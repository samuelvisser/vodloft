"""Give Daily Wire episodes added before VODLoft kept their membership levels the level they need.

Episodes added since then show a badge such as Insider when only members may
watch them. Older ones never got it, because the scans only list new episodes
and the metadata refresh is done with them. Each show's seasons are listed
once, 50 episodes a request, and every episode they list gets its level.

Revision ID: 536d9eeb6f76
Revises: 305a9510537f
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Collection, Episode
from backend.services.media_access import apply_source_access
from backend.types.dailywire_user_info import DwMembershipLevel
from sources.dailywire.api.dw_api.client import ByNextPage, ByShowSeason, MiddlewareAPIError, MiddlewareClient
from sources.dailywire.auth import DeviceAuthClient
from sources.dailywire.source import episode_access

revision = "536d9eeb6f76"
down_revision = "305a9510537f"
title = "Give older Daily Wire episodes their membership level"

logger = logging.getLogger(__name__)


def _shows() -> list[tuple[int, str, str]]:
    """Each Daily Wire show: its id, slug and the membership plan it is listed with."""
    session = get_session()
    try:
        return [
            (collection.id, collection.slug, collection.membership_level)
            for collection in session.scalars(
                select(Collection).where(Collection.source_key == "dailywire").order_by(Collection.id)
            )
        ]
    finally:
        session.rollback()
        session.close()


def _levels(client: MiddlewareClient, slug: str, plan: str | None) -> dict[str, list]:
    """The membership levels of every episode the show's seasons list, by episode slug."""
    levels: dict[str, list] = {}
    for season in client.get_show_page(slug, membership_plan=plan).seasons:
        page = client.get_episodes_paginated(
            slug, ByShowSeason(season_dw_id=season.dw_id, membership_plan=plan, page_size=50, order_by="CreatedAt_ASC"),
        )
        while True:
            for record in page.items:
                # A record without levels says nothing about them.
                if record.available_for:
                    levels[record.slug] = list(record.available_for)
            if not (page.has_next and page.next_page_url):
                break
            page = client.get_episodes_paginated(slug, ByNextPage(next_page_url=page.next_page_url))
    return levels


def _apply(collection_id: int, levels: dict[str, list]) -> None:
    def work(session) -> None:
        for episode in session.scalars(select(Episode).where(Episode.collection_id == collection_id)):
            if (available_for := levels.get(episode.slug)) is not None:
                apply_source_access(episode, episode_access(available_for))

    run_write_transaction(work)


async def migrate(context) -> None:
    shows = _shows()
    if not shows:
        return
    tokens = await asyncio.to_thread(DeviceAuthClient().get_token)
    client = MiddlewareClient(access_token=tokens.access_token if tokens else None)
    for done, (collection_id, slug, plan) in enumerate(shows):
        context.raise_if_canceled()
        context.update_progress(done, len(shows), f"Reading the membership levels of {slug}'s episodes")
        # The scans list a show set to what the membership allows with the free plan, too.
        if plan == DwMembershipLevel.HIGHEST_ALLOWED.value:
            plan = DwMembershipLevel.FREE.value
        try:
            levels = await asyncio.to_thread(_levels, client, slug, plan)
        except MiddlewareAPIError as exc:
            # Its episodes keep no level; a metadata refresh of the show gives them one.
            logger.warning("Could not read the membership levels of %s: %s", slug, exc)
            continue
        _apply(collection_id, levels)
    context.update_progress(len(shows), len(shows), "Gave older Daily Wire episodes their membership level")
