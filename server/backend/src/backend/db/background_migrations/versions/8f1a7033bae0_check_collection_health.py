"""Check the health of each collection.

Collections now store their health, which Home and the Library read; this runs the collection health check once on
each collection that was there before, such as to count the downloads that wait to be moved. From then on VODLoft keeps
it up to date as it works on a collection, and the nightly health check finds what drifted.

Revision ID: 8f1a7033bae0
Revises: 9c25f5b4d4d1
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection
from backend.services.collection_health import check_collection_health

revision = "8f1a7033bae0"
down_revision = "9c25f5b4d4d1"
title = "Check the health of each collection"

_TITLE = "Checking the health of each collection"


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
        await asyncio.to_thread(check_collection_health, collection_id)
        context.update_progress(done, total, _TITLE)
