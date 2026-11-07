"""Thumbnails VODLoft makes itself, for videos that have no picture of their own.

A video's Source takes a frame from the start of the video. VODLoft keeps it as
a JPEG in the thumbnail folder and stores ``thumbnails/<name>.jpg`` as the
video's picture, which the browser loads from the ``/assets`` route.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import MediaItemBase
from config import get_settings
from config.network import is_no_internet_error
from sources import get_source

logger = logging.getLogger(__name__)

_PREFIX = "thumbnails/"
_NAME = re.compile(r"^[0-9A-Za-z-]{1,64}\.jpg$")
_PICTURE_FIELDS = ("thumbnail_landscape_path", "background_image_path")


def thumbnail_root() -> Path:
    return Path(get_settings().download_settings.thumbnail_root)


def is_own_thumbnail(path: str | None) -> bool:
    return bool(path) and path.startswith(_PREFIX)


def thumbnail_file(name: str) -> Path | None:
    """The file of one of VODLoft's own thumbnails, or None when there is no such thumbnail."""
    if _NAME.match(name) is None:
        return None
    path = thumbnail_root() / name
    return path if path.is_file() else None


def own_thumbnail_file(picture: str | None) -> Path | None:
    """The file of a picture VODLoft made itself, which media items store as ``thumbnails/<name>.jpg``."""
    return thumbnail_file(picture.removeprefix(_PREFIX)) if is_own_thumbnail(picture) else None


def newest_media_item_id(s: Session) -> int:
    """The id of the newest media item, to find the items an indexing run adds after it."""
    return s.scalar(select(func.max(MediaItemBase.id))) or 0


def take_first_frames(s: Session, item_ids: Sequence[int]) -> int:
    """Give the episodes and videos among ``item_ids`` whose picture is missing a frame of the video.

    Their Source decides whether a picture is missing and takes the frame. No
    transaction stays open while it does. Returns how many thumbnails were made.
    """
    if not item_ids:
        return 0
    items = [
        (item.id, item.uuid, item.source_key, item.sharing_url, item.thumbnail_landscape_path)
        for item in s.scalars(select(MediaItemBase).where(MediaItemBase.id.in_(item_ids)).order_by(MediaItemBase.id))
        if getattr(item, "sharing_url", None) and not is_own_thumbnail(getattr(item, "thumbnail_landscape_path", None))
        and not item.removed_from_source
    ]
    s.rollback()
    made = 0
    for item_id, uuid, source_key, url, picture in items:
        try:
            frame = get_source(source_key).first_frame(url, picture)
        except Exception as exc:
            if is_no_internet_error(exc):
                raise
            logger.warning("Could not take a frame of %s: %s", url, exc)
            continue
        if frame is None:
            continue
        name = f"{uuid}.jpg"
        try:
            root = thumbnail_root()
            root.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(frame)
        except OSError as exc:
            logger.warning("Could not save the thumbnail of %s: %s", url, exc)
            continue
        item = s.get(MediaItemBase, item_id)
        if item is None:
            continue
        for field in _PICTURE_FIELDS:
            setattr(item, field, _PREFIX + name)
        s.commit()
        made += 1
    if made:
        logger.info("Made %d %s from the first frames of their videos", made, "thumbnail" if made == 1 else "thumbnails")
    return made
