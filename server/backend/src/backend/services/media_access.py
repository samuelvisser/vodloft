"""Media that VODLoft cannot download for lack of an access the Source wants, such as NPO Plus,
a Daily Wire membership level or a YouTube channel membership.

Such media is locked: it is not an error and its download is not retried. VODLoft checks
whether refused media opened up for everyone after a day, three days and a week, then weekly
for a few weeks, and checks right away when the user asks or when the Source's sign-in changes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, false, not_, or_

from backend.db.models import Episode, Video
from backend.db.models.media_item import MediaItemBase
from backend.services.sites import collection_site, video_site
from sources import Access, UnknownSourceError, all_sources, get_source, site_for, site_of

CHECK_GAPS = (
    timedelta(days=1), timedelta(days=2), timedelta(days=4),
    timedelta(days=7), timedelta(days=7), timedelta(days=7), timedelta(days=7),
)
"""The time before each check of refused media: after 1, 3 and 7 days, then weekly up to five weeks."""


def site_access(source_key: str, site_key: str | None, key: str | None) -> Access | None:
    """What the media's Site calls the access it needs: as the Site itself says, else as the media's
    Source names it on that Site, such as a membership yt-dlp tells on a Site made for another Source."""
    if key is None or site_key is None:
        return None
    found = site_of(site_key).access(key)
    if found is None:
        try:
            own = get_source(source_key).site_of(site_key)
        except UnknownSourceError:
            own = None
        found = own.access(key) if own is not None else None
    return found


def link_access(source_key: str, url: str, key: str | None) -> Access | None:
    """What the Site of a link calls the access its video needs."""
    return site_access(source_key, site_for(url, source_key).key, key) if key is not None else None


def media_site_key(media: MediaItemBase) -> str | None:
    """The key of the Site the media is on, told from its link while VODLoft has not stored it yet."""
    if isinstance(media, Episode):
        return media.collection.site_key or collection_site(media.collection).key
    if isinstance(media, Video):
        return media.site_key or video_site(media).key
    return None


def media_access(media: MediaItemBase) -> Access | None:
    """What the media's Site calls the access the media needs."""
    return site_access(media.source_key, media_site_key(media), media.access)


class AccessLocks:
    """Which media is locked, asking each Source once whether VODLoft has an access."""

    def __init__(self) -> None:
        self._has: dict[tuple[str, str], bool | None] = {}

    def has_access(self, source_key: str, key: str) -> bool | None:
        if (source_key, key) not in self._has:
            try:
                self._has[source_key, key] = get_source(source_key).has_access(key)
            except UnknownSourceError:
                self._has[source_key, key] = None
        return self._has[source_key, key]

    def locked(self, media: MediaItemBase) -> bool:
        """The media needs an access VODLoft does not have, or the Source refused it for lack of it."""
        if media.access is None:
            return False
        return media.access_refused_at is not None or self.has_access(media.source_key, media.access) is False


def access_locked(source_key: str, access: str | None, refused_at: datetime | None) -> bool:
    """``AccessLocks.locked`` for media known by its columns alone."""
    if access is None:
        return False
    return refused_at is not None or AccessLocks().has_access(source_key, access) is False


def access_granted(source_key: str, access: str | None, refused_at: datetime | None) -> bool:
    """The media needs an access, and the Source says VODLoft has it, such as the membership level
    of the account VODLoft signs in with."""
    if access is None or refused_at is not None:
        return False
    return AccessLocks().has_access(source_key, access) is True


def media_locked(media: MediaItemBase) -> bool:
    return AccessLocks().locked(media)


def locked_clause(item=MediaItemBase):
    """SQL for ``AccessLocks.locked``."""
    lacking = [
        and_(item.source_key == source.id, item.access == access.key)
        for source in all_sources() for site in source.sites for access in site.accesses
        if source.has_access(access.key) is False
    ]
    return and_(item.access.is_not(None), or_(item.access_refused_at.is_not(None), *lacking, false()))


def granted_clause(item=MediaItemBase):
    """SQL for ``access_granted``."""
    having = [
        and_(item.source_key == source.id, item.access == access.key)
        for source in all_sources() for site in source.sites for access in site.accesses
        if source.has_access(access.key) is True
    ]
    return and_(item.access.is_not(None), item.access_refused_at.is_(None), or_(*having, false()))


def without_access_clause(item=MediaItemBase):
    """SQL for media that needs an access VODLoft is not known to have: locked, or left for a download
    to find out, such as a channel membership."""
    return and_(item.access.is_not(None), not_(granted_clause(item)))


def lock_refused(media: MediaItemBase, access: str, *, now: datetime | None = None) -> None:
    """The Source refused the media for lack of the access: lock it and plan the first check."""
    now = now or datetime.now(timezone.utc)
    media.access = access
    media.access_refused_at = now
    if media.access_check_at is None and media.access_checks < len(CHECK_GAPS):
        media.access_check_at = now + CHECK_GAPS[media.access_checks]


def record_check(media: MediaItemBase, access: str | None, *, now: datetime | None = None) -> None:
    """Store what a check found: the access the media needs now, or None when anyone may download it."""
    now = now or datetime.now(timezone.utc)
    if access is None:
        unlock(media)
        return
    media.access = access
    if media.access_refused_at is None:
        # Nothing was refused since the check was asked for, so a download tries again.
        media.access_check_at = None
        return
    media.access_checks += 1
    media.access_check_at = now + CHECK_GAPS[media.access_checks] if media.access_checks < len(CHECK_GAPS) else None


def apply_source_access(media: MediaItemBase, access: str | None) -> None:
    """Store the access a fresh lookup of the media says it needs. Media anyone may download is unlocked."""
    if access is None:
        unlock(media)
    else:
        media.access = access


def unlock(media: MediaItemBase) -> None:
    media.access = None
    media.access_refused_at = None
    media.access_check_at = None
    media.access_checks = 0
