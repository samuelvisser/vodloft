"""Count the downloads of each collection that wait to be moved.

Collections now store that count, which Home and the Library read; this counts it once for the collections that were
there before. From then on every placement of a collection's videos keeps it up to date, and a nightly check finds
what drifted.

Revision ID: 8f1a7033bae0
Revises: 9c25f5b4d4d1
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection
from backend.services.reconcile import check_moves_waiting

revision = "8f1a7033bae0"
down_revision = "9c25f5b4d4d1"
title = "Count the downloads of each collection that wait to be moved"

_TITLE = "Counting the downloads that wait to be moved"


def _collection_ids() -> list[int]:
    session = get_session()
    try:
        return list(session.scalars(select(Collection.id).order_by(Collection.id)))
    finally:
        session.rollback()
        session.close()


async def migrate(context) -> None:
    ids = _collection_ids()
    if not ids:
        return
    total = len(ids)
    context.update_progress(0, total, _TITLE)
    for done, collection_id in enumerate(ids, start=1):
        context.raise_if_canceled()
        await asyncio.to_thread(check_moves_waiting, collection_id)
        context.update_progress(done, total, _TITLE)
