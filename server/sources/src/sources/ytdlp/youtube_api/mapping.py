"""Turns the YouTube Data API's answers into the details yt-dlp's lookups give.

The parity rule: for the same video both paths produce the same episode, above
all the same date, because the date decides the upload-year season. yt-dlp
dates a livestream by when it actually started and every other video by when
it was published, so this does too. The API rounds durations up to the next
second where yt-dlp rounds down, which moves nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlsplit

from ...contract import MAIN_TAG, ShowDetails, VideoDetails, link_host, on_domain

SHORT_MAX_SECONDS = 180
"""YouTube Shorts are three minutes at most, so a longer video is never one."""

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_CHANNEL_PATH = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(?:/(videos|shorts|streams))?/?$")
_THUMBNAIL_SIZES = ("maxres", "standard", "high", "medium", "default")
# The playlists YouTube keeps per channel: all uploads, Shorts only, livestreams only.
_TAB_PLAYLIST_PREFIXES = {"videos": "UU", "shorts": "UUSH", "streams": "UULV"}


@dataclass(frozen=True)
class YouTubeRef:
    """What a YouTube show link points at.

    ``kind`` is handle, channel, username or custom (an old /c/ link the API
    cannot read) for a channel, or playlist. A channel's Videos tab stands for
    all its uploads; the Shorts and Live tabs for only those.
    """

    kind: str
    value: str
    tab: str = "videos"

    def uploads_playlist(self, channel_id: str) -> str:
        return _TAB_PLAYLIST_PREFIXES[self.tab] + channel_id.removeprefix("UC")


def youtube_ref(url: str) -> YouTubeRef | None:
    """The channel or playlist a link points at, or None for any other link."""
    if not on_domain(link_host(url), "youtube.com"):
        return None
    parts = urlsplit(url)
    if parts.path.rstrip("/") == "/playlist":
        playlist = (parse_qs(parts.query).get("list") or [None])[0]
        return YouTubeRef("playlist", playlist) if playlist else None
    match = _CHANNEL_PATH.match(parts.path)
    if not match:
        return None
    name, tab = unquote(match.group(1)), match.group(2) or "videos"
    if name.startswith("@"):
        return YouTubeRef("handle", name, tab)
    kind, value = name.split("/", 1)
    return YouTubeRef({"channel": "channel", "user": "username", "c": "custom"}[kind], value, tab)


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def published_at(item: dict) -> datetime | None:
    live = item.get("liveStreamingDetails") or {}
    return _time(live.get("actualStartTime") or (item.get("snippet") or {}).get("publishedAt"))


def duration(value: str | None) -> float | None:
    """Seconds from an ISO 8601 duration. A video that has not been broadcast yet has P0D, no duration."""
    match = _DURATION.match(value or "")
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return float(((days * 24 + hours) * 60 + minutes) * 60 + seconds) or None


def thumbnail(thumbnails: dict | None) -> str | None:
    for size in _THUMBNAIL_SIZES:
        if (thumbnails or {}).get(size, {}).get("url"):
            return thumbnails[size]["url"]
    return None


def is_pending(item: dict) -> bool:
    """An upcoming livestream or premiere, or one that is live right now, has nothing to download yet."""
    return (item.get("snippet") or {}).get("liveBroadcastContent") in {"upcoming", "live"}


def is_livestream(item: dict) -> bool:
    """The API keeps a livestream's details after the broadcast, as yt-dlp keeps calling it one."""
    return bool(item.get("liveStreamingDetails"))


def may_be_short(item: dict) -> bool:
    """Whether the video could be a Short. The API has no Shorts flag; the channel's Shorts playlist says."""
    length = duration((item.get("contentDetails") or {}).get("duration"))
    return not is_livestream(item) and (length is None or length <= SHORT_MAX_SECONDS)


def video(item: dict, *, short: bool) -> VideoDetails:
    snippet = item.get("snippet") or {}
    channel_id = snippet.get("channelId")
    tag = "livestream" if is_livestream(item) else "short" if short else MAIN_TAG
    return VideoDetails(
        slug=item["id"],
        url=video_url(item["id"]),
        title=snippet.get("title") or video_url(item["id"]),
        description=snippet.get("description"),
        duration=duration((item.get("contentDetails") or {}).get("duration")),
        image_url=thumbnail(snippet.get("thumbnails")),
        author_name=snippet.get("channelTitle"),
        author_url=channel_url(channel_id) if channel_id else None,
        published_at=published_at(item),
        tag=tag,
    )


def channel_show(item: dict, url: str) -> ShowDetails:
    snippet = item.get("snippet") or {}
    return ShowDetails(
        slug=item["id"],
        url=url,
        title=snippet.get("title") or url,
        description=snippet.get("description") or None,
        image_url=thumbnail(snippet.get("thumbnails")),
        author_name=snippet.get("title"),
        author_url=channel_url(item["id"]),
    )


def playlist_show(item: dict, url: str) -> ShowDetails:
    snippet = item.get("snippet") or {}
    channel_id = snippet.get("channelId")
    return ShowDetails(
        slug=item["id"],
        url=url,
        title=snippet.get("title") or url,
        description=snippet.get("description") or None,
        image_url=thumbnail(snippet.get("thumbnails")),
        author_name=snippet.get("channelTitle"),
        author_url=channel_url(channel_id) if channel_id else None,
    )
