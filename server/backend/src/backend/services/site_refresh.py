"""Each Site VODLoft knows, as the Automation settings list it to schedule it.

What a Site's own scheduling is lives in config.yml, under ``siteSchedules``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, Site, Video
from backend.services.pending_episodes import follows_pending
from backend.services.metadata_refresh import refreshes_metadata
from sources import site_refresh_intervals


@dataclass(frozen=True)
class SiteRefresh:
    site: Site
    refreshes: bool
    follows_pending: bool
    """Whether a Source the Site's collections come through follows upcoming and live episodes."""
    default_refresh_intervals: Optional[str]
    """The schedule the sources package knows for the Site, which it follows unless config.yml sets one."""


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


def list_site_refresh(s: Session) -> list[SiteRefresh]:
    found = _site_refreshes(s)
    sites = s.scalars(select(Site).order_by(Site.name)).all()
    # A Site without collections or videos yet shows every setting.
    return [SiteRefresh(site, *found.get(site.key, (True, True)), site_refresh_intervals(site.key)) for site in sites]

