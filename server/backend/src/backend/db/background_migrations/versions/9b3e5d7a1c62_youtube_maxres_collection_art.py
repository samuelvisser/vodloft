"""Use YouTube's 16:9 maxresdefault still for existing yt-dlp Collections.

New yt-dlp Collections already store the maxresdefault still when YouTube has
one. Collections added before that keep the 4:3 hqdefault or sddefault still,
which has black bars around a 16:9 picture, because a metadata refresh only
updates episode artwork. Only the stored URL changes; no image is downloaded.

Revision ID: 9b3e5d7a1c62
Revises: c0f6328c88f7
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection
from sources.ytdlp.thumbnails import widest_still


revision = "9b3e5d7a1c62"
down_revision = "c0f6328c88f7"
title = "Use YouTube's 16:9 still for yt-dlp Collection artwork"

_SOURCE_KEY = "ytdlp"
_FIELDS = ("thumbnail_landscape_path", "background_image_path")


def _collection_artwork() -> list[tuple[int, dict[str, str | None]]]:
    session = get_session()
    try:
        return [
            (collection.id, {field: getattr(collection, field) for field in _FIELDS})
            for collection in session.scalars(
                select(Collection).where(Collection.source_key == _SOURCE_KEY).order_by(Collection.id)
            )
        ]
    finally:
        session.close()


def _apply(collection_id: int, changes: dict[str, str]) -> None:
    session = get_session()
    try:
        collection = session.get(Collection, collection_id)
        if collection is not None:
            for field, value in changes.items():
                setattr(collection, field, value)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def migrate(context) -> None:
    collections = _collection_artwork()
    if not collections:
        return
    total = len(collections)
    context.update_progress(0, total, "Looking up YouTube's 16:9 Collection artwork")
    for done, (collection_id, artwork) in enumerate(collections, start=1):
        context.raise_if_cancelled()
        changes: dict[str, str] = {}
        upgraded: dict[str, str | None] = {}
        for field, url in artwork.items():
            if url not in upgraded:
                upgraded[url] = await asyncio.to_thread(widest_still, url)
            if upgraded[url] and upgraded[url] != url:
                changes[field] = upgraded[url]
        if changes:
            _apply(collection_id, changes)
        context.update_progress(done, total, "Looking up YouTube's 16:9 Collection artwork")
