"""Bringing an episode or video VODLoft has up to date with what its Source says about it now.

The daily catalogue refresh and the metadata refresh sweep both use it. Only what
VODLoft shows and serves changes: downloaded files keep their names and sidecars,
and the publication date and tag stay, because the episode identifier follows them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.db.models import Episode, Video
from backend.services.sites import collection_site
from backend.services.thumbnails import is_own_thumbnail
from backend.services.upgrade_check import check_refreshed_changes_now
from sources import VideoDetails
from task_manager.scheduler.transactional import queue_task_after_commit

_UPGRADE_CHECK_TASK_KEY = "upgrade_check"


def apply_refreshed_details(item: Episode | Video, details: VideoDetails, *, now: datetime | None = None) -> bool:
    """Take the title, description, uploader, length and picture the Source has now. Returns whether any changed.

    A field the Source left out is kept. So is a lock: a refresh that says nothing about access does not prove
    anyone may download the item, so it only stores the access the Source says the item needs now. The item
    remembers when it was looked up, also when nothing changed.
    """
    item.metadata_refreshed_at = now or datetime.now(timezone.utc)
    changes = {
        "title": details.title, "description": details.description, "author_name": details.author_name,
        # A length of zero means the Source did not say.
        "duration": details.duration or None,
        "access": details.access,
    }
    # A frame VODLoft took stays until the Source has a picture again; refreshes do not say which.
    if details.image_url and not is_own_thumbnail(item.thumbnail_landscape_path):
        changes |= {"thumbnail_landscape_path": details.image_url, "background_image_path": details.image_url}
    changed = False
    for name, value in changes.items():
        if value is not None and getattr(item, name) != value:
            setattr(item, name, value)
            changed = True
    return changed


def check_upgrades_after_refresh(s: Session, episode: Episode) -> None:
    """Start the upgrade check once the refresh commits, when the refreshed metadata shows that something an
    episode's downloads count as better changed. When a refresh cannot tell, the check keeps its own schedule."""
    if check_refreshed_changes_now(episode, collection_site(episode.collection), datetime.now(timezone.utc)):
        queue_task_after_commit(s, def_key=_UPGRADE_CHECK_TASK_KEY, resource_type="system", resource_id=0)
