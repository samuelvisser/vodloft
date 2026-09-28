"""Persisted Collection download policies; jobs remain independently durable."""

import logging
import threading
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import CollectionDownloadProfile, CollectionEntry, CollectionScan, MediaItem
from backend.api.endpoints.vodloft.router import queue_download, _run_download, refresh_collection, _reference_for

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vodloft", tags=["VodLoft collection automation"])


class DownloadPolicyInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    local_profile_ids: list[int] = Field(min_length=1)
    source_reference_id: int | None = None
    backfill: str = Field(default="newest", pattern="^(all|newest|date_range|metadata_only)$")
    newest_count: int = Field(default=10, ge=1, le=1000)
    published_after: date | None = None
    published_before: date | None = None
    title_contains: str | None = Field(default=None, max_length=200)
    refresh_minutes: int = Field(default=60, ge=15, le=10080)
    enabled: bool = True

    @model_validator(mode="after")
    def date_range_is_valid(self):
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("The publication start must be on or before the end")
        if self.backfill == "date_range" and not (self.published_after or self.published_before):
            raise ValueError("Choose a publication date for date-range backfill")
        return self


def _serialize(policy: CollectionDownloadProfile) -> dict:
    return {"id": policy.id, "collection_id": policy.collection_id, "name": policy.name,
            "local_profile_ids": policy.local_profile_ids,
            "source_reference_id": policy.source_reference_id, "backfill": policy.backfill,
            "newest_count": policy.newest_count, "published_after": policy.published_after,
            "published_before": policy.published_before, "title_contains": policy.title_contains,
            "refresh_minutes": policy.refresh_minutes,
            "enabled": policy.enabled, "last_scan_at": policy.last_scan_at}


@router.get("/library/{collection_id}/download-profiles")
def list_profiles(collection_id: int):
    with get_session() as session:
        if not (item := session.get(MediaItem, collection_id)) or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        return [_serialize(p) for p in session.scalars(select(CollectionDownloadProfile).where(
            CollectionDownloadProfile.collection_id == collection_id)).all()]


@router.post("/library/{collection_id}/download-profiles", status_code=201)
def create_profile(collection_id: int, data: DownloadPolicyInput):
    with get_session() as session:
        if not (item := session.get(MediaItem, collection_id)) or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        reference = _reference_for(session, collection_id, reference_id=data.source_reference_id)
        if not reference:
            raise HTTPException(422, "Select an available Source reference for this Collection")
        for profile_id in set(data.local_profile_ids):
            if not session.get(DomainLocalMediaProfile, profile_id):
                raise HTTPException(422, f"Local Media Profile {profile_id} does not exist")
        profile = CollectionDownloadProfile(collection_id=collection_id,
            **(data.model_dump() | {"source_reference_id": reference.id,
                                    "local_profile_ids": list(dict.fromkeys(data.local_profile_ids))}))
        session.add(profile)
        session.commit()
        return _serialize(profile)


@router.put("/download-profiles/{profile_id}")
def update_profile(profile_id: int, data: DownloadPolicyInput):
    with get_session() as session:
        profile = session.get(CollectionDownloadProfile, profile_id)
        if not profile:
            raise HTTPException(404, "Download Profile not found")
        reference = _reference_for(session, profile.collection_id, reference_id=data.source_reference_id)
        if not reference:
            raise HTTPException(422, "Select an available Source reference for this Collection")
        for local_id in set(data.local_profile_ids):
            if not session.get(DomainLocalMediaProfile, local_id):
                raise HTTPException(422, f"Local Media Profile {local_id} does not exist")
        for key, value in data.model_dump().items():
            setattr(profile, key, value)
        profile.source_reference_id = reference.id
        session.commit()
        return _serialize(profile)


