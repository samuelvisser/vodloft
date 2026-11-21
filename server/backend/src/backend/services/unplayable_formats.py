"""yt-dlp's ``--allow-unplayable-formats``, set in a Collection's own yt-dlp options.

With it, yt-dlp also offers the formats it can not play back, such as ones protected by DRM, and saves them as
the site serves them. VODLoft does nothing to that media itself: it only stops hiding the download of an episode
that is protected by DRM, and lets yt-dlp try. When yt-dlp or the site still refuses, the download fails like any
other and is not tried again.
"""
from __future__ import annotations

from backend.db.models import Collection, Episode
from sources import Feature, get_source
from sources.ytdlp_options import allows_unplayable_formats


def options_allow_unplayable_formats(source_key: str, ytdlp_options: str | None) -> bool:
    """Whether a Collection of this Source with these own yt-dlp options turns on ``--allow-unplayable-formats``."""
    return (
        bool(ytdlp_options)
        and get_source(source_key).has(Feature.YTDLP_OPTIONS)
        and allows_unplayable_formats(ytdlp_options)
    )


def collection_allows_unplayable_formats(collection: Collection) -> bool:
    """Whether the Collection's own yt-dlp options turn on ``--allow-unplayable-formats``."""
    return options_allow_unplayable_formats(collection.source_key, collection.ytdlp_options)


def tries_unplayable_formats(media) -> bool:
    """Whether yt-dlp downloads this media with unplayable formats allowed, by its Collection's own options."""
    return isinstance(media, Episode) and collection_allows_unplayable_formats(media.collection)


def blocked_by_drm(media) -> bool:
    """Whether DRM keeps VODLoft from downloading this media: it is protected, and nothing lets yt-dlp try."""
    return media.drm_protected and not tries_unplayable_formats(media)
