"""Make thumbnails from the first frame of videos that have none.

New episodes and videos get a frame of their video when their Source has no
picture for them. This gives the episodes and videos VODLoft already has the
same, for example the YouTube videos that show YouTube's grey placeholder.

Revision ID: 4e8a2c7f1d95
Revises: 9b3e5d7a1c62
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Episode, Video
from backend.services.thumbnails import take_first_frames


revision = "4e8a2c7f1d95"
down_revision = "9b3e5d7a1c62"
title = "Make thumbnails from the first frame of videos without one"

_BATCH = 25
_MESSAGE = "Looking for videos without a thumbnail"


def _item_ids() -> list[int]:
    session = get_session()
    try:
        ids = [*session.scalars(select(Episode.id)), *session.scalars(select(Video.id))]
        return sorted(ids)
    finally:
        session.close()


def _take(item_ids: list[int]) -> None:
    session = get_session()
    try:
        take_first_frames(session, item_ids)
    finally:
        session.close()


async def migrate(context) -> None:
    item_ids = _item_ids()
    total = len(item_ids)
    if total == 0:
        return
    for start in range(0, total, _BATCH):
        context.raise_if_canceled()
        context.update_progress(start, total, _MESSAGE)
        await asyncio.to_thread(_take, item_ids[start:start + _BATCH])
    context.update_progress(total, total, _MESSAGE)
