"""Review choices stay explicit; a preview never becomes acquisition demand."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from backend.api.endpoints.vodloft.router import ImportRequest, import_media
from backend.api.models.vodloft import LibraryItemResponse
from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import CollectionDownloadProfile, Domain, LibraryRequest, SourceReference
from backend.security.permissions import principal, require_connection

router = APIRouter(prefix='/vodloft', tags=['VodLoft import review'])


class ImportChoices(BaseModel):
    local_profile_ids: list[int] = Field(default_factory=list, max_length=12)
    backfill: Literal['metadata_only', 'newest', 'date_range', 'all'] = 'metadata_only'
    newest_count: int = Field(default=10, ge=1, le=1000)
    published_after: date | None = None
    published_before: date | None = None
    refresh_minutes: int = Field(default=60, ge=15, le=10080)
    confirm_archive: bool = False

    @model_validator(mode='after')
    def valid_backfill(self):
        if len(self.local_profile_ids) != len(set(self.local_profile_ids)) or any(p <= 0 for p in self.local_profile_ids):
            raise ValueError('Choose distinct existing Local Media Profiles')
        if self.backfill != 'metadata_only' and not self.local_profile_ids:
            raise ValueError('Select Local Media Profiles before enabling Collection downloads')
        if self.backfill == 'all' and not self.confirm_archive:
            raise ValueError('Confirm downloading the entire Collection archive')
        if self.backfill == 'date_range' and not (self.published_after or self.published_before):
            raise ValueError('Select a publication date for date-range backfill')
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError('The publication start must be on or before the end')
        return self


class ConfirmImportInput(ImportRequest):
    choices: ImportChoices = Field(default_factory=ImportChoices)


class ConfirmImportResponse(BaseModel):
    item: LibraryItemResponse
    request_ids: list[int] = Field(default_factory=list)
    download_profile_id: int | None = None
    operation_id: str | None = None
    message: str


@router.post('/import/confirm', response_model=ConfirmImportResponse)
def confirm_import(data: ConfirmImportInput, request: Request, background: BackgroundTasks):
    actor, snapshot, choices = principal(request), data.snapshot, data.choices
    require_connection(request, data.connection_id)
    if snapshot.kind != 'collection' and choices.backfill != 'metadata_only':
        raise HTTPException(422, 'Backfill applies only to Collections')
    if snapshot.kind == 'collection' and choices.backfill != 'metadata_only' and actor.role != 'admin':
        raise HTTPException(403, 'An administrator must configure automatic Collection downloads')
    # Validate choices before importing anything. The import re-resolves identity
    # and metadata, and request_media remains authoritative for quotas and grants.
    with get_session() as session:
        for profile_id in choices.local_profile_ids:
            profile = session.get(DomainLocalMediaProfile, profile_id)
            domain = session.get(Domain, profile.domain_id) if profile else None
            if not profile or profile.deleted or not profile.enabled or profile.impairment or (
                snapshot.kind != 'collection' and (domain.hostname != snapshot.reference.domain or snapshot.kind not in profile.applicable_kinds)):
                raise HTTPException(422, 'Choose compatible, enabled Local Media Profiles')
        if snapshot.kind != 'collection' and choices.local_profile_ids:
            active = session.scalar(select(func.count()).select_from(LibraryRequest).where(
                LibraryRequest.user_key == actor.key, LibraryRequest.state.in_(['pending', 'approved'])))
            if active + len(choices.local_profile_ids) > actor.request_quota:
                raise HTTPException(429, 'The local account has insufficient open request quota')
    imported = import_media(ImportRequest(snapshot=snapshot, connection_id=data.connection_id,
        existing_item_id=data.existing_item_id, confirm_same_edition=data.confirm_same_edition), request)
    if imported.kind != snapshot.kind:
        # Explicitly reclassified existing identities must use their own profile
        # applicability. Metadata-only linking remains supported.
        if choices.local_profile_ids:
            raise HTTPException(409, 'The existing identity has another Media Type; select its profiles in Library')
    with get_session() as session:
        reference = session.scalar(select(SourceReference).join(Domain, Domain.id == SourceReference.domain_id).where(
            SourceReference.item_id == imported.id, SourceReference.source_id == snapshot.reference.source_id,
            Domain.hostname == snapshot.reference.domain, SourceReference.namespace == snapshot.reference.namespace,
            SourceReference.upstream_id == snapshot.reference.upstream_id,
            SourceReference.connection_key == (data.connection_id or 0)))
        if not reference:
            raise HTTPException(409, 'Source media changed during confirmation; resolve and review again')
        reference_id = reference.id
    result = ConfirmImportResponse(item=imported, message='Media saved to Library')
    if imported.kind == 'collection':
        if choices.backfill != 'metadata_only':
            from backend.api.endpoints.vodloft.automation import DownloadPolicyInput, create_profile
            policy_input = DownloadPolicyInput(name=f'{imported.title[:95]} downloads',
                local_profile_ids=choices.local_profile_ids, source_reference_id=reference_id,
                backfill=choices.backfill, newest_count=choices.newest_count,
                published_after=choices.published_after, published_before=choices.published_before,
                refresh_minutes=choices.refresh_minutes)
            with get_session() as session:
                existing = next((p for p in session.scalars(select(CollectionDownloadProfile).where(
                    CollectionDownloadProfile.collection_id == imported.id,
                    CollectionDownloadProfile.source_reference_id == reference_id))
                    if p.enabled and all(getattr(p, name) == value for name, value in policy_input.model_dump().items() if name != 'name')), None)
                policy_id = existing.id if existing else None
            result.download_profile_id = policy_id or create_profile(imported.id, policy_input).id
            result.message = 'Collection saved; the selected backfill will run after synchronization'
        if actor.manages_library:
            from backend.services.vodloft_sync import enqueue
            result.operation_id = enqueue(imported.id, reference_id, full=True)
            if not result.download_profile_id:
                result.message = 'Collection saved; metadata synchronization queued without downloads'
    elif choices.local_profile_ids:
        from backend.api.endpoints.vodloft.requests import RequestInput, request_media
        for profile_id in choices.local_profile_ids:
            demand = request_media(imported.id, RequestInput(profile_id=profile_id, reference_id=reference_id), request, background)
            result.request_ids.append(demand.id)
        result.message = 'Media saved; download requests follow your account approval policy'
    return result
