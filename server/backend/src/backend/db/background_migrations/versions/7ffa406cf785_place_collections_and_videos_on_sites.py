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

from backend.db.core import get_session
from backend.db.models import Collection, Video
from backend.services.sites import CollectionAlreadyAddedError, place_collection, place_video


revision = "7ffa406cf785"
down_revision = "4dac3ac7c70e"
title = "Find the Site of collections and videos"

logger = logging.getLogger(__name__)


async def migrate(context) -> None:
    session = get_session()
    try:
        collections = list(session.scalars(select(Collection).where(Collection.site_key.is_(None)).order_by(Collection.id)))
        videos = list(session.scalars(select(Video).where(Video.site_key.is_(None)).order_by(Video.id)))
        total = len(collections) + len(videos)
        for done, collection in enumerate(collections):
            context.update_progress(done, total, "Finding the Site of collections")
            try:
                place_collection(session, collection)
            except CollectionAlreadyAddedError as exc:
                logger.warning("'%s' is the same collection as '%s', so it keeps no Site", collection.title, exc.existing.title)
            session.flush()
        for done, video in enumerate(videos, start=len(collections)):
            context.update_progress(done, total, "Finding the Site of videos")
            place_video(session, video)
        session.commit()
        context.update_progress(total, total, "Finding the Site of collections and videos")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
