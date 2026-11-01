"""Populate show square thumbnails from The Daily Wire Watch page.

Revision ID: 3c8f6a1d2b47
Revises: f6a1c3d8b427
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from backend.db.core import get_session
from backend.db.models import Collection
from sources.dailywire.api.dw_api.client import MiddlewareClient
from sources.dailywire.auth import DeviceAuthClient


revision = "3c8f6a1d2b47"
down_revision = "f6a1c3d8b427"
title = "Populate show square thumbnails from The Daily Wire"


def _collection_count() -> int:
    session = get_session()
    try:
        return int(session.scalar(select(func.count(Collection.id))) or 0)
    finally:
        session.close()


def _apply_square_thumbnails(thumbnails: dict[str, str]) -> int:
    """Apply only artwork present in the carousel; absent shows are expected."""
    session = get_session()
    updated = 0
    try:
        for collection in session.scalars(select(Collection).order_by(Collection.id)):
            if collection.thumbnail_square_path is not None:
                continue

            square_path = thumbnails.get(collection.slug)
            if square_path is None:
                continue

            collection.thumbnail_square_path = square_path
            updated += 1
        session.commit()
        return updated
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def migrate(context) -> None:
    collection_count = _collection_count()
    if collection_count == 0:
        return

    context.raise_if_cancelled()
    context.update_progress(
        0,
        collection_count,
        "Fetching square show thumbnails from The Daily Wire",
    )

    tokens = await asyncio.to_thread(DeviceAuthClient().get_token)
    client = MiddlewareClient(
        access_token=tokens.access_token if tokens else None,
    )
    thumbnails = await asyncio.to_thread(client.get_square_show_thumbnails)

    context.raise_if_cancelled()
    _apply_square_thumbnails(thumbnails)

    context.update_progress(
        collection_count,
        collection_count,
        "Updated square show thumbnails",
    )
