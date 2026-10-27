from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from downloader.ytdlp import is_drm_message, is_unsupported_url_message

from ..contract import (
    ANY_DOMAIN, MAIN_TAG, ApiKeyRejected, EpisodeTag, RssEpisodeType, ApiQuotaShare, ApiStatus, Feature, LinkKind, Playback, PlaybackKind, ProgramStatus,
    ResolvedLink, ShowDetails, Source, SourceProblem, VideoDetails, link_host, on_domain,
)
from .. import pacing, ytdlp_runner as runner
from .youtube_api import ApiKeyError, Share, YouTubeApiClient, YouTubeApiError, key as api_key, mapping, quota
from .youtube_api.catalogue import Catalogue
from .youtube_api.client import MAX_RESULTS

logger = logging.getLogger(__name__)

GENERIC_SITE = "Other sites · best effort"
_CACHE_SECONDS = 300
# Pause between per-video lookups while listing a show, so a large channel
# does not look like a scraper to the site.
_LISTING_PAUSE_SECONDS = 1.0
_YOUTUBE_CHANNEL = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_UNAVAILABLE_TITLES = {"[Private video]", "[Deleted video]"}
_VIDEO_TAG = EpisodeTag(MAIN_TAG, "Video", "A normal video", main=True)
_YOUTUBE_TAGS = (
    _VIDEO_TAG,
    EpisodeTag("short", "Short", "A YouTube Short", selected_by_default=False, rss_episode_type=RssEpisodeType.BONUS),
    EpisodeTag(
        "livestream", "Livestream",
        "A livestream or premiere: upcoming, live now or finished. Finishing does not change the tag.",
    ),
)
# yt-dlp reports a livestream that is still live, upcoming or long finished alike.
_LIVE_STATUSES = {"is_live", "is_upcoming", "was_live", "post_live"}
# Upcoming and live videos have nothing to download yet; a later scan adds them once they have finished.
_PENDING_STATUSES = {"is_live", "is_upcoming"}
# Without a key, a channel's uploads are listed tab by tab. A channel may have no Shorts or Live tab.
_CHANNEL_EXTRA_TABS = ("shorts", "streams")


def show_url(url: str) -> str:
    """A YouTube channel's link lists its tabs; the show is its Videos tab."""
    parts = urlsplit(url)
    if on_domain(link_host(url), "youtube.com") and _YOUTUBE_CHANNEL.match(parts.path):
        return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/videos"))
    return url


def _listing_urls(url: str) -> list[str]:
    """The pages that list a show's videos: for a channel's Videos tab, its Shorts and Live tabs too."""
    url = show_url(url)
    ref = mapping.youtube_ref(url)
    if ref is None or ref.kind == "playlist" or ref.tab != "videos":
        return [url]
    parts = urlsplit(url)
    base = parts.path.rstrip("/").removesuffix("/videos")
    return [url] + [urlunsplit(parts._replace(path=f"{base}/{tab}")) for tab in _CHANNEL_EXTRA_TABS]


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


def _is_youtube(url: str) -> bool:
    host = link_host(url)
    return on_domain(host, "youtube.com") or host == "youtu.be"


