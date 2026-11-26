"""The paid tiers creators set up themselves on a Site, such as Patreon's.

VODLoft keeps each tier with an id of its own, beside the Site's id of it. Media that needs a tier points to it, so it
stays with the tier when the creator renames it or changes what it costs. VODLoft learns a creator's tiers when it
indexes or refreshes a collection of theirs, and when it looks up one of their videos.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sources import CreatorTier as SiteTier
from sources import Site, Source, site_for
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import CreatorTier

logger = logging.getLogger(__name__)


def tiers_at_source(source: Source, site: Site, url: str | None) -> tuple[SiteTier, ...] | None:
    """The tiers of the creator a link is of, as the Source tells them; None on a Site without creators' tiers, or when
    the Source could not tell. Asked before a write transaction, as it asks the Site."""
    if site.creator_tiers is None or not url:
        return None
    try:
        return source.creator_tiers(url)
    except Exception as exc:  # noqa: BLE001 - the tiers only name what media needs; indexing goes on without them
        logger.info("Could not learn the creator's tiers of %s: %s", url, exc)
        return None


def keep_tiers(s: Session, site_key: str, tiers: Iterable[SiteTier] | None) -> None:
    """Store what the creator now calls their tiers and what they cost."""
    for tier in tiers or ():
        row = tier_row(s, site_key, tier.site_id)
        row.name, row.amount, row.rank = tier.name, tier.amount, tier.rank


def tier_row(s: Session, site_key: str, site_tier_id: str) -> CreatorTier:
    """The tier VODLoft keeps for a tier on a Site, made when it is new; its name follows when VODLoft learns it."""
    row = next((
        pending for pending in s.new
        if isinstance(pending, CreatorTier) and (pending.site_key, pending.site_tier_id) == (site_key, site_tier_id)
    ), None) or s.scalar(select(CreatorTier).where(CreatorTier.site_key == site_key, CreatorTier.site_tier_id == site_tier_id))
    if row is None:
        row = CreatorTier(site_key=site_key, site_tier_id=site_tier_id)
        s.add(row)
    return row


def site_tier(row: CreatorTier | None) -> SiteTier | None:
    """A kept tier as its Site names it; None for a tier VODLoft does not know the name of yet."""
    if row is None or not row.name:
        return None
    return SiteTier(site_id=row.site_tier_id, name=row.name, amount=row.amount, rank=row.rank)


def unnamed_tiers(s: Session, source: Source, links: Iterable[tuple[str, str | None]]) -> list[tuple[str, tuple[SiteTier, ...]]]:
    """The tiers of the creators of links whose access, as the Source told it, is a tier VODLoft does not know the name
    of yet, by the key of their Site: one lookup per creator. Asked before a write transaction, as it asks the Site."""
    found: list[tuple[str, tuple[SiteTier, ...]]] = []
    known: set[tuple[str, str]] = set()
    for url, key in links:
        site = site_for(url, source.id) if url else None
        tier_access = site.creator_tiers if site is not None else None
        site_tier_id = tier_access.tier_id(key) if tier_access is not None else None
        if site_tier_id is None or (site.key, site_tier_id) in known:
            continue
        known.add((site.key, site_tier_id))
        if s.scalar(select(CreatorTier.name).where(CreatorTier.site_key == site.key, CreatorTier.site_tier_id == site_tier_id)):
            continue
        if tiers := tiers_at_source(source, site, url):
            found.append((site.key, tiers))
            known |= {(site.key, tier.site_id) for tier in tiers}
    s.rollback()
    return found
