"""Find the Site of the collections and videos added before VODLoft knew Sites.

The database migration placed The Daily Wire's and NPO Start's. Telling the Site of
a yt-dlp link takes yt-dlp's extractors, which only application code loads. That
needs no network request.

A collection whose Site already has the same collection, added through another
Source or under another link, keeps no Site: it is the second copy of that
collection, which VODLoft no longer lets anyone add, and it is left for the user
to remove.

Revision ID: 7ffa406cf785
Revises: 4dac3ac7c70e
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Collection, Video
from backend.services.sites import CollectionAlreadyAddedError, place_collection, place_video


revision = "7ffa406cf785"
down_revision = "4dac3ac7c70e"
title = "Find the Site of collections and videos"

logger = logging.getLogger(__name__)


def _unplaced(model) -> list[int]:
    session = get_session()
    try:
        return list(session.scalars(select(model.id).where(model.site_key.is_(None)).order_by(model.id)))
    finally:
        session.close()


def _place_collection(session, collection_id: int) -> None:
    collection = session.get(Collection, collection_id)
    if collection is None:
        return
    try:
        place_collection(session, collection)
    except CollectionAlreadyAddedError as exc:
        logger.warning("'%s' is the same collection as '%s', so it keeps no Site", collection.title, exc.existing.title)


def _place_video(session, video_id: int) -> None:
    video = session.get(Video, video_id)
    if video is not None:
        place_video(session, video)


async def migrate(context) -> None:
    collections = _unplaced(Collection)
    videos = _unplaced(Video)
    total = len(collections) + len(videos)
    # Each one is saved on its own, so VODLoft is never locked out of the database for the whole run, and a
    # run that stops halfway goes on where it was: only what has no Site yet is looked up again.
    for done, collection_id in enumerate(collections):
        context.update_progress(done, total, "Finding the Site of collections")
        run_write_transaction(lambda session: _place_collection(session, collection_id))
    for done, video_id in enumerate(videos, start=len(collections)):
        context.update_progress(done, total, "Finding the Site of videos")
        run_write_transaction(lambda session: _place_video(session, video_id))
    context.update_progress(total, total, "Finding the Site of collections and videos")
