"""The metadata refresh setting of each Site, as the Automation settings show and change it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, Site, Video
from backend.services.episode_metadata_refresh import refreshes_episode_metadata
from backend.services.metadata_refresh import sweeps_metadata
from backend.services.pending_episodes import checks_pending, follows_pending
from backend.types.site_types import SiteRefreshMode
from sources import UnknownSourceError, get_source


class UnknownSiteError(LookupError):
    pass


@dataclass(frozen=True)
class SiteRefresh:
    site: Site
    refreshes: bool
    checks_pending: bool
    """Whether a Source the Site's collections come through can add upcoming and live videos."""
    follows_pending: bool
    """Whether a Source the Site's collections come through follows upcoming and live episodes."""


@dataclass(frozen=True)
class PendingMinutes:
    """How often a Site's upcoming and live episodes are looked up."""

    upcoming: int
    starting: int
    live: int


def _checks_pending(source_key: str) -> bool:
    try:
        return checks_pending(get_source(source_key))
    except UnknownSourceError:
        return False


def _site_refreshes(s: Session) -> dict[str, tuple[bool, bool, bool]]:
    """Every Site with collections or videos, and whether a Source looks its items up again, can add its
    upcoming videos and follows its upcoming episodes."""
    rows = s.execute(union(
        select(Collection.site_key, Collection.source_key).where(Collection.site_key.is_not(None)),
        select(Video.site_key, Video.source_key).where(Video.site_key.is_not(None)),
    )).all()
    found: dict[str, tuple[bool, bool, bool]] = {}
    for site_key, source_key in rows:
        refreshes, checks, follows = found.get(site_key, (False, False, False))
        found[site_key] = (
            refreshes or sweeps_metadata(source_key) or refreshes_episode_metadata(source_key),
            checks or _checks_pending(source_key),
            follows or follows_pending(source_key),
        )
    return found


def _site_refresh(site: Site, found: dict[str, tuple[bool, bool, bool]]) -> SiteRefresh:
    # A Site without collections or videos yet shows every setting.
    return SiteRefresh(site, *found.get(site.key, (True, True, True)))


def list_site_refresh(s: Session) -> list[SiteRefresh]:
    found = _site_refreshes(s)
    sites = s.scalars(select(Site).order_by(Site.name)).all()
    return [_site_refresh(site, found) for site in sites]


def set_site_refresh(
    s: Session,
    key: str,
    mode: SiteRefreshMode,
    intervals: Optional[str],
    pending_checks: Optional[bool] = None,
    pending_minutes: Optional[PendingMinutes] = None,
) -> SiteRefresh:
    site = s.get(Site, key)
    if site is None:
        raise UnknownSiteError(f"VODLoft has no Site '{key}'")
    site.refresh_mode = SiteRefreshMode(mode).value
    if intervals is not None:
        site.refresh_intervals = intervals
    if pending_checks is not None:
        site.pending_checks = pending_checks
    if pending_minutes is not None:
        site.pending_upcoming_minutes = pending_minutes.upcoming
        site.pending_starting_minutes = pending_minutes.starting
        site.pending_live_minutes = pending_minutes.live
    s.flush()
    return _site_refresh(site, _site_refreshes(s))
