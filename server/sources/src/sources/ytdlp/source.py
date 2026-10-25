from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from ..contract import (
    ANY_DOMAIN, Feature, LinkKind, MoviePlayback, PlaybackKind, ProgramStatus, ResolvedLink, Source, VideoDetails,
)
from . import runner

GENERIC_SITE = "Other sites · best effort"
_CACHE_SECONDS = 300


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
    features = frozenset({Feature.VIDEOS, Feature.PROGRAM_UPDATES, Feature.COOKIES})

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
        info = runner.run_json("--no-playlist", "--flat-playlist", "--playlist-items", "1", url)
        with self._cache_lock:
            self._cache[url] = (now, info)
        return info

    def resolve(self, url: str) -> ResolvedLink | None:
        try:
            info = self._info(url)
        except runner.YtDlpError as exc:
            if "Unsupported URL" in str(exc):
                return None
            raise
        site = _site(info)
        if info.get("_type") == "playlist":
            return ResolvedLink(
                kind=LinkKind.SHOW,
                slug=str(info.get("id") or url),
                url=info.get("webpage_url") or url,
                title=info.get("title") or info.get("channel") or url,
                description=info.get("description"),
                image_url=_thumbnail(info),
                author_name=info.get("uploader") or info.get("channel"),
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
        )

    def video_details(self, url: str) -> VideoDetails:
        info = self._info(url)
        if info.get("_type") == "playlist":
            raise runner.YtDlpError("This link is a playlist or channel, not a single video")
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
        )

    def video_playback(self, *, slug: str, url: str) -> MoviePlayback:
        return MoviePlayback(url=url, kind=PlaybackKind.YTDLP, command=runner.command())

    def episode_media(self, *, slug: str, members_only: bool, interactive: bool = False):
        raise NotImplementedError("yt-dlp has no shows yet")

    def movie_playback(self, **_kwargs) -> MoviePlayback:
        raise NotImplementedError("yt-dlp has no movies")

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
