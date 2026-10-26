from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from ..contract import (
    ANY_DOMAIN, Feature, LinkKind, Playback, PlaybackKind, ProgramStatus, ResolvedLink, ShowDetails, Source,
    VideoDetails, link_host, on_domain,
)
from .. import pacing, ytdlp_runner as runner

logger = logging.getLogger(__name__)

GENERIC_SITE = "Other sites · best effort"
_CACHE_SECONDS = 300
# Pause between per-video lookups while listing a show, so a large channel
# does not look like a scraper to the site.
_LISTING_PAUSE_SECONDS = 1.0
_YOUTUBE_CHANNEL = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_UNAVAILABLE_TITLES = {"[Private video]", "[Deleted video]"}


def show_url(url: str) -> str:
    """A YouTube channel's link lists its tabs; the show is its Videos tab."""
    parts = urlsplit(url)
    if on_domain(link_host(url), "youtube.com") and _YOUTUBE_CHANNEL.match(parts.path):
        return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/videos"))
    return url


def _site(info: dict) -> str:
    extractor = str(info.get("extractor_key") or "")
    if extractor == "Generic":
        return GENERIC_SITE
    if extractor.startswith("Youtube"):
        return "YouTube"
    return str(info.get("webpage_url_domain") or extractor or "Unknown site")


def video_slug(info: dict) -> str:
    """The id yt-dlp gives the video, prefixed by its extractor except on YouTube."""
    extractor = str(info.get("extractor_key") or info.get("ie_key") or "").lower()
    video_id = str(info["id"])
    if extractor.startswith("youtube"):
        return video_id
    return f"{extractor or 'site'}-{video_id}"


def _published_at(info: dict) -> datetime | None:
    for key in ("release_timestamp", "timestamp"):
        if isinstance(info.get(key), (int, float)):
            return datetime.fromtimestamp(info[key], tz=timezone.utc)
    for key in ("release_date", "upload_date"):
        value = info.get(key)
        if isinstance(value, str) and len(value) == 8 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


def _is_drm_error(exc: Exception) -> bool:
    return "drm" in str(exc).lower()


def _drm_protected(info: dict) -> bool:
    """yt-dlp marks a video, or each of its formats, that is protected by DRM."""
    if info.get("_has_drm"):
        return True
    formats = [f for f in info.get("formats") or [] if isinstance(f, dict)]
    return bool(formats) and all(f.get("has_drm") for f in formats)


def _lookup(*args: str) -> dict:
    """Look up a link. A video protected by DRM is looked up again for its details alone."""
    try:
        return runner.run_json(*args)
    except runner.YtDlpError as exc:
        if not _is_drm_error(exc):
            raise
    info = runner.run_json("--allow-unplayable-formats", *args)
    return {**info, "_has_drm": True}


