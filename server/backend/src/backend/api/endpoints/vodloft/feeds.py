"""Revocable collection feeds with immutable enclosure copies."""

import mimetypes
import os
import secrets
import shutil
import tempfile
import threading
from datetime import date
from email.utils import format_datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, HTTPException, Request
from backend.security.permissions import principal, user_enabled
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select

from backend.db import get_session
from backend.db.models.vodloft import (AcquisitionJob, Artifact, CollectionDownloadProfile,
    CollectionEntry, CollectionStreamProfile, FeedSubscription, LiveAdmission, MediaItem,
    PublishedEntry, SourceReference, MediaServerTarget)
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from config import get_settings
from backend.services.vodloft_collections import known_groups, matches_membership

api_router = APIRouter(prefix="/vodloft", tags=["VodLoft feeds"])
public_router = APIRouter(prefix="/feeds/vodloft", tags=["VodLoft feeds"])
_audio_extensions = frozenset({".mp3", ".m4a", ".aac"})
_video_extensions = frozenset({".mp4", ".mkv", ".webm", ".mov"})


class StreamProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    format: str = Field(default="audio", pattern="^(audio|video)$")
    published_after: date | None = None
    published_before: date | None = None
    title_contains: str | None = Field(default=None, max_length=200)
    selected_groups: list[str] | None = Field(default=None, max_length=1000)
    include_future_groups: bool = True
    member_roles: list[str] | None = Field(default=None, max_length=100)
    max_items: int = Field(default=0, ge=0, le=10000)
    feed_title: str | None = Field(default=None, max_length=200)
    local_only: bool = True
    include_live: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_dates(self):
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("The publication start must be on or before the end")
        return self


class StreamProfileResponse(StreamProfileInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    collection_id: int


def _stream_profile(profile: CollectionStreamProfile) -> StreamProfileResponse:
    return StreamProfileResponse.model_validate(profile)


@api_router.get("/library/{collection_id}/stream-profiles")
def stream_profiles(collection_id: int):
    with get_session() as session:
        if not (item := session.get(MediaItem, collection_id)) or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        return [_stream_profile(p) for p in session.scalars(select(CollectionStreamProfile).where(
            CollectionStreamProfile.collection_id == collection_id)).all()]


@api_router.post("/library/{collection_id}/stream-profiles", status_code=201)
def create_stream_profile(collection_id: int, data: StreamProfileInput):
    with get_session() as session:
        if not (item := session.get(MediaItem, collection_id)) or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        profile = CollectionStreamProfile(collection_id=collection_id,
            known_groups=known_groups(session, collection_id), **data.model_dump())
        session.add(profile)
        session.commit()
        result = _stream_profile(profile)
    reconcile_live_admissions(collection_id)
    return result


@api_router.put("/stream-profiles/{profile_id}")
def update_stream_profile(profile_id: int, data: StreamProfileInput):
    with get_session() as session:
        profile = session.get(CollectionStreamProfile, profile_id)
        if not profile:
            raise HTTPException(404, "Stream Profile not found")
        # A published enclosure never changes format or bytes. Create a new
        # Stream Profile for a different representation after publication.
        published = session.scalar(select(FeedSubscription.id).where(
            FeedSubscription.stream_profile_id == profile_id))
        if published and profile.format != data.format:
            raise HTTPException(409, "Revoke this feed before changing its representation")
        if profile.selected_groups != data.selected_groups:
            profile.known_groups = known_groups(session, profile.collection_id)
        for key, value in data.model_dump().items():
            setattr(profile, key, value)
        collection_id = profile.collection_id
        session.commit()
        result = _stream_profile(profile)
    reconcile_live_admissions(collection_id)
    return result


@api_router.delete("/stream-profiles/{profile_id}", status_code=204)
def delete_stream_profile(profile_id: int):
    with get_session() as session:
        profile = session.get(CollectionStreamProfile, profile_id)
        if not profile:
            raise HTTPException(404, "Stream Profile not found")
        subscriptions = session.scalars(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile_id)).all()
        subscription_ids = [subscription.id for subscription in subscriptions]
        for subscription in subscriptions:
            session.delete(subscription)
        session.flush()
        session.execute(delete(LiveAdmission).where(LiveAdmission.stream_profile_id == profile_id))
        session.delete(profile)
        session.commit()
    for subscription_id in subscription_ids:
        _remove_published(subscription_id)