def _tag(info: dict, url: str) -> str:
    """Short and Livestream, as yt-dlp's full extraction of a YouTube video says."""
    if not str(info.get("extractor_key") or "").startswith("Youtube"):
        return MAIN_TAG
    media_type = info.get("media_type")
    if media_type in {"short", "livestream"}:
        return media_type
    if info.get("live_status") in _LIVE_STATUSES:
        return "livestream"
    if "/shorts/" in (info.get("webpage_url") or url):
        return "short"
    return MAIN_TAG


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
        if not is_drm_message(str(exc)):
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
    features = frozenset({
        Feature.SHOWS, Feature.EPISODE_LISTS, Feature.VIDEOS, Feature.PROGRAM_UPDATES, Feature.COOKIES, Feature.API_KEY,
    })
    episode_tags = _YOUTUBE_TAGS

    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._cache_lock = threading.Lock()

    def episode_tags_for(self, url: str | None) -> tuple[EpisodeTag, ...]:
        """Shorts and livestreams are YouTube's; other sites only have videos."""
        return _YOUTUBE_TAGS if url is None or _is_youtube(url) else (_VIDEO_TAG,)

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

    @staticmethod
    def _catalogue(*, adding: bool) -> Catalogue | None:
        """The YouTube Data API, when a key is set. Adding a show is paid from the units kept free first."""
        key = api_key.load()
        if key is None:
            return None
        return Catalogue(YouTubeApiClient(key), (Share.RESERVE, Share.CHECKS) if adding else (Share.CHECKS,))

    def _youtube_ref(self, url: str) -> mapping.YouTubeRef | None:
        """The channel or playlist a link points at, with an old /c/ link's channel ID looked up by yt-dlp."""
        ref = mapping.youtube_ref(url)
        if ref is not None and ref.kind == "custom":
            channel_id = self._info(url).get("channel_id")
            ref = mapping.YouTubeRef("channel", str(channel_id), ref.tab) if channel_id else None
        return ref

    def _api_show(self, url: str) -> ShowDetails | None:
        """The show through the YouTube Data API, or None to ask yt-dlp."""
        catalogue = self._catalogue(adding=True)
        if catalogue is None or mapping.youtube_ref(url) is None:
            return None
        try:
            ref = self._youtube_ref(url)
            return catalogue.show(ref, url) if ref is not None else None
        except (YouTubeApiError, runner.YtDlpError) as exc:
            logger.info("Looking %s up with yt-dlp, because the YouTube API could not: %s", url, exc)
            return None

    def resolve(self, url: str) -> ResolvedLink | None:
        url = show_url(url)
        if show := self._api_show(url):
            return ResolvedLink(
                kind=LinkKind.SHOW, slug=show.slug, url=show.url, title=show.title,
                description=show.description, image_url=show.image_url, author_name=show.author_name,
                site="YouTube",
            )
        try:
            info = self._info(url)
        except runner.YtDlpError as exc:
            if is_unsupported_url_message(str(exc)):
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
            tag=_tag(info, url),
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
        if show := self._api_show(url):
            return show
        info = self._info(url)
        if info.get("_type") != "playlist":
            raise runner.YtDlpError("This link is a single video, not a channel or playlist")
        return self._show(info, url)

    def list_episodes(self, url: str, *, known: frozenset[str]) -> Iterator[VideoDetails]:
        """A YouTube show's videos come through the API when a key is set, and through yt-dlp otherwise.

        The API lists all of a channel's uploads in seconds. yt-dlp lists the
        Videos, Shorts and Live tabs and looks every new video up on its own.
        """
        catalogue = self._catalogue(adding=not known) if mapping.youtube_ref(show_url(url)) else None
        if catalogue is not None:
            try:
                ref = self._youtube_ref(show_url(url))
                ids = catalogue.video_ids(catalogue.playlist_id(ref)) if ref is not None else None
            except (YouTubeApiError, runner.YtDlpError) as exc:
                logger.info("Listing %s with yt-dlp, because the YouTube API could not: %s", url, exc)
                ids = None
            if ids is not None:
                logger.info("Listing %s through the YouTube API", url)
                yield from self._details_from_api(catalogue, [video_id for video_id in ids if video_id not in known])
                return
        yield from self._list_with_ytdlp(url, known)

    def _details_from_api(self, catalogue: Catalogue, ids: list[str]) -> Iterator[VideoDetails]:
        for start in range(0, len(ids), MAX_RESULTS):
            batch = ids[start:start + MAX_RESULTS]
            try:
                items = catalogue.videos(batch)
                shorts = catalogue.shorts_among(items)
            except YouTubeApiError as exc:
                # Only this batch falls back to yt-dlp; the next one tries the API again.
                logger.info("Looking %d videos up with yt-dlp, because the YouTube API could not: %s", len(batch), exc)
                for video_id in batch:
                    if details := self._look_up(mapping.video_url(video_id)):
                        yield details
                continue
            for item in items:
                if not mapping.is_pending(item):
                    yield mapping.video(item, short=item["id"] in shorts)

    def _look_up(self, url: str) -> VideoDetails | None:
        """One video through yt-dlp, or None when it cannot be looked up or has nothing to download yet."""
        try:
            info = _lookup("--no-playlist", url)
        except runner.YtDlpError as exc:
            logger.info("Skipping %s for now: %s", url, exc)
            return None
        finally:
            pacing.pause(_LISTING_PAUSE_SECONDS)
        if info.get("live_status") in _PENDING_STATUSES:
            logger.info("Skipping %s until it has finished", url)
            return None
        return self._video(info, url)

    def _list_with_ytdlp(self, url: str, known: frozenset[str]) -> Iterator[VideoDetails]:
        seen = set(known)
        for index, listing_url in enumerate(_listing_urls(url)):
            try:
                listing = runner.run_json("--flat-playlist", listing_url)
            except runner.YtDlpError as exc:
                if index == 0:
                    raise
                logger.info("Not listing %s: %s", listing_url, exc)
                continue
            for entry in listing.get("entries") or []:
                if not isinstance(entry, dict) or not entry.get("id") or entry.get("title") in _UNAVAILABLE_TITLES:
                    continue
                if video_slug(entry) in seen:
                    continue
                entry_url = entry.get("url") or entry.get("webpage_url")
                if not entry_url:
                    continue
                seen.add(video_slug(entry))
                if details := self._look_up(entry_url):
                    yield details

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

    def problems(self) -> list[SourceProblem]:
        if api_key.load() is None:
            return []
        problems = []
        if problem := api_key.problem():
            problems.append(SourceProblem("YouTube API key does not work", problem.message, problem.fix_url))
        status = quota.status()
        if status.exhausted:
            problems.append(SourceProblem(
                "YouTube API quota used up",
                "Google says today's quota is used up. VODLoft uses RSS and yt-dlp until it resets at midnight "
                "Pacific time. Nothing is lost; checks are slower.",
            ))
        return problems

    def api_status(self, shows: Sequence[tuple[str, int]] = ()) -> ApiStatus:
        key = api_key.load()
        counts = [count for url, count in shows if on_domain(link_host(url), "youtube.com")]
        status = quota.status()
        problem = api_key.problem() if key else None
        return ApiStatus(
            key_hint=api_key.hint(key) if key else None,
            shares=tuple(ApiQuotaShare(usage.share.value, usage.used, usage.limit) for usage in status.shares),
            daily_quota=status.daily_quota,
            exhausted=status.exhausted,
            resets_at=status.resets_at,
            problem=problem.message if problem else None,
            problem_fix_url=problem.fix_url if problem else None,
            show_count=len(counts),
            rescan_units=quota.rescan_units(counts),
        )

    @staticmethod
    def _test_key(key: str, *, stored: bool) -> None:
        try:
            YouTubeApiClient(key, stored=stored).test()
        except ApiKeyError as exc:
            raise ApiKeyRejected(str(exc), exc.fix_url) from exc
        except YouTubeApiError as exc:
            # The key may be fine; Google could not say right now.
            logger.info("Could not test the YouTube API key: %s", exc)

    def save_api_key(self, key: str) -> None:
        key = key.strip()
        if not key:
            raise ApiKeyRejected("Paste an API key")
        self._test_key(key, stored=False)
        api_key.save(key)

    def test_api_key(self) -> None:
        key = api_key.load()
        if key is None:
            raise ApiKeyRejected("No API key is set")
        self._test_key(key, stored=True)

    def remove_api_key(self) -> None:
        api_key.remove()
