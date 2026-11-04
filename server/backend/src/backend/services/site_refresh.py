"""The metadata refresh setting of each Site, as the Automation settings show and change it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, Site, Video
from backend.services.episode_metadata_refresh import refreshes_episode_metadata
from backend.services.metadata_refresh import sweeps_metadata
from backend.types.site_types import SiteRefreshMode
from sources import Feature, UnknownSourceError, get_source


class UnknownSiteError(LookupError):
    pass


@dataclass(frozen=True)
class SiteRefresh:
    site: Site
    refreshes: bool
    checks_pending: bool
    """Whether a Source the Site's collections come through follows upcoming and live videos."""


def _checks_pending(source_key: str) -> bool:
    try:
        return get_source(source_key).has(Feature.PENDING_CHECKS)
    except UnknownSourceError:
        return False


def _site_refreshes(s: Session) -> dict[str, tuple[bool, bool]]:
    """Every Site with collections or videos, and whether a Source looks its items up again and follows its
    upcoming videos."""
    rows = s.execute(union(
        select(Collection.site_key, Collection.source_key).where(Collection.site_key.is_not(None)),
        select(Video.site_key, Video.source_key).where(Video.site_key.is_not(None)),
    )).all()
    found: dict[str, tuple[bool, bool]] = {}
    for site_key, source_key in rows:
        refreshes, checks_pending = found.get(site_key, (False, False))
        found[site_key] = (
            refreshes or sweeps_metadata(source_key) or refreshes_episode_metadata(source_key),
            checks_pending or _checks_pending(source_key),
        )
    return found


def _site_refresh(site: Site, found: dict[str, tuple[bool, bool]]) -> SiteRefresh:
    # A Site without collections or videos yet shows every setting.
    refreshes, checks_pending = found.get(site.key, (True, True))
    return SiteRefresh(site, refreshes, checks_pending)


def list_site_refresh(s: Session) -> list[SiteRefresh]:
    found = _site_refreshes(s)
    sites = s.scalars(select(Site).order_by(Site.name)).all()
    return [_site_refresh(site, found) for site in sites]


def set_site_refresh(
    s: Session, key: str, mode: SiteRefreshMode, intervals: Optional[str], pending_checks: Optional[bool] = None,
) -> SiteRefresh:
    site = s.get(Site, key)
    if site is None:
        raise UnknownSiteError(f"VODLoft has no Site '{key}'")
    site.refresh_mode = SiteRefreshMode(mode).value
    if intervals is not None:
        site.refresh_intervals = intervals
    if pending_checks is not None:
        site.pending_checks = pending_checks
    s.flush()
    return _site_refresh(site, _site_refreshes(s))
