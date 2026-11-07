"""Mark NPO Start programmes that only NPO Plus subscribers can watch.

VODLoft 0.1.0 and 0.2.0 indexed these programmes as if they were free, and
then failed to download them. This asks NPO Start once per season of every
NPO series, and once per single NPO video, which programmes need NPO Plus.
A show or video NPO Start cannot answer for right now is left as it is; its
programmes are still marked when a download finds out.

Revision ID: 5e2b8c71d0a4
Revises: 2965d0593097
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.core import run_write_transaction
from backend.db.models import Episode, Collection, Video
from sources.npo.client import NpoClient, NpoError
from sources.npo.source import NpoSource, needs_subscription, parse_link


revision = "5e2b8c71d0a4"
down_revision = "2965d0593097"
title = "Mark NPO Start programmes that need NPO Plus"

logger = logging.getLogger(__name__)


def _unchecked() -> tuple[list[tuple[int, str]], list[tuple[str, str]]]:
    """The NPO shows with programmes that are not marked yet, and such single videos."""
    session = get_session()
    try:
        collections = session.execute(
            select(Collection.id, Collection.sharing_url)
            .where(Collection.source_key == NpoSource.id)
            .where(Collection.id.in_(select(Episode.collection_id).where(Episode.needs_subscription.is_(False))))
            .order_by(Collection.id)
        ).all()
        videos = session.execute(
            select(Video.slug, Video.sharing_url)
            .where(Video.source_key == NpoSource.id, Video.needs_subscription.is_(False))
            .order_by(Video.id)
        ).all()
        return [(row.id, row.sharing_url) for row in collections], [(row.slug, row.sharing_url) for row in videos]
    finally:
        session.close()


def _premium_in_series(client: NpoClient, url: str) -> set[str]:
    parsed = parse_link(url)
    if parsed is None:
        return set()
    series = client.series_detail(parsed[1])
    premium = set()
    for season in client.series_seasons(series.get("slug") or parsed[1], series.get("type")):
        if not season.get("guid"):
            continue
        for program in client.programs_by_season(season["guid"]):
            if program.get("slug") and needs_subscription(program):
                premium.add(program["slug"])
    return premium


def _premium_video(client: NpoClient, slug: str, url: str) -> bool:
    parsed = parse_link(url)
    return needs_subscription(client.program_detail(parsed[1] if parsed else slug))


def _mark_episodes(collection_id: int, slugs: set[str]) -> None:
    if not slugs:
        return
    def work(session):
        for episode in session.scalars(
            select(Episode).where(Episode.collection_id == collection_id, Episode.source_slug.in_(slugs))
        ):
            episode.needs_subscription = True

    run_write_transaction(work)


def _mark_video(slug: str) -> None:
    def work(session):
        video = session.scalars(
            select(Video).where(Video.source_key == NpoSource.id, Video.slug == slug)
        ).one_or_none()
        if video is not None:
            video.needs_subscription = True

    run_write_transaction(work)


async def migrate(context) -> None:
    collections, videos = _unchecked()
    total = len(collections) + len(videos)
    if total == 0:
        return
    client = NpoClient()
    done = 0
    for collection_id, url in collections:
        context.raise_if_canceled()
        context.update_progress(done, total, "Checking which NPO Start programmes need NPO Plus")
        try:
            premium = await asyncio.to_thread(_premium_in_series, client, url)
        except NpoError as exc:
            logger.warning("Could not check %s for NPO Plus programmes: %s", url, exc)
        else:
            _mark_episodes(collection_id, premium)
        done += 1
    for slug, url in videos:
        context.raise_if_canceled()
        context.update_progress(done, total, "Checking which NPO Start videos need NPO Plus")
        try:
            premium = await asyncio.to_thread(_premium_video, client, slug, url)
        except NpoError as exc:
            logger.warning("Could not check %s for NPO Plus: %s", url, exc)
        else:
            if premium:
                _mark_video(slug)
        done += 1
    context.update_progress(total, total, "Marked the NPO Start programmes that need NPO Plus")
