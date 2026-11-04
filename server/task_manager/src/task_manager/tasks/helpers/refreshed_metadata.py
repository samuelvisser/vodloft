"""Bringing an episode or video VODLoft has up to date with what its Source says about it now.

The daily catalogue refresh and the metadata refresh sweep both use it. Only what
VODLoft shows and serves changes: downloaded files keep their names and sidecars,
and the publication date and tag stay, because the episode identifier follows them.
"""
from __future__ import annotations

from backend.db.models import Episode, Video
from backend.services.thumbnails import is_own_thumbnail
from sources import VideoDetails


def apply_refreshed_details(item: Episode | Video, details: VideoDetails) -> bool:
    """Take the title, description, uploader, length and picture the Source has now. Returns whether any changed.

    A field the Source left out is kept.
    """
    changes = {
        "title": details.title, "description": details.description, "author_name": details.author_name,
        # A length of zero means the Source did not say.
        "duration": details.duration or None,
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