def _feed_root() -> Path:
    root = Path(get_settings().download_settings.download_root).resolve() / "vodloft-feeds"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _remove_published(subscription_id: int) -> None:
    shutil.rmtree(_feed_root() / str(subscription_id), ignore_errors=True)


@api_router.post("/library/{collection_id}/feed")
def subscribe(collection_id: int, request: Request):
    with get_session() as session:
        item = session.get(MediaItem, collection_id)
        if not item or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.collection_id == collection_id, FeedSubscription.stream_profile_id.is_(None),
            FeedSubscription.user_key == principal(request).key))
        if not subscription:
            subscription = FeedSubscription(collection_id=collection_id, token=secrets.token_urlsafe(32),
                                            user_key=principal(request).key)
            session.add(subscription)
            session.commit()
        return {"url": str(request.url_for("vodloft_feed", token=subscription.token))}


@api_router.delete("/library/{collection_id}/feed")
def revoke(collection_id: int, request: Request):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.collection_id == collection_id, FeedSubscription.stream_profile_id.is_(None),
            FeedSubscription.user_key == principal(request).key))
        if not subscription:
            raise HTTPException(404, "Collection feed not found")
        subscription_id = subscription.id
        session.delete(subscription)
        session.commit()
    _remove_published(subscription_id)
    return {"revoked": True}


@api_router.post("/stream-profiles/{profile_id}/feed")
def subscribe_profile(profile_id: int, request: Request):
    with get_session() as session:
        profile = session.get(CollectionStreamProfile, profile_id)
        if not profile or not profile.enabled:
            raise HTTPException(404, "Enabled Stream Profile not found")
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile_id,
            FeedSubscription.user_key == principal(request).key))
        if not subscription:
            subscription = FeedSubscription(collection_id=profile.collection_id,
                stream_profile_id=profile_id, token=secrets.token_urlsafe(32),
                user_key=principal(request).key)
            session.add(subscription)
            session.commit()
        return {"url": str(request.url_for("vodloft_feed", token=subscription.token))}


@api_router.delete("/stream-profiles/{profile_id}/feed")
def revoke_profile(profile_id: int, request: Request):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile_id,
            FeedSubscription.user_key == principal(request).key))
        if not subscription:
            raise HTTPException(404, "Stream Profile feed not found")
        subscription_id = subscription.id
        session.delete(subscription)
        session.commit()
    _remove_published(subscription_id)
    return {"revoked": True}


@api_router.post("/stream-profiles/{profile_id}/feed/rotate")
def rotate_profile_feed(profile_id: int, request: Request):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile_id,
            FeedSubscription.user_key == principal(request).key))
        if not subscription:
            raise HTTPException(404, "Stream Profile feed not found")
        subscription.token = secrets.token_urlsafe(32)
        session.commit()
        return {"url": str(request.url_for("vodloft_feed", token=subscription.token))}


def _publish(session, subscription: FeedSubscription, item_id: int) -> PublishedEntry | None:
    existing = session.scalar(select(PublishedEntry).where(
        PublishedEntry.subscription_id == subscription.id, PublishedEntry.item_id == item_id))
    if existing:
        return existing if Path(existing.path).is_file() else None
    profile = session.get(CollectionStreamProfile, subscription.stream_profile_id) if subscription.stream_profile_id else None
    extensions = (_audio_extensions if profile.format == "audio" else _video_extensions) if profile else None
    artifact = next((a for a in session.scalars(select(Artifact).where(
        Artifact.item_id == item_id).order_by(Artifact.id.desc())).all()
        if extensions is None or Path(a.path).suffix.lower() in extensions), None)
    if not artifact or not Path(artifact.path).is_file():
        return None
    source = Path(artifact.path).resolve()
    root = Path(get_settings().download_settings.download_root).resolve() / "vodloft"
    if not source.is_relative_to(root):
        return None
    directory = _feed_root() / str(subscription.id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{item_id}{source.suffix.lower()}"
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".publishing-", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, temporary)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        # Exclusive creation prevents two feed requests (or a crash retry) from
        # changing bytes at a published enclosure URL.
        os.link(temporary_path, destination)
    except FileExistsError:
        pass
    finally:
        temporary_path.unlink(missing_ok=True)
    entry = PublishedEntry(subscription_id=subscription.id, item_id=item_id,
                           path=str(destination), size=destination.stat().st_size)
    session.add(entry)
    session.flush()
    return entry


