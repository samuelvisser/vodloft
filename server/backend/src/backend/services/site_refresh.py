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


class UnknownSiteError(LookupError):
    pass


@dataclass(frozen=True)
class SiteRefresh:
    site: Site
    refreshes: bool


def _refreshing_site_keys(s: Session) -> tuple[set[str], set[str]]:
    """Every Site with collections or videos, and those of them whose items a Source looks up again."""
    rows = s.execute(union(
        select(Collection.site_key, Collection.source_key).where(Collection.site_key.is_not(None)),
        select(Video.site_key, Video.source_key).where(Video.site_key.is_not(None)),
    )).all()
    used = {site_key for site_key, _source_key in rows}
    refreshing = {
        site_key for site_key, source_key in rows
        if sweeps_metadata(source_key) or refreshes_episode_metadata(source_key)
    }
    return used, refreshing


def list_site_refresh(s: Session) -> list[SiteRefresh]:
    used, refreshing = _refreshing_site_keys(s)
    sites = s.scalars(select(Site).order_by(Site.name)).all()
    return [SiteRefresh(site, site.key in refreshing or site.key not in used) for site in sites]


def set_site_refresh(s: Session, key: str, mode: SiteRefreshMode, intervals: Optional[str]) -> SiteRefresh:
    site = s.get(Site, key)
    if site is None:
        raise UnknownSiteError(f"VODLoft has no Site '{key}'")
    site.refresh_mode = SiteRefreshMode(mode).value
    if intervals is not None:
        site.refresh_intervals = intervals
    s.flush()
    used, refreshing = _refreshing_site_keys(s)
    return SiteRefresh(site, key in refreshing or key not in used)
