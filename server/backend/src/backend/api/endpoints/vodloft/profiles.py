"""Domain-scoped Local Media Profiles using WireLoft's template engine."""

from pathlib import Path
import ipaddress
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import ArtifactPlacement, Domain, MediaItem, MediaServerTarget, SourceReference
from backend.types.local_media_profile_types import PreferredFormat
from backend.utils.helpers import slugify
from backend.utils.output_template import render_output_template, finalize_output_path
from config import get_settings

router = APIRouter(prefix="/vodloft", tags=["VodLoft profiles"])

ALLOWED_FIELDS = frozenset({"domain", "title", "id", "upstream_id", "media_type", "collection"})
Kind = Literal["video", "movie", "movie_extra"]


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    domain: str
    preferred_format: PreferredFormat = PreferredFormat.FORMAT_1080P
    applicable_kinds: list[Kind] = Field(default_factory=lambda: ["video", "movie", "movie_extra"])
    output_template: str = "/downloads/{{ domain }}/{{ title }} - {{ id }}.ext"
    enabled: bool = True
    delivery_target_ids: list[int] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, domain):
        try:
            hostname = domain.strip().rstrip(".").lower().encode("idna").decode("ascii")
        except (UnicodeError, AttributeError) as exc:
            raise ValueError("Enter a website Domain such as example.com") from exc
        if len(hostname) > 253 or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
            hostname):
            raise ValueError("Enter a website Domain such as example.com")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            return hostname
        raise ValueError("IP addresses are not website Domains")

    @field_validator("applicable_kinds")
    @classmethod
    def nonempty(cls, kinds):
        if not kinds:
            raise ValueError("Select at least one applicable media type")
        return list(dict.fromkeys(kinds))

    @field_validator("output_template")
    @classmethod
    def validate_template(cls, template):
        render_output_template(template, {"domain": "example.com", "title": "Example",
            "id": 1, "upstream_id": "123", "media_type": "video", "collection": ""},
            allowed_fields=ALLOWED_FIELDS)
        return template


def output_path(profile: DomainLocalMediaProfile, item: MediaItem, domain: Domain,
                reference: SourceReference, extension: str, collection: str = "") -> Path:
    return output_path_from_spec(profile.output_template, {
        "domain": domain.hostname, "title": item.user_title or item.title,
        "id": item.id, "upstream_id": reference.upstream_id,
        "media_type": item.kind, "collection": collection,
    }, extension)


def output_path_from_spec(template: str, values: dict, extension: str) -> Path:
    rendered = render_output_template(template, values, allowed_fields=ALLOWED_FIELDS)
    sanitized = finalize_output_path(rendered, extension)
    root = Path(get_settings().download_settings.download_root).resolve()
    path = (root / sanitized.removeprefix("/downloads/")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Output path escapes the download root")
    return path


def _serialize(profile: DomainLocalMediaProfile, domain: Domain) -> dict:
    return {"id": profile.id, "name": profile.name, "domain": domain.hostname,
        "preferred_format": profile.preferred_format, "output_template": profile.output_template,
        "applicable_kinds": profile.applicable_kinds, "enabled": profile.enabled,
        "delivery_target_ids": profile.delivery_target_ids}


def _validate_targets(session, ids: list[int]) -> None:
    if len(ids) != len(set(ids)) or any(not session.get(MediaServerTarget, target_id) for target_id in ids):
        raise HTTPException(422, "Select existing delivery targets without duplicates")


@router.get("/domains")
def domains():
    with get_session() as session:
        return [{"id": d.id, "hostname": d.hostname, "display_name": d.display_name}
                for d in session.scalars(select(Domain).order_by(Domain.hostname)).all()]


@router.get("/profiles")
def profiles(domain: str | None = None):
    with get_session() as session:
        query = select(DomainLocalMediaProfile)
        if domain:
            domain_record = session.scalar(select(Domain).where(Domain.hostname == domain))
            if not domain_record:
                return []
            query = query.where(DomainLocalMediaProfile.domain_id == domain_record.id)
        return [_serialize(p, session.get(Domain, p.domain_id)) for p in session.scalars(query).all()]


@router.post("/profiles", status_code=201)
def create_profile(data: ProfileInput):
    with get_session() as session:
        domain = session.scalar(select(Domain).where(Domain.hostname == data.domain))
        if not domain:
            domain = Domain(hostname=data.domain, display_name=data.domain)
            session.add(domain)
            session.flush()
        _validate_targets(session, data.delivery_target_ids)
        profile = DomainLocalMediaProfile(name=data.name, slug=slugify(data.name),
            domain_id=domain.id, preferred_format=data.preferred_format.value,
            output_template=data.output_template, applicable_kinds=data.applicable_kinds,
            enabled=data.enabled, delivery_target_ids=data.delivery_target_ids)
        session.add(profile)
        try:
            session.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "A Local Media Profile with this name or output already exists") from exc
        return _serialize(profile, domain)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, data: ProfileInput):
    with get_session() as session:
        profile = session.get(DomainLocalMediaProfile, profile_id)
        domain = session.scalar(select(Domain).where(Domain.hostname == data.domain.lower()))
        if not profile or not domain:
            raise HTTPException(404, "Profile or Domain not found")
        _validate_targets(session, data.delivery_target_ids)
        profile.name, profile.slug = data.name, slugify(data.name)
        profile.domain_id, profile.preferred_format = domain.id, data.preferred_format.value
        profile.output_template, profile.applicable_kinds, profile.enabled = (
            data.output_template, data.applicable_kinds, data.enabled)
        profile.delivery_target_ids = data.delivery_target_ids
        try:
            session.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Profile name or output conflicts with another profile") from exc
        return _serialize(profile, domain)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int):
    with get_session() as session:
        profile = session.get(DomainLocalMediaProfile, profile_id)
        if not profile:
            raise HTTPException(404, "Profile not found")
        if session.scalar(select(ArtifactPlacement.id).where(ArtifactPlacement.profile_id == profile_id)):
            raise HTTPException(409, "Remove the profile's file placements before deleting it")
        session.delete(profile)
        session.commit()


@router.post("/profiles/{profile_id}/preview")
def preview(profile_id: int, item_id: int, extension: str = "mp4"):
    with get_session() as session:
        profile = session.get(DomainLocalMediaProfile, profile_id)
        item = session.get(MediaItem, item_id)
        if not profile or not item or item.domain_id != profile.domain_id or item.kind not in profile.applicable_kinds:
            raise HTTPException(404, "This profile does not apply to the media item")
        domain = session.get(Domain, item.domain_id)
        reference = session.scalar(select(SourceReference).where(SourceReference.item_id == item_id))
        try:
            return {"path": str(output_path(profile, item, domain, reference, extension))}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
