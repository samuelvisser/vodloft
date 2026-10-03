"""Domain-scoped Local Media Profiles using WireLoft's template engine."""

from pathlib import Path
import ipaddress
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from source_contracts import RepresentationPolicy
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import ArtifactPlacement, CollectionEntry, Domain, MediaItem, MediaServerTarget, SourceReference
from backend.types.local_media_profile_types import PreferredFormat
from backend.utils.helpers import slugify
from backend.utils.output_template import render_output_template, finalize_output_path
from config import get_settings

router = APIRouter(prefix="/vodloft", tags=["VodLoft profiles"])

ALLOWED_FIELDS = frozenset({"domain", "title", "id", "upstream_id", "media_type", "collection",
    "group", "episode_number", "published_date", "author", "duration", "movie_year"})
Kind = Literal["video", "movie", "movie_extra"]


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    domain: str
    preferred_format: PreferredFormat = PreferredFormat.FORMAT_1080P
    applicable_kinds: list[Kind] = Field(default_factory=lambda: ["video", "movie", "movie_extra"])
    output_template: str = "/downloads/{{ domain }}/{{ title }} - {{ id }}.ext"
    enabled: bool = True
    delivery_target_ids: list[int] = Field(default_factory=list)
    representation: RepresentationPolicy = Field(default_factory=RepresentationPolicy)

    @model_validator(mode="after")
    def compatible_representation(self):
        audio = self.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY
        if (audio and self.representation.container in {"mp4", "mkv"} or
            not audio and self.representation.container in {"mp3", "m4a", "opus"} or
            audio and self.representation.video_codec != "source"):
            raise ValueError("Choose a container and codecs compatible with the profile's audio or video format")
        if audio and self.representation.subtitles:
            raise ValueError("Embedded subtitles require a video profile")
        codec = {"mp3": "mp3", "m4a": "aac", "opus": "opus"}.get(self.representation.container)
        if codec and self.representation.audio_codec not in {"source", codec}:
            raise ValueError("The selected audio codec is incompatible with the selected container")
        return self

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
            "id": 1, "upstream_id": "123", "media_type": "video", "collection": "",
            "group": "Season 1", "episode_number": "1", "published_date": "2026-01-01",
            "author": "Example", "duration": 60, "movie_year": 2026},
            allowed_fields=ALLOWED_FIELDS)
        return template


def output_path(profile: DomainLocalMediaProfile, item: MediaItem, domain: Domain,
                reference: SourceReference, extension: str, collection: str = "") -> Path:
    return output_path_from_spec(profile.output_template, template_values(item, domain, reference, collection=collection), extension)


def template_values(item: MediaItem, domain: Domain, reference: SourceReference,
                    *, collection: str = "", membership: CollectionEntry | None = None) -> dict:
    return {
        "domain": domain.hostname, "title": item.user_title or item.title,
        "id": item.id, "upstream_id": reference.upstream_id,
        "media_type": item.kind, "collection": collection,
        "group": membership.group or "" if membership else "",
        "episode_number": membership.episode_number or str(membership.position) if membership else "",
        "published_date": item.published_at.date().isoformat() if item.published_at else "",
        "author": (item.normalized_metadata or {}).get("author") or "",
        "duration": item.duration or 0, "movie_year": (item.normalized_metadata or {}).get("movie_year") or "",
    }


def output_path_from_spec(template: str, values: dict, extension: str) -> Path:
    rendered = render_output_template(template, values, allowed_fields=ALLOWED_FIELDS)
    sanitized = finalize_output_path(rendered, extension)
    root = Path(get_settings().download_settings.download_root).resolve()
    path = (root / sanitized.removeprefix("/downloads/")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Output path escapes the download root")
    if path.is_relative_to(root / "vodloft") or path.is_relative_to(root / "vodloft-feeds"):
        raise ValueError("Output path is reserved for VodLoft-managed representations")
    return path


def _serialize(profile: DomainLocalMediaProfile, domain: Domain) -> dict:
    return {"id": profile.id, "name": profile.name, "domain": domain.hostname,
        "preferred_format": profile.preferred_format, "output_template": profile.output_template,
        "applicable_kinds": profile.applicable_kinds, "enabled": profile.enabled,
        "impairment": profile.impairment,
        "representation": RepresentationPolicy.model_validate(profile.representation or {}).model_dump(),
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


@router.get("/profiles/template-sources")
def template_sources(domain: str, kind: Kind = "video", search: str = "", limit: int = 30):
    with get_session() as session:
        website = session.scalar(select(Domain).where(Domain.hostname == domain))
        if not website:
            return []
        query = select(MediaItem).where(MediaItem.domain_id == website.id, MediaItem.kind == kind)
        if search:
            query = query.where(MediaItem.title.ilike("%" + search[:200] + "%"))
        return [{"id": item.id, "label": item.user_title or item.title}
            for item in session.scalars(query.order_by(MediaItem.id.desc()).limit(min(max(limit, 1), 100))).all()]


class TemplatePreviewInput(BaseModel):
    domain: str
    kind: Kind = "video"
    template: str = Field(min_length=1, max_length=20000)
    item_id: int | None = None
    extension: str = Field(default="mp4", pattern="^(mp4|mkv|webm|mp3|m4a|opus)$")


@router.post("/profiles/template-preview")
def template_preview(data: TemplatePreviewInput):
    with get_session() as session:
        website = session.scalar(select(Domain).where(Domain.hostname == data.domain))
        item = session.get(MediaItem, data.item_id) if data.item_id else None
        if data.item_id and (not item or not website or item.domain_id != website.id or item.kind != data.kind):
            raise HTTPException(422, "Choose an example from this Domain and media type")
        membership = session.scalar(select(CollectionEntry).where(CollectionEntry.item_id == item.id)) if item else None
        collection = session.get(MediaItem, membership.collection_id) if membership else None
        reference = session.scalar(select(SourceReference).where(SourceReference.item_id == item.id)) if item else None
        if item and reference:
            values = template_values(item, website, reference, membership=membership,
                collection=collection.user_title or collection.title if collection else "")
        else:
            values = {"domain": data.domain, "title": "Example title", "id": 1,
                "upstream_id": "example-id", "media_type": data.kind, "collection": "Example collection",
                "group": "Season 1", "episode_number": "1", "published_date": "2026-01-01",
                "author": "Example creator", "duration": 1800, "movie_year": 2026}
        try:
            return {"path": str(output_path_from_spec(data.template, values, data.extension)), "values": values}
        except (ValueError, Exception) as exc:
            raise HTTPException(422, "Template is invalid: " + str(exc)[:400]) from exc


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
            enabled=data.enabled, delivery_target_ids=data.delivery_target_ids,
            representation=data.representation.model_dump())
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
        profile.representation = data.representation.model_dump()
        profile.impairment = None
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
