"""The Sites VODLoft knows, and which Site a collection or video is on.

A Site is a website as the user knows it, such as YouTube, whichever Source
fetches it. VODLoft keeps a row per Site it has seen, with the domains it saw and
the Source to ask first for the Site's links. A collection is added once per Site:
the Site's own id for it is unique per Site.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection, Site, Video
from backend.types.site_types import SiteRefreshMode
from sources import Site as SourceSite, collection_on_site, site_for


class CollectionAlreadyAddedError(ValueError):
    """The collection is already in VODLoft, possibly through another Source."""

    def __init__(self, existing: Collection, site: Site):
        super().__init__(f"{existing.title} is already in VODLoft, as a collection on {site.name}")
        self.existing = existing


def site_record(s: Session, site: SourceSite) -> Site:
    """The row of a Site, made when VODLoft sees the Site for the first time, with the domain seen added."""
    record = s.get(Site, site.key)
    if record is None:
        record = Site(
            key=site.key, name=site.name, domains=list(site.domains),
            # A Site the sources package knows a schedule for starts on it; any other follows the system schedule.
            refresh_mode=(SiteRefreshMode.OWN if site.refresh_intervals else SiteRefreshMode.SYSTEM).value,
            refresh_intervals=site.refresh_intervals,
        )
        s.add(record)
        s.flush()
    elif any(domain not in record.domains for domain in site.domains):
        record.domains = [*record.domains, *(domain for domain in site.domains if domain not in record.domains)]
    return record


def collection_on_site_taken(s: Session, site_key: str, site_ref: str, *, other_than: Optional[int] = None) -> Optional[Collection]:
    query = select(Collection).where(Collection.site_key == site_key, Collection.site_ref == site_ref)
    if other_than is not None:
        query = query.where(Collection.id != other_than)
    return s.scalars(query.limit(1)).first()


def place_collection(s: Session, collection: Collection) -> None:
    """Give a new collection its Site and the Site's id for it.

    Raises CollectionAlreadyAddedError when the Site's collection is already in VODLoft,
    whichever Source it came through. The database refuses it too.
    """
    site, ref = collection_on_site(collection.sharing_url, collection.source_key, collection.slug)
    record = site_record(s, site)
    existing = collection_on_site_taken(s, record.key, ref, other_than=collection.id)
    if existing is not None:
        raise CollectionAlreadyAddedError(existing, record)
    collection.site_key, collection.site_ref = record.key, ref


def collection_site(collection: Collection) -> SourceSite:
    """The Site a collection is on, as the sources package tells it, with what VODLoft may do there."""
    return _site_of(collection.sharing_url, collection.source_key)


@lru_cache(maxsize=1024)
def _site_of(url: str, source_key: str) -> SourceSite:
    # Telling a yt-dlp link's Site tries every extractor, and a feed asks once per episode.
    return site_for(url, source_key)


def place_video(s: Session, video: Video) -> None:
    """Give a video the Site its link is on."""
    video.site_key = site_record(s, site_for(video.sharing_url, video.source_key)).key


def preferred_sources(s: Session) -> dict[str, str]:
    """The Source the user asks first, per Site key."""
    return dict(s.execute(select(Site.key, Site.preferred_source_key).where(Site.preferred_source_key.is_not(None))).all())