def _thumbnail(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbnails = [t for t in info.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    return thumbnails[-1]["url"] if thumbnails else None


class YtDlpSource(Source):
    """Every site yt-dlp supports, and any page with a plain video on it."""

    id = "ytdlp"
    name = "yt-dlp"
    domains = (ANY_DOMAIN,)
    features = frozenset({Feature.SHOWS, Feature.EPISODE_LISTS, Feature.VIDEOS, Feature.PROGRAM_UPDATES, Feature.COOKIES})

    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._cache_lock = threading.Lock()

    def _info(self, url: str) -> dict:
        """The video info for a link. Adding a video right after looking up its link reuses the lookup."""
        now = time.monotonic()
        with self._cache_lock:
            self._cache = {key: value for key, value in self._cache.items() if now - value[0] < _CACHE_SECONDS}
            if url in self._cache:
                return self._cache[url][1]
        info = _lookup("--no-playlist", "--flat-playlist", "--playlist-items", "1", url)
        with self._cache_lock:
            self._cache[url] = (now, info)
        return info

    def resolve(self, url: str) -> ResolvedLink | None:
        url = show_url(url)
        try:
            info = self._info(url)
        except runner.YtDlpError as exc:
            if "Unsupported URL" in str(exc):
                return None
            raise
        site = _site(info)
        if info.get("_type") == "playlist":
            show = self._show(info, url)
            return ResolvedLink(
                kind=LinkKind.SHOW, slug=show.slug, url=show.url, title=show.title,
                description=show.description, image_url=show.image_url, author_name=show.author_name,
                site=site,
            )
        return ResolvedLink(
            kind=LinkKind.VIDEO,
            slug=video_slug(info),
            url=info.get("webpage_url") or url,
            title=info.get("title") or url,
            description=info.get("description"),
            image_url=_thumbnail(info),
            author_name=info.get("uploader") or info.get("channel"),
            site=site,
            drm_protected=_drm_protected(info),
        )

    def video_details(self, url: str) -> VideoDetails:
        info = self._info(url)
        if info.get("_type") == "playlist":
            raise runner.YtDlpError("This link is a playlist or channel, not a single video")
        return self._video(info, url)

    @staticmethod
    def _video(info: dict, url: str) -> VideoDetails:
        duration = info.get("duration")
        return VideoDetails(
            slug=video_slug(info),
            url=info.get("webpage_url") or url,
            title=info.get("title") or url,
            description=info.get("description"),
            duration=float(duration) if isinstance(duration, (int, float)) else None,
            image_url=_thumbnail(info),
            author_name=info.get("uploader") or info.get("channel"),
            author_url=info.get("uploader_url") or info.get("channel_url"),
            published_at=_published_at(info),
            drm_protected=_drm_protected(info),
        )

    @staticmethod
    def _show(info: dict, url: str) -> ShowDetails:
        channel = info.get("channel") or info.get("uploader")
        # A channel's Videos tab is titled "<channel> - Videos"; the show is the channel.
        is_channel = bool(info.get("channel_id")) and info.get("channel_id") == info.get("id")
        return ShowDetails(
            slug=str(info.get("id") or url),
            url=info.get("webpage_url") or url,
            title=(channel if is_channel else info.get("title")) or channel or url,
            description=info.get("description") or None,
            image_url=_thumbnail(info),
            author_name=channel,
            author_url=info.get("channel_url") or info.get("uploader_url"),
        )

    def show_details(self, url: str) -> ShowDetails:
        url = show_url(url)
        info = self._info(url)
        if info.get("_type") != "playlist":
            raise runner.YtDlpError("This link is a single video, not a channel or playlist")
        return self._show(info, url)

    def list_episodes(self, url: str, *, known: frozenset[str]) -> Iterator[VideoDetails]:
        listing = runner.run_json("--flat-playlist", show_url(url))
        for entry in listing.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("id") or entry.get("title") in _UNAVAILABLE_TITLES:
                continue
            if video_slug(entry) in known:
                continue
            entry_url = entry.get("url") or entry.get("webpage_url")
            if not entry_url:
                continue
            try:
                info = _lookup("--no-playlist", entry_url)
            except runner.YtDlpError as exc:
                logger.info("Skipping %s for now: %s", entry_url, exc)
                continue
            finally:
                pacing.pause(_LISTING_PAUSE_SECONDS)
            yield self._video(info, entry_url)

    def video_playback(self, *, slug: str, url: str) -> Playback:
        return Playback(url=url, kind=PlaybackKind.YTDLP, command=runner.command())



    def program_status(self) -> ProgramStatus:
        last_update_at, last_update_error = runner.last_update()
        return ProgramStatus(
            name="yt-dlp", version=runner.version(),
            last_update_at=last_update_at, last_update_error=last_update_error,
        )

    def program_update_due(self) -> bool:
        return runner.update_due()

    def update_program(self) -> ProgramStatus:
        runner.update()
        return self.program_status()

    def has_cookies(self) -> bool:
        return runner.cookies_path().is_file()

    def save_cookies(self, content: bytes) -> None:
        runner.save_cookies(content)

    def remove_cookies(self) -> None:
        runner.remove_cookies()
