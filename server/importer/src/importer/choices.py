"""Local Media Profile and Download Profile choices that importers make the same way from another program's settings."""
from __future__ import annotations

from collections.abc import Collection, Mapping

PREFER_H264 = [
    {"codec": "h264", "allowed": True}, {"codec": "vp9", "allowed": True},
    {"codec": "av1", "allowed": True}, {"codec": "h265", "allowed": True},
]
"""Your own codecs: H.264 first, as yt-dlp prefers it in an MP4, with every codec allowed."""

SPONSORBLOCK_CATEGORIES = (
    "sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "filler", "hook", "music_offtopic",
)


def video_quality(container: str, above_1080p: bool) -> dict[str, object]:
    """The quality goal for videos in ``container`` (mp4 or mkv), up to a resolution above 1080p or not.

    Above 1080p there is rarely H.264, so only a lower resolution in MP4 is Compatibility; anything else is
    Your own, with H.264 first and every codec allowed.
    """
    if container == "mp4" and not above_1080p:
        return {"quality_goal": "compatibility"}
    return {"quality_goal": "custom", "video_codecs": PREFER_H264, "container": container, "audio_codec": "aac"}


def sponsorblock(actions: Mapping[str, str]) -> dict[str, object]:
    """SponsorBlock with ``actions`` (cut or chapter) by category, keeping the others; off when there are none."""
    on = bool(actions)
    return {
        "sponsorblock_enabled": on,
        "sponsorblock_segments": {
            **{category: actions.get(category, "keep") for category in SPONSORBLOCK_CATEGORIES},
            # VODLoft always marked the highlight; viewer chapters stay out.
            "poi_highlight": "chapter" if on else "keep",
            "chapter": "keep",
        },
    }


def sponsorblock_all(action: str, chosen: Collection[str]) -> dict[str, object]:
    """SponsorBlock that does ``action`` with the ``chosen`` categories."""
    return sponsorblock({category: action for category in SPONSORBLOCK_CATEGORIES if category in chosen})
