"""When a Collection's downloads use its Site's cookies file, as chosen on its edit page.

Signing in for every download can get an account flagged, so by default a Collection downloads without the cookies
file. When a download fails because the Source wanted someone signed in, the Collection uses the cookies file for a
week, starting with the retry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode
from backend.db.models.media_download import MediaDownloadBase
from backend.types.collection_types import CookiesMode
from sources import get_source
from sources.contract import Feature
from sources.cookies import site_cookies

logger = logging.getLogger(__name__)

AUTOMATIC_COOKIES_FOR = timedelta(days=7)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def uses_cookies(collection: Collection, now: Optional[datetime] = None) -> bool:
    if collection.cookies_mode == CookiesMode.ALWAYS:
        return True
    if collection.cookies_mode == CookiesMode.NEVER:
        return False
    until = collection.cookies_needed_until
    return until is not None and _aware(until) > (now or datetime.now(timezone.utc))


def note_failed_download(session: Session, media_download_id: int, error: str) -> bool:
    """Start using the cookies file for the episode's Collection when the failure says signing in would help.

    True when the Collection now uses it, so a retry can succeed.
    """
    download = session.get(MediaDownloadBase, media_download_id)
    media = download.media if download is not None else None
    if not isinstance(media, Episode):
        return False
    collection = media.collection
    source = get_source(collection.source_key)
    if (
        collection.cookies_mode != CookiesMode.AUTOMATIC
        or not source.has(Feature.OPTIONAL_COOKIES)
        or site_cookies(collection.site_key) is None
        or not source.needs_cookies(error)
    ):
        return False
    collection.cookies_needed_until = datetime.now(timezone.utc) + AUTOMATIC_COOKIES_FOR
    logger.info("%s needs signing in; '%s' uses the cookies file for a week", source.name, collection.title)
    return True