@router.delete("/download-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int):
    with get_session() as session:
        profile = session.get(CollectionDownloadProfile, profile_id)
        if not profile:
            raise HTTPException(404, "Download Profile not found")
        session.delete(profile)
        session.commit()


def schedule_profile(profile_id: int, *, dispatch: bool = True) -> dict:
    with get_session() as session:
        policy = session.get(CollectionDownloadProfile, profile_id)
        if not policy or not policy.enabled:
            raise HTTPException(404, "Enabled Download Profile not found")
        entries = session.scalars(select(CollectionEntry).where(
            CollectionEntry.collection_id == policy.collection_id).order_by(CollectionEntry.position)).all()
        if policy.backfill == "newest":
            # Source ordering is not necessarily reverse chronological (a
            # series may enumerate its first season first).
            def newest_key(entry):
                published = session.get(MediaItem, entry.item_id).published_at
                timestamp = (published.replace(tzinfo=published.tzinfo or timezone.utc).timestamp()
                             if published else float("-inf"))
                return timestamp, -entry.position

            entries = sorted(entries, key=newest_key, reverse=True)[:policy.newest_count]
        local_profiles = [session.get(DomainLocalMediaProfile, pid) for pid in policy.local_profile_ids]
        compatible: list[tuple[int, int]] = []
        skipped: list[dict] = []
        for entry in entries:
            item = session.get(MediaItem, entry.item_id)
            if item.kind == "collection":
                skipped.append({"item_id": item.id, "reason": "Nested Collection requires an explicit subscription"})
                continue
            if item.capabilities is not None and "download" not in item.capabilities:
                skipped.append({"item_id": item.id, "reason": "Source does not advertise download for this item"})
                continue
            if policy.title_contains and policy.title_contains.casefold() not in (item.user_title or item.title).casefold():
                skipped.append({"item_id": item.id, "reason": "Title does not match the Download Profile filter"})
                continue
            if policy.backfill == "date_range" or policy.published_after or policy.published_before:
                if not item.published_at:
                    skipped.append({"item_id": item.id, "reason": "Publication date is unknown"})
                    continue
                published = item.published_at.date()
                if (policy.published_after and published < policy.published_after or
                    policy.published_before and published > policy.published_before):
                    skipped.append({"item_id": item.id, "reason": "Outside the publication date range"})
                    continue
            candidates = [p for p in local_profiles if p and p.enabled and
                          p.domain_id == item.domain_id and item.kind in p.applicable_kinds]
            if not candidates:
                skipped.append({"item_id": item.id, "reason": "No applicable Local Media Profile for the item's Domain"})
            elif policy.backfill != "metadata_only":
                compatible.extend((item.id, p.id) for p in candidates)
        collection_id = policy.collection_id
        collection_reference_id = policy.source_reference_id
    queued: list[int] = []
    for item_id, local_id in compatible:
        try:
            job_id, state, created = queue_download(item_id, local_id, collection_id=collection_id,
                collection_reference_id=collection_reference_id)
            if created and job_id is not None:
                queued.append(job_id)
        except Exception:
            logger.exception("Could not queue Collection %s item %s", collection_id, item_id)
            skipped.append({"item_id": item_id, "reason": "Could not queue acquisition"})
    if dispatch:
        for job_id in queued:
            threading.Thread(target=_run_download, args=(job_id,), daemon=True,
                             name=f"vodloft-collection-{job_id}").start()
    return {"queued_job_ids": queued, "skipped": skipped, "considered": len(entries)}


@router.post("/download-profiles/{profile_id}/run")
def run_profile(profile_id: int):
    return schedule_profile(profile_id)


@router.get("/library/{collection_id}/scans")
def scans(collection_id: int):
    with get_session() as session:
        return [{"id": s.id, "source_id": s.source_id, "complete": s.complete,
                 "entry_count": s.entry_count, "error": s.error,
                 "has_checkpoint": bool(s.next_cursor), "runtime_version": s.runtime_version,
                 "created_at": s.created_at}
                for s in session.scalars(select(CollectionScan).where(
                    CollectionScan.collection_id == collection_id).order_by(CollectionScan.id.desc()).limit(50)).all()]


def refresh_due_collections() -> None:
    """A periodic sweep; a persisted scan clock survives application restarts."""
    with get_session() as session:
        profiles = session.scalars(select(CollectionDownloadProfile).where(CollectionDownloadProfile.enabled.is_(True))).all()
        due = []
        now = datetime.now(timezone.utc)
        for profile in profiles:
            last = profile.last_scan_at
            if not last or now - last.replace(tzinfo=last.tzinfo or timezone.utc) >= timedelta(minutes=profile.refresh_minutes):
                profile.last_scan_at = now
                due.append((profile.id, profile.collection_id, profile.source_reference_id))
        session.commit()
    for profile_id, collection_id, reference_id in due:
        try:
            refresh_collection(collection_id, reference_id=reference_id)
            schedule_profile(profile_id)
        except Exception:
            logger.exception("Collection %s automatic refresh failed", collection_id)