def reconcile_live_admissions(collection_id: int) -> None:
    """Freeze live admission until a local archive arrives or acquisition fails."""
    from backend.api.endpoints.vodloft.router import queue_download, _run_download, _reference_for

    queued = []
    with get_session() as session:
        profiles = session.scalars(select(CollectionStreamProfile).where(
            CollectionStreamProfile.collection_id == collection_id,
            CollectionStreamProfile.enabled.is_(True),
            CollectionStreamProfile.include_live.is_(True))).all()
        entries = session.scalars(select(CollectionEntry).where(
            CollectionEntry.collection_id == collection_id)).all()
        policies = session.scalars(select(CollectionDownloadProfile).where(
            CollectionDownloadProfile.collection_id == collection_id,
            CollectionDownloadProfile.enabled.is_(True))).all()
        for profile in profiles:
            for entry in entries:
                if not matches_membership(entry, profile):
                    continue
                item = session.get(MediaItem, entry.item_id)
                admission = session.scalar(select(LiveAdmission).where(
                    LiveAdmission.stream_profile_id == profile.id,
                    LiveAdmission.item_id == item.id))
                if not item.is_live and not admission:
                    continue
                if profile.title_contains and profile.title_contains.casefold() not in (
                    item.user_title or item.title).casefold():
                    continue
                if profile.published_after or profile.published_before:
                    if not item.published_at:
                        continue
                    published = item.published_at.date()
                    if (profile.published_after and published < profile.published_after or
                        profile.published_before and published > profile.published_before):
                        continue
                extensions = _audio_extensions if profile.format == "audio" else _video_extensions
                local = any(Path(a.path).is_file() and Path(a.path).suffix.lower() in extensions
                    for a in session.scalars(select(Artifact).where(Artifact.item_id == item.id)).all())
                candidate = None
                for policy in policies:
                    if not matches_membership(entry, policy) or policy.backfill == "metadata_only" or (
                        policy.title_contains and policy.title_contains.casefold() not in
                            (item.user_title or item.title).casefold()):
                        continue
                    if policy.published_after or policy.published_before:
                        if not item.published_at:
                            continue
                        published = item.published_at.date()
                        if (policy.published_after and published < policy.published_after or
                            policy.published_before and published > policy.published_before):
                            continue
                    reference = _reference_for(session, item.id, collection_id=collection_id,
                        collection_reference_id=policy.source_reference_id)
                    for profile_id in policy.local_profile_ids:
                        media_profile = session.get(DomainLocalMediaProfile, profile_id)
                        if (reference and media_profile and media_profile.enabled and
                            media_profile.domain_id == item.domain_id and
                            item.kind in media_profile.applicable_kinds and
                            (media_profile.preferred_format == "format_audio_only") ==
                                (profile.format == "audio")):
                            candidate = (policy.id, media_profile.id, reference.id)
                            break
                    if candidate:
                        break
                if not admission:
                    if profile.local_only and not candidate:
                        continue
                    reference = (session.get(SourceReference, candidate[2]) if candidate else
                                 _reference_for(session, item.id))
                    if not reference:
                        continue
                    admission = LiveAdmission(stream_profile_id=profile.id,
                        item_id=item.id, source_reference_id=reference.id,
                        state="local" if local else "upstream")
                    session.add(admission)
                if local:
                    admission.state = "local"
                else:
                    job = session.scalar(select(AcquisitionJob).where(
                        AcquisitionJob.item_id == item.id,
                        AcquisitionJob.reference_id == admission.source_reference_id)
                        .order_by(AcquisitionJob.id.desc()))
                    admission.state = ("failed" if profile.local_only and not candidate or
                        job and job.state in {"failed", "canceled"} else
                        "upstream" if item.capabilities is None or "stream_lease" in item.capabilities
                        else "waiting")
                    if profile.local_only and candidate and admission.state != "failed":
                        queued.append((item.id, candidate))
        session.commit()
    for item_id, (policy_id, local_id, reference_id) in set(queued):
        try:
            job_id, _, created = queue_download(item_id, local_id, reference_id=reference_id,
                policy_id=policy_id)
            if created and job_id is not None:
                threading.Thread(target=_run_download, args=(job_id,), daemon=True,
                    name=f"vodloft-live-{job_id}").start()
        except Exception:
            # The normal Download Profile scheduler retries; admission remains
            # persisted so the temporary upstream period is not lost.
            pass


