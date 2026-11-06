"""The metadata refresh setting of each Site, as the Automation settings show and change it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, Site, Video
from backend.services.metadata_refresh import refreshes_metadata
from backend.services.pending_episodes import PendingMinutes, follows_pending
from backend.types.site_types import SiteRefreshMode


class UnknownSiteError(LookupError):
    pass


@dataclass(frozen=True)
class SiteRefresh:
    site: Site
    refreshes: bool
    follows_pending: bool
    """Whether a Source the Site's collections come through follows upcoming and live episodes, which
    the Site's ``pending_checks`` turns on and off."""


def _site_refreshes(s: Session) -> dict[str, tuple[bool, bool]]:
    """Every Site with collections or videos, and whether a Source looks its items up again and
    follows its upcoming and live episodes."""
    rows = s.execute(union(
        select(Collection.site_key, Collection.source_key).where(Collection.site_key.is_not(None)),
        select(Video.site_key, Video.source_key).where(Video.site_key.is_not(None)),
    )).all()
    found: dict[str, tuple[bool, bool]] = {}
    for site_key, source_key in rows:
        refreshes, follows = found.get(site_key, (False, False))
        found[site_key] = (refreshes or refreshes_metadata(source_key), follows or follows_pending(source_key))
    return found


def _site_refresh(site: Site, found: dict[str, tuple[bool, bool]]) -> SiteRefresh:
    # A Site without collections or videos yet shows every setting.
    return SiteRefresh(site, *found.get(site.key, (True, True)))


def list_site_refresh(s: Session) -> list[SiteRefresh]:
    found = _site_refreshes(s)
    sites = s.scalars(select(Site).order_by(Site.name)).all()
    return [_site_refresh(site, found) for site in sites]


def set_site_refresh(
    s: Session,
    key: str,
    mode: SiteRefreshMode,
    intervals: Optional[str],
    pending_checks: Optional[bool],
    pending_minutes: Optional[PendingMinutes],
) -> SiteRefresh:
    """Change a Site's settings. ``pending_checks`` and ``pending_minutes`` None follow the system setting."""
    site = s.get(Site, key)
    if site is None:
        raise UnknownSiteError(f"VODLoft has no Site '{key}'")
    site.refresh_mode = SiteRefreshMode(mode).value
    if intervals is not None:
        site.refresh_intervals = intervals
    site.pending_checks = pending_checks
    site.pending_upcoming_minutes = pending_minutes.upcoming if pending_minutes else None
    site.pending_starting_minutes = pending_minutes.starting if pending_minutes else None
    site.pending_live_minutes = pending_minutes.live if pending_minutes else None
    s.flush()
    return _site_refresh(site, _site_refreshes(s))
