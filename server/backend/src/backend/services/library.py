from __future__ import annotations

from datetime import datetime, timezone

from media_profiles import CollectionKind
from sqlalchemy import select
from sqlalchemy.orm import Session
from ytdlp_client import ExtractedCollection, ExtractedVideo, YtDlpClient

from backend.db.models import Collection, Video


def detect_collection_kind(url: str, data: ExtractedCollection) -> CollectionKind:
    lowered = url.lower()
    if "list=" in lowered or "/playlist" in lowered:
        return CollectionKind.PLAYLIST
    if any(part in lowered for part in ("/@", "/channel/", "/user/", "/c/")):
        return CollectionKind.CHANNEL
    if data.channel_id and data.playlist_id == data.extractor_id:
        return CollectionKind.CHANNEL
    return CollectionKind.PLAYLIST


def upsert_video(session: Session, data: ExtractedVideo) -> Video:
    video = session.scalar(
        select(Video).where(
            Video.extractor == data.extractor,
            Video.extractor_id == data.extractor_id,
        )
    )
    if video is None:
        video = Video(
            extractor=data.extractor,
            extractor_id=data.extractor_id,
            source_url=data.webpage_url,
            title=data.title,
        )
        session.add(video)
    video.source_url = data.webpage_url
    video.title = data.title
    video.description = data.description
    video.uploader = data.uploader
    video.uploader_id = data.uploader_id
    video.channel = data.channel
    video.channel_id = data.channel_id
    video.duration = data.duration
    video.upload_date = data.upload_date
    video.thumbnail_url = data.thumbnail_url
    return video


def add_video(session: Session, client: YtDlpClient, url: str) -> Video:
    video = upsert_video(session, client.extract_video(url))
    session.commit()
    session.refresh(video)
    return video


def add_collection(
    session: Session,
    client: YtDlpClient,
    url: str,
    requested_kind: CollectionKind | None = None,
) -> Collection:
    data = client.extract_collection(url, flat=True)
    kind = requested_kind or detect_collection_kind(url, data)
    existing = session.scalar(
        select(Collection).where(
            Collection.extractor == data.extractor,
            Collection.extractor_id == data.extractor_id,
        )
    )
    if existing is not None:
        raise ValueError("Collection is already in the library")

    collection = Collection(
        kind=kind.value,
        source_url=url,
        extractor=data.extractor,
        extractor_id=data.extractor_id,
        title=data.title,
        description=data.description,
        uploader=data.uploader,
        uploader_id=data.uploader_id,
        channel=data.channel,
        channel_id=data.channel_id,
        thumbnail_url=data.thumbnail_url,
    )
    session.add(collection)
    session.flush()
    _apply_collection_sync(session, collection, data)
    session.commit()
    session.refresh(collection)
    return collection


def _apply_collection_sync(session: Session, collection: Collection, data: ExtractedCollection) -> None:
    collection.title = data.title
    collection.description = data.description
    collection.uploader = data.uploader
    collection.uploader_id = data.uploader_id
    collection.channel = data.channel
    collection.channel_id = data.channel_id
    collection.thumbnail_url = data.thumbnail_url

    existing_ids = {video.id for video in collection.videos}
    for item in data.entries:
        video = upsert_video(session, item)
        session.flush()
        if video.id not in existing_ids:
            collection.videos.append(video)
            existing_ids.add(video.id)
    collection.last_synced_at = datetime.now(timezone.utc)


def sync_collection(session: Session, client: YtDlpClient, collection_id: int) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise LookupError("Collection not found")
    data = client.extract_collection(collection.source_url, flat=True)
    _apply_collection_sync(session, collection, data)
    session.commit()
    session.refresh(collection)
    return collection
