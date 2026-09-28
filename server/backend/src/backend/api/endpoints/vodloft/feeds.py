"""Revocable collection feeds with immutable enclosure copies."""

import mimetypes
import os
import secrets
import shutil
import tempfile
from datetime import date
from email.utils import format_datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.vodloft import Artifact, CollectionEntry, CollectionStreamProfile, FeedSubscription, MediaItem, PublishedEntry
from config import get_settings

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
    local_only: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def validate_dates(self):
        if self.published_after and self.published_before and self.published_after > self.published_before:
            raise ValueError("The publication start must be on or before the end")
        return self


def _stream_profile(profile: CollectionStreamProfile) -> dict:
    return {"id": profile.id, "collection_id": profile.collection_id,
            "name": profile.name, "format": profile.format,
            "published_after": profile.published_after,
            "published_before": profile.published_before,
            "title_contains": profile.title_contains,
            "local_only": profile.local_only, "enabled": profile.enabled}


@api_router.get("/library/{collection_id}/stream-profiles")
def stream_profiles(collection_id: int):
    with get_session() as session:
        if not (item := session.get(MediaItem, collection_id)) or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        return [_stream_profile(p) for p in session.scalars(select(CollectionStreamProfile).where(
            CollectionStreamProfile.collection_id == collection_id)).all()]


@api_router.post("/library/{collection_id}/stream-profiles", status_code=201)
def create_stream_profile(collection_id: int, data: StreamProfileInput):
    if not data.local_only:
        raise HTTPException(422, "Upstream feed delivery requires a prepared local rendition")
    with get_session() as session:
        if not (item := session.get(MediaItem, collection_id)) or item.kind != "collection":
            raise HTTPException(404, "Collection not found")
        profile = CollectionStreamProfile(collection_id=collection_id, **data.model_dump())
        session.add(profile)
        session.commit()
        return _stream_profile(profile)


@api_router.put("/stream-profiles/{profile_id}")
def update_stream_profile(profile_id: int, data: StreamProfileInput):
    if not data.local_only:
        raise HTTPException(422, "Upstream feed delivery requires a prepared local rendition")
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
        for key, value in data.model_dump().items():
            setattr(profile, key, value)
        session.commit()
        return _stream_profile(profile)


@api_router.delete("/stream-profiles/{profile_id}", status_code=204)
def delete_stream_profile(profile_id: int):
    with get_session() as session:
        profile = session.get(CollectionStreamProfile, profile_id)
        if not profile:
            raise HTTPException(404, "Stream Profile not found")
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile_id))
        subscription_id = subscription.id if subscription else None
        if subscription:
            session.delete(subscription)
            session.flush()
        session.delete(profile)
        session.commit()
    if subscription_id:
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
            FeedSubscription.collection_id == collection_id, FeedSubscription.stream_profile_id.is_(None)))
        if not subscription:
            subscription = FeedSubscription(collection_id=collection_id, token=secrets.token_urlsafe(32))
            session.add(subscription)
            session.commit()
        return {"url": str(request.url_for("vodloft_feed", token=subscription.token))}


@api_router.delete("/library/{collection_id}/feed")
def revoke(collection_id: int):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.collection_id == collection_id, FeedSubscription.stream_profile_id.is_(None)))
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
            FeedSubscription.stream_profile_id == profile_id))
        if not subscription:
            subscription = FeedSubscription(collection_id=profile.collection_id,
                stream_profile_id=profile_id, token=secrets.token_urlsafe(32))
            session.add(subscription)
            session.commit()
        return {"url": str(request.url_for("vodloft_feed", token=subscription.token))}


@api_router.delete("/stream-profiles/{profile_id}/feed")
def revoke_profile(profile_id: int):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile_id))
        if not subscription:
            raise HTTPException(404, "Stream Profile feed not found")
        subscription_id = subscription.id
        session.delete(subscription)
        session.commit()
    _remove_published(subscription_id)
    return {"revoked": True}


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


@public_router.get("/{token}.xml", name="vodloft_feed")
def feed(token: str, request: Request):
    with get_session() as session:
        subscription = session.scalar(select(FeedSubscription).where(FeedSubscription.token == token))
        if not subscription:
            raise HTTPException(404, "Feed not found")
        profile = session.get(CollectionStreamProfile, subscription.stream_profile_id) if subscription.stream_profile_id else None
        if subscription.stream_profile_id:
            if not profile or not profile.enabled:
                raise HTTPException(404, "Feed not found")
        collection = session.get(MediaItem, subscription.collection_id)
        channel = Element("channel")
        SubElement(channel, "title").text = collection.user_title or collection.title
        SubElement(channel, "description").text = collection.description or collection.title
        SubElement(channel, "link").text = str(request.base_url)
        memberships = session.scalars(select(CollectionEntry).where(
            CollectionEntry.collection_id == collection.id).order_by(CollectionEntry.position)).all()
        for membership in memberships:
            media = session.get(MediaItem, membership.item_id)
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


@public_router.get("/{token}/media/{entry_id}/{name}", name="vodloft_enclosure")
def enclosure(token: str, entry_id: int, name: str):
    with get_session() as session:
        entry = session.get(PublishedEntry, entry_id)
        if not entry:
            raise HTTPException(404, "Enclosure not found")
        subscription = session.get(FeedSubscription, entry.subscription_id)
        path = Path(entry.path).resolve()
        if (not subscription or not secrets.compare_digest(subscription.token, token)
                or path.name != name or not path.is_relative_to(_feed_root()) or not path.is_file()):
            raise HTTPException(404, "Enclosure not found")
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
