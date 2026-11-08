"""Media that VODLoft cannot download for lack of an access the Source wants, such as NPO Plus,
a Daily Wire membership level or a YouTube channel membership.

Such media is locked: it is not an error and its download is not retried. VODLoft checks
whether refused media opened up for everyone after a day, three days and a week, then weekly
for a few weeks, and checks right away when the user asks or when the Source's sign-in changes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, false, or_

from backend.db.models.media_item import MediaItemBase
from sources import Access, UnknownSourceError, all_sources, get_source

CHECK_GAPS = (
    timedelta(days=1), timedelta(days=2), timedelta(days=4),
    timedelta(days=7), timedelta(days=7), timedelta(days=7), timedelta(days=7),
)
"""The time before each check of refused media: after 1, 3 and 7 days, then weekly up to five weeks."""


def source_access(source_key: str, key: str | None) -> Access | None:
    """The Source's Access by its key."""
    try:
        return get_source(source_key).access(key)
    except UnknownSourceError:
        return None


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


def media_locked(media: MediaItemBase) -> bool:
    return AccessLocks().locked(media)


def locked_clause(item=MediaItemBase):
    """SQL for ``AccessLocks.locked``."""
    lacking = [
        and_(item.source_key == source.id, item.access == access.key)
        for source in all_sources() for access in source.accesses
        if source.has_access(access.key) is False
    ]
    return and_(item.access.is_not(None), or_(item.access_refused_at.is_not(None), *lacking, false()))


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