@api_router.get("/stream-profiles/{profile_id}/admissions")
def live_admissions(profile_id: int):
    with get_session() as session:
        if not session.get(CollectionStreamProfile, profile_id):
            raise HTTPException(404, "Stream Profile not found")
        return [{"item_id": admission.item_id, "state": admission.state,
            "source_reference_id": admission.source_reference_id,
            "admitted_at": admission.admitted_at} for admission in session.scalars(
                select(LiveAdmission).where(LiveAdmission.stream_profile_id == profile_id)).all()]


def _subscription_enabled(session, subscription):
    if not subscription:
        return False
    if subscription.integration_target_id is not None:
        target = session.get(MediaServerTarget, subscription.integration_target_id)
        return bool(target and target.enabled)
    return subscription.user_key == "admin" or user_enabled(subscription.user_key)


@public_router.get("/{token}.xml", name="vodloft_feed")
def feed(token: str, request: Request):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(FeedSubscription.token == token))
        if not _subscription_enabled(session, subscription):
            raise HTTPException(404, "Feed not found")
        profile = session.get(CollectionStreamProfile, subscription.stream_profile_id) if subscription.stream_profile_id else None
        if subscription.stream_profile_id:
            if not profile or not profile.enabled:
                raise HTTPException(404, "Feed not found")
        collection = session.get(MediaItem, subscription.collection_id)
        channel = Element("channel")
        SubElement(channel, "title").text = (profile.feed_title if profile else None) or collection.user_title or collection.title
        SubElement(channel, "description").text = collection.description or collection.title
        SubElement(channel, "link").text = str(request.base_url)
        memberships = session.scalars(select(CollectionEntry).where(
            CollectionEntry.collection_id == collection.id).order_by(CollectionEntry.position)).all()
        if profile and profile.max_items:
            memberships.sort(key=lambda entry: (
                session.get(MediaItem, entry.item_id).published_at.timestamp()
                if session.get(MediaItem, entry.item_id).published_at else float('-inf'), -entry.position), reverse=True)
        seen = set()
        published_count = 0
        for membership in memberships:
            if profile and profile.max_items and published_count >= profile.max_items:
                break
            if profile and not matches_membership(membership, profile):
                continue
            if membership.item_id in seen:
                continue
            seen.add(membership.item_id)
            media = session.get(MediaItem, membership.item_id)
            if profile and media.is_live and (not profile.include_live or not session.scalar(
                select(LiveAdmission.id).where(LiveAdmission.stream_profile_id == profile.id,
                    LiveAdmission.item_id == media.id))):
                continue
            if profile and profile.title_contains and profile.title_contains.casefold() not in (
                media.user_title or media.title).casefold():
                continue
            if profile and (profile.published_after or profile.published_before):
                if not media.published_at:
                    continue
                published = media.published_at.date()
                if (profile.published_after and published < profile.published_after or
                    profile.published_before and published > profile.published_before):
                    continue
            entry = _publish(session, subscription, media.id)
            if not entry:
                continue
            published_count += 1
            node = SubElement(channel, "item")
            SubElement(node, "title").text = media.user_title or media.title
            SubElement(node, "guid", isPermaLink="false").text = f"urn:vodloft:feed:{subscription.id}:media:{media.id}"
            SubElement(node, "pubDate").text = format_datetime(entry.created_at)
            SubElement(node, "enclosure", url=str(request.url_for("vodloft_enclosure", token=token,
                entry_id=entry.id, name=Path(entry.path).name)), length=str(entry.size),
                type=mimetypes.guess_type(entry.path)[0] or "application/octet-stream")
        session.commit()
        rss = Element("rss", version="2.0")
        rss.append(channel)
        return Response(content=b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="utf-8"),
                        media_type="application/rss+xml")


@public_router.api_route("/{token}/media/{entry_id}/{name}", methods=["GET", "HEAD"], name="vodloft_enclosure")
def enclosure(token: str, entry_id: int, name: str):
    with get_session() as session:
        entry = session.get(PublishedEntry, entry_id)
        if not entry:
            raise HTTPException(404, "Enclosure not found")
        subscription = session.get(FeedSubscription, entry.subscription_id)
        path = Path(entry.path).resolve()
        if (not _subscription_enabled(session, subscription)
                or not secrets.compare_digest(subscription.token, token)
                or path.name != name or not path.is_relative_to(_feed_root()) or not path.is_file()):
            raise HTTPException(404, "Enclosure not found")
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
