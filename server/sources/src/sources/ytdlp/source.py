from __future__ import annotations

import json
import logging
import re
import threading
import time

import requests
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit, urlunsplit

from config import get_settings
from downloader.ytdlp import is_drm_message, is_unsupported_url_message

from ..contract import (
    ANY_DOMAIN, MAIN_TAG, ApiKeyRejected, EpisodePublishStatus, EpisodeTag, ItemRef, ItemRefresh, RssEpisodeType, ApiQuotaShare, ApiStatus, DownloadOptions, Feature, LinkKind, LinkPreview, LiveStream, MediaStream, MediaTracks, Playback, PlaybackKind, ProgramStatus,
    ResolvedLink, SearchResults, CollectionDetails, Site, SiteSetting, Source, SourceProblem, SponsorBlockSegment, StreamMethod, UpgradeOffer, VideoDetails, VideoFormat, VideoFormats,
    link_host, on_domain,
)
from .. import pacing, ytdlp_runner as runner
from . import sites, thumbnails, youtube_rss, youtube_search
from .youtube_api import ApiKeyError, QuotaExceededError, Share, YouTubeApiClient, YouTubeApiError, key as api_key, mapping, quota
from .youtube_api.catalogue import Catalogue
from .youtube_api.client import MAX_RESULTS

logger = logging.getLogger(__name__)

GENERIC_SITE = "Other sites · best effort"
_CACHE_SECONDS = 300
# Pause between per-video lookups while listing a collection, so a large channel
# does not look like a scraper to the site.
_LISTING_PAUSE_SECONDS = 1.0
_YOUTUBE_CHANNEL = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_UNAVAILABLE_TITLES = {"[Private video]", "[Deleted video]"}
_VIDEO_TAG = EpisodeTag(MAIN_TAG, "Video", "A normal video", "video", "videos", main=True)
_YOUTUBE_TAGS = (
    _VIDEO_TAG,
    EpisodeTag("short", "Short", "A YouTube Short", "short", "shorts", selected_by_default=False, rss_episode_type=RssEpisodeType.BONUS),
    EpisodeTag(
        "livestream", "Livestream",
        "A livestream: upcoming, live now or finished. Finishing does not change the tag. A premiere is a video.",
        "livestream", "livestreams",
    ),
)
# yt-dlp reports a livestream that is still live, upcoming or long finished alike.
_LIVE_STATUSES = {"is_live", "is_upcoming", "was_live", "post_live"}
# Where a video is in its life, as yt-dlp's live_status says. An upcoming video past its start is delayed.
_PUBLISH_STATUSES = {
    "is_upcoming": EpisodePublishStatus.SCHEDULED,
    "is_live": EpisodePublishStatus.LIVE,
    "post_live": EpisodePublishStatus.SOURCE_PROCESSING,
}
# What yt-dlp says about a video the site no longer has, such as a cancelled stream. A video
# blocked in this country, or one that needs signing in, is still there, unless it went private.
_GONE_ERRORS = ("video unavailable", "has been removed", "no longer available", "does not exist")
_STILL_THERE_ERRORS = ("country", "sign in", "--cookies", "members")
_PRIVATE_ERRORS = ("private video", "this video is private")
# Without a key, a channel's uploads are listed tab by tab. A channel may have no Shorts or Live tab.
_CHANNEL_EXTRA_TABS = ("shorts", "streams")
# The same search within an hour is answered from memory, so going back to the results costs nothing.
_SEARCH_CACHE_SECONDS = 3600
# How many of a collection's newest videos a quick check through yt-dlp looks at, per tab.
_LATEST_COUNT = 15


def collection_url(url: str) -> str:
    """A YouTube channel's link lists its tabs; the collection is its Videos tab."""
    parts = urlsplit(url)
    if on_domain(link_host(url), "youtube.com") and _YOUTUBE_CHANNEL.match(parts.path):
        return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/videos"))
    return url


def _listing_urls(url: str) -> list[str]:
    """The pages that list a collection's videos: for a channel's Videos tab, its Shorts and Live tabs too."""
    url = collection_url(url)
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


_OEMBED_URL = "https://www.youtube.com/oembed"
_OEMBED_TIMEOUT_SECONDS = 5
_SPONSORBLOCK_URL = "https://sponsor.ajay.app/api/skipSegments"
_SPONSORBLOCK_TIMEOUT_SECONDS = 15


def _feed(ref: mapping.YouTubeRef) -> dict[str, str]:
    """Which RSS feed lists a YouTube channel's or playlist's newest videos."""
    if ref.kind == "channel" and ref.tab == "videos":
        return {"channel_id": ref.value}
    return {"playlist_id": ref.value if ref.kind == "playlist" else ref.uploads_playlist(ref.value)}


def _is_youtube(url: str) -> bool:
    host = link_host(url)
    return on_domain(host, "youtube.com") or host == "youtu.be"


def _tag(info: dict, url: str) -> str:
    """Short and Livestream, as yt-dlp's full extraction of a YouTube video says.

    yt-dlp calls a premiere a video, also while it is upcoming or playing for
    the first time, so then a live status alone does not make it a livestream.
    A finished broadcast does.
    """
    if not str(info.get("extractor_key") or "").startswith("Youtube"):
        return MAIN_TAG
    media_type = info.get("media_type")
    if media_type in {"short", "livestream"}:
        return media_type
    live_status = info.get("live_status")
    if live_status == "was_live" or (media_type is None and live_status in _LIVE_STATUSES):
        return "livestream"
    if "/shorts/" in (info.get("webpage_url") or url):
        return "short"
    return MAIN_TAG


def _scheduled_at(info: dict) -> datetime | None:
    if info.get("live_status") == "is_upcoming" and isinstance(info.get("release_timestamp"), (int, float)):
        return datetime.fromtimestamp(info["release_timestamp"], tz=timezone.utc)
    return None


def _publish_status(info: dict) -> EpisodePublishStatus:
    status = _PUBLISH_STATUSES.get(info.get("live_status"), EpisodePublishStatus.PUBLISHED_FINAL)
    scheduled_at = _scheduled_at(info)
    if status is EpisodePublishStatus.SCHEDULED and scheduled_at is not None and scheduled_at < datetime.now(timezone.utc):
        return EpisodePublishStatus.DELAYED
    return status


def is_gone_message(message: str) -> bool:
    """Whether yt-dlp's error says the site no longer has the video."""
    message = message.lower()
    if any(text in message for text in _PRIVATE_ERRORS):
        return True
    return any(text in message for text in _GONE_ERRORS) and not any(text in message for text in _STILL_THERE_ERRORS)


def _drm_protected(info: dict) -> bool:
    """yt-dlp marks a video, or each of its formats, that is protected by DRM."""
    if info.get("_has_drm"):
        return True
    formats = [f for f in info.get("formats") or [] if isinstance(f, dict)]
    return bool(formats) and all(f.get("has_drm") for f in formats)


_CODECS = (("avc", "h264"), ("h264", "h264"), ("hev", "h265"), ("hvc", "h265"), ("h265", "h265"),
           ("vp09", "vp9"), ("vp9", "vp9"), ("av01", "av1"), ("av1", "av1"))


def _codec(vcodec: str) -> str:
    name = vcodec.lower()
    for prefix, codec in _CODECS:
        if name.startswith(prefix):
            return codec
    return name.split(".")[0]


def _format_size(entry: dict, duration) -> int | None:
    size = entry.get("filesize") or entry.get("filesize_approx")
    if isinstance(size, (int, float)) and size > 0:
        return int(size)
    rate = entry.get("tbr")
    if isinstance(rate, (int, float)) and rate > 0 and isinstance(duration, (int, float)) and duration > 0:
        return int(rate * 1000 / 8 * duration)
    return None


def video_formats(info: dict) -> VideoFormats:
    """The downloadable streams in yt-dlp's info for a video, without storyboards or DRM."""
    duration = info.get("duration")
    videos: list[VideoFormat] = []
    audio: list[int | None] = []
    for entry in info.get("formats") or []:
        if not isinstance(entry, dict) or entry.get("has_drm") or entry.get("format_note") == "storyboard":
            continue
        vcodec, acodec = entry.get("vcodec") or "none", entry.get("acodec") or "none"
        if vcodec != "none":
            sides = [side for side in (entry.get("width"), entry.get("height")) if isinstance(side, int) and side > 0]
            if not sides:
                continue
            videos.append(VideoFormat(height=min(sides), codec=_codec(vcodec), size_bytes=_format_size(entry, duration)))
        elif acodec != "none":
            audio.append(_format_size(entry, duration))
    sizes = [size for size in audio if size]
    return VideoFormats(
        videos=tuple(videos),
        audio_size_bytes=max(sizes) if sizes else None,
        duration=float(duration) if isinstance(duration, (int, float)) else None,
    )


# The formats a feed can pass on as they are: YouTube's M4A audio, and its one MP4 with sound (360p).
_READY_AUDIO_FORMAT = "140"
# The sound of YouTube's live streams is AAC, which yt-dlp does not say.
_LIVE_AUDIO_CODECS = "mp4a.40.2"
_READY_VIDEO_FORMAT = "18"
_DIRECT_PROTOCOLS = {"http", "https"}


def _direct(entry: dict) -> bool:
    """A format VODLoft can fetch with plain HTTP range requests: no playlist, no DRM, no storyboard."""
    return (
        isinstance(entry, dict) and bool(entry.get("url")) and entry.get("protocol") in _DIRECT_PROTOCOLS
        and not entry.get("has_drm") and entry.get("format_note") != "storyboard"
    )


def _expires_at(url: str) -> float | None:
    """When a googlevideo URL stops working, from its own ``expire`` parameter."""
    values = parse_qs(urlsplit(url).query).get("expire")
    try:
        return float(values[0]) if values else None
    except ValueError:
        return None


def _media_stream(entry: dict, *, ready: bool) -> MediaStream:
    size = entry.get("filesize")
    codecs = [entry.get(kind) for kind in ("vcodec", "acodec") if (entry.get(kind) or "none") != "none"]
    bitrate = entry.get("tbr") or entry.get("abr")
    return MediaStream(
        url=entry["url"], headers=dict(entry.get("http_headers") or {}), expires_at=_expires_at(entry["url"]),
        size_bytes=int(size) if isinstance(size, (int, float)) and size > 0 else None, ready=ready,
        codecs=",".join(codecs) or None, bitrate=int(bitrate * 1000) if bitrate else None,
        width=entry.get("width"), height=entry.get("height"),
    )


def _original_language(entries: list[dict]) -> dict | None:
    """A video with dubbed audio lists each format once per language, as 140-0, 140-1 and so on, and
    also as 140-drc with its loudness evened out. Take the original language as it was made."""
    versions = [entry for entry in entries if not str(entry.get("format_id")).endswith("-drc")]
    return max(versions, key=lambda entry: entry.get("language_preference") or 0, default=None)


def stream_of(info: dict, *, audio: bool) -> MediaStream | None:
    """The stream a feed plays from yt-dlp's info for a video.

    Audio is YouTube's M4A when it is offered, and otherwise the best audio for VODLoft to
    transcode. Video is only the MP4 that already has sound in it.
    """
    formats = [entry for entry in info.get("formats") or [] if _direct(entry)]
    wanted = _READY_AUDIO_FORMAT if audio else _READY_VIDEO_FORMAT
    ready = _original_language([entry for entry in formats if str(entry.get("format_id")).split("-")[0] == wanted])
    if ready is not None:
        return _media_stream(ready, ready=True)
    if not audio:
        return None
    sound_only = [
        entry for entry in formats
        if (entry.get("vcodec") or "none") == "none" and (entry.get("acodec") or "none") != "none"
        and not str(entry.get("format_id")).endswith("-drc")
    ]
    if not sound_only:
        return None
    best = max(sound_only, key=lambda entry: (entry.get("language_preference") or 0, entry.get("abr") or entry.get("tbr") or 0))
    return _media_stream(best, ready=False)


def tracks_of(info: dict, heights: Sequence[int]) -> MediaTracks | None:
    """The H.264 video without sound at each of ``heights`` that YouTube has, and the M4A audio, from
    yt-dlp's info for a video. None without audio or video."""
    formats = [entry for entry in info.get("formats") or [] if _direct(entry)]
    audio = _original_language([
        entry for entry in formats if str(entry.get("format_id")).split("-")[0] == _READY_AUDIO_FORMAT
    ])
    video = []
    for height in sorted(heights, reverse=True):
        candidates = [
            entry for entry in formats
            if entry.get("height") == height and entry.get("ext") == "mp4" and (entry.get("acodec") or "none") == "none"
            and str(entry.get("vcodec") or "").startswith("avc1")
        ]
        best = max(candidates, key=lambda entry: entry.get("tbr") or 0, default=None)
        if best is not None:
            video.append(_media_stream(best, ready=False))
    if audio is None or not video:
        return None
    return MediaTracks(video=tuple(video), audio=_media_stream(audio, ready=True))


def _live_playlist(entry: dict) -> bool:
    return isinstance(entry, dict) and bool(entry.get("url")) and "m3u8" in str(entry.get("protocol") or "") and not entry.get("has_drm")


def live_of(info: dict, heights: Sequence[int]) -> LiveStream | None:
    """The HLS playlists of a video while it is live, from yt-dlp's info: one per resolution up to the
    highest of ``heights``, and the sound when YouTube lists it apart from the video. None when the
    video is not live."""
    if info.get("live_status") != "is_live":
        return None
    playlists = [entry for entry in info.get("formats") or [] if _live_playlist(entry)]
    best: dict[int, dict] = {}
    for entry in playlists:
        height = entry.get("height") or 0
        if (entry.get("vcodec") or "none") == "none" or not height or height > max(heights):
            continue
        if height not in best or (entry.get("tbr") or 0) > (best[height].get("tbr") or 0):
            best[height] = entry
    video = [_media_stream(best[height], ready=True) for height in sorted(best, reverse=True)]
    if not video:
        return None
    if all((best[height].get("acodec") or "none") != "none" for height in best):
        return LiveStream(video=tuple(video))
    # YouTube lists the sound of most live streams apart, as 233 and 234 without a codec or bitrate:
    # the higher number is the better one.
    sound = max(
        (entry for entry in playlists if entry.get("vcodec") == "none" and entry.get("acodec") != "none"),
        key=lambda entry: (entry.get("language_preference") or 0, entry.get("tbr") or entry.get("abr") or 0, str(entry.get("format_id"))),
        default=None,
    )
    if sound is None:
        return None
    audio = _media_stream(sound, ready=True)
    if audio.codecs is None:
        audio = replace(audio, codecs=_LIVE_AUDIO_CODECS)
    return LiveStream(video=tuple(video), audio=audio)


def _sponsorblock_segments(video_id: str, categories: Sequence[str]) -> tuple[SponsorBlockSegment, ...]:
    """The video's SponsorBlock segments of the given types; a video nobody submitted segments for has none."""
    response = requests.get(
        _SPONSORBLOCK_URL, params={
            "videoID": video_id, "categories": json.dumps(list(categories)),
            # The highlight and viewer chapters have action types of their own, which SponsorBlock leaves out unless asked.
            "actionTypes": json.dumps(["skip", "mute", "poi", "chapter"]),
        },
        timeout=_SPONSORBLOCK_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return ()
    response.raise_for_status()
    segments = []
    for entry in response.json() or ():
        span = entry.get("segment") if isinstance(entry, dict) else None
        if isinstance(span, list) and len(span) == 2 and all(isinstance(value, (int, float)) for value in span):
            segments.append(SponsorBlockSegment(str(entry.get("category")), float(span[0]), float(span[1])))
    return tuple(sorted(segments, key=lambda segment: (segment.start, segment.end)))


def _lookup(*args: str) -> dict:
    """Look up a link, the last argument, signed in on its Site. A video protected by DRM is looked up
    again for its details alone."""
    cookies = sites.cookies_for(args[-1])
    try:
        return runner.run_json(*args, cookies=cookies)
    except runner.YtDlpError as exc:
        if not is_drm_message(str(exc)):
            raise
    info = runner.run_json("--allow-unplayable-formats", *args, cookies=cookies)
    return {**info, "_has_drm": True}


def _thumbnail(info: dict) -> str | None:
    if info.get("thumbnail"):
        return thumbnails.widest_still(info["thumbnail"])
    candidates = [t for t in info.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    return thumbnails.widest_still(candidates[-1]["url"]) if candidates else None


# What yt-dlp says when a video needs someone signed in: a bot check, an age check, members-only videos.
_SIGN_IN_ERRORS = (
    "--cookies", "sign in to confirm", "login required", "login_required", "members-only", "members only",
    "join this channel", "registered users", "private video", "age-restricted",
)
# What yt-dlp says about a video that only the channel's members can watch.
_MEMBERS_ERRORS = ("join this channel", "members-only", "members only", "available to this channel's members")
_ACCESS_BY_AVAILABILITY = {"subscriber_only": sites.MEMBERS_KEY, "premium_only": sites.PREMIUM_KEY}
_OPEN_AVAILABILITIES = frozenset({"public", "unlisted"})


def _access(info: dict) -> str | None:
    """yt-dlp marks a video only the channel's members can watch as ``subscriber_only``, and one only
    the site's paying subscribers can watch as ``premium_only``."""
    return _ACCESS_BY_AVAILABILITY.get(info.get("availability"))


def _listed_open(entry: dict) -> bool:
    """Whether a listing says anyone may watch the video.

    YouTube marks every video in a listing that only members or paying
    subscribers can watch, so there a video without that mark is open. Other
    sites are only open when yt-dlp says so.
    """
    if entry.get("availability") in _OPEN_AVAILABILITIES:
        return True
    extractor = str(entry.get("ie_key") or entry.get("extractor_key") or "").lower()
    return extractor.startswith("youtube") and _access(entry) is None


class YtDlpSource(Source):
    """Every site yt-dlp supports, and any page with a plain video on it."""

    id = "ytdlp"
    name = "yt-dlp"
    domains = (ANY_DOMAIN,)
    features = frozenset({
        Feature.COLLECTIONS, Feature.EPISODE_LISTS, Feature.PAGE_STREAMS, Feature.VIDEOS, Feature.PROGRAM_UPDATES, Feature.COOKIES, Feature.OPTIONAL_COOKIES, Feature.API_KEY,
        Feature.QUICK_CHECK, Feature.CATALOGUE_REFRESH, Feature.SEARCH, Feature.COSTLY_SEARCH,
        Feature.FORMAT_CHOICES, Feature.YTDLP_OPTIONS, Feature.METADATA_REFRESH,
        Feature.PENDING_CHECKS,
    })
    episode_tags = _YOUTUBE_TAGS
    # Search covers YouTube only; other sites are added by link.
    sites_label = "YouTube, and many more"
    api_key_sites = sites.api_key_sites()
    search_label = "YouTube"

    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._searches: dict[str, tuple[float, SearchResults]] = {}
        self._cache_lock = threading.Lock()
        # A channel's handle never changes its ID, so it is looked up once.
        self._channel_ids: dict[str, str] = {}

    @property
    def download_options(self) -> DownloadOptions:
        return sites.download_options()

    def site_for(self, url: str) -> Site:
        """The site of the yt-dlp extractor that handles the link: one Site for all of YouTube's domains."""
        return sites.site_for(url)

    def site_of(self, site_key: str) -> Site:
        return sites.site_of(site_key)

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
        """The YouTube Data API, when a key is set. Adding a collection is paid from the units kept free first."""
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

    def _channel_ref(self, url: str, catalogue: Catalogue | None) -> mapping.YouTubeRef | None:
        """The channel or playlist a collection link points at, with a channel always by its ID.

        A handle or user name is looked up through the API when there is one, and
        through yt-dlp otherwise, once.
        """
        ref = mapping.youtube_ref(url)
        if ref is None or ref.kind in {"playlist", "channel"}:
            return ref
        name = f"{ref.kind}:{ref.value}"
        if name not in self._channel_ids:
            if catalogue is not None and ref.kind != "custom":
                channel_id = catalogue.channel(ref)["id"]
            else:
                channel_id = self._info(url).get("channel_id")
            if not channel_id:
                return None
            self._channel_ids[name] = str(channel_id)
        return mapping.YouTubeRef("channel", self._channel_ids[name], ref.tab)

    def _api_collection(self, url: str) -> CollectionDetails | None:
        """The collection through the YouTube Data API, or None to ask yt-dlp."""
        catalogue = self._catalogue(adding=True)
        if catalogue is None or mapping.youtube_ref(url) is None:
            return None
        try:
            ref = self._youtube_ref(url)
            return catalogue.collection(ref, url) if ref is not None else None
        except (YouTubeApiError, runner.YtDlpError) as exc:
            logger.info("Looking %s up with yt-dlp, because the YouTube API could not: %s", url, exc)
            return None

    def preview(self, url: str) -> LinkPreview | None:
        """The title and thumbnail of a YouTube video from YouTube's oEmbed, in well under a second.

        yt-dlp's full lookup takes several seconds; this shows the video while it
        runs. A link already looked up is answered from that lookup.
        """
        url = collection_url(url)
        with self._cache_lock:
            cached = self._cache.get(url)
        if cached is not None and cached[1].get("_type") != "playlist":
            info = cached[1]
            return LinkPreview(
                title=info.get("title") or url, image_url=_thumbnail(info),
                author_name=info.get("uploader") or info.get("channel"), site=_site(info),
            )
        if not _is_youtube(url) or mapping.youtube_ref(url) is not None:
            return None
        try:
            response = requests.get(
                _OEMBED_URL, params={"url": url, "format": "json"}, timeout=_OEMBED_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("No quick preview for %s: %s", url, exc)
            return None
        title = data.get("title") if isinstance(data, dict) else None
        if not title:
            return None
        return LinkPreview(
            title=str(title), image_url=data.get("thumbnail_url"), author_name=data.get("author_name"), site="YouTube",
        )

    def resolve(self, url: str) -> ResolvedLink | None:
        url = collection_url(url)
        if collection := self._api_collection(url):
            return ResolvedLink(
                kind=LinkKind.COLLECTION, slug=collection.slug, url=collection.url, title=collection.title,
                description=collection.description, image_url=collection.image_url, author_name=collection.author_name,
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
            collection = self._collection(info, url)
            return ResolvedLink(
                kind=LinkKind.COLLECTION, slug=collection.slug, url=collection.url, title=collection.title,
                description=collection.description, image_url=collection.image_url, author_name=collection.author_name,
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
            access=_access(info),
        )

    def video_details(self, url: str) -> VideoDetails:
        info = self._info(url)
        if info.get("_type") == "playlist":
            raise runner.YtDlpError("This link is a playlist or channel, not a single video")
        return self._video(info, url)

    def first_frame(self, url: str, image_url: str | None) -> bytes | None:
        if not thumbnails.still_missing(image_url):
            return None
        return thumbnails.first_frame(url)

    def video_formats(self, url: str) -> VideoFormats:
        info = self._info(url)
        if info.get("_type") == "playlist":
            raise runner.YtDlpError("This link is a playlist or channel, not a single video")
        return video_formats(info)

    def upgrade_offer(self, url: str, *, sponsorblock_categories: Sequence[str] = ()) -> UpgradeOffer:
        # A fresh lookup: what the site offered when the link was last looked up may have changed.
        info = _lookup("--no-playlist", url)
        if info.get("_type") == "playlist":
            raise runner.YtDlpError("This link is a playlist or channel, not a single video")
        languages = frozenset(
            str(language) for language, tracks in (info.get("subtitles") or {}).items()
            if language != "live_chat" and tracks
        )
        sponsorblock = None
        if sponsorblock_categories and self.site_for(url).settings.offers(SiteSetting.SPONSORBLOCK) and info.get("id"):
            sponsorblock = _sponsorblock_segments(str(info["id"]), sponsorblock_categories)
        formats = video_formats(info)
        return UpgradeOffer(
            videos=formats.videos, subtitle_languages=languages, sponsorblock=sponsorblock, duration=formats.duration,
        )

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
            access=_access(info),
            tag=_tag(info, url),
            publish_status=_publish_status(info),
            scheduled_at=_scheduled_at(info),
        )

    @staticmethod
    def _collection(info: dict, url: str) -> CollectionDetails:
        channel = info.get("channel") or info.get("uploader")
        # A channel's Videos tab is titled "<channel> - Videos"; the collection is the channel.
        is_channel = bool(info.get("channel_id")) and info.get("channel_id") == info.get("id")
        return CollectionDetails(
            slug=str(info.get("id") or url),
            url=info.get("webpage_url") or url,
            title=(channel if is_channel else info.get("title")) or channel or url,
            description=info.get("description") or None,
            image_url=_thumbnail(info),
            author_name=channel,
            author_url=info.get("channel_url") or info.get("uploader_url"),
        )

    def collection_details(self, url: str) -> CollectionDetails:
        url = collection_url(url)
        if collection := self._api_collection(url):
            return collection
        info = self._info(url)
        if info.get("_type") != "playlist":
            raise runner.YtDlpError("This link is a single video, not a channel or playlist")
        return self._collection(info, url)

    def list_episodes(self, url: str, *, known: frozenset[str]) -> Iterator[VideoDetails]:
        """A YouTube collection's videos come through the API when a key is set, and through yt-dlp otherwise.

        The API lists all of a channel's uploads in seconds. yt-dlp lists the
        Videos, Shorts and Live tabs and looks every new video up on its own.

        A channel's uploads playlist leaves out the videos only its members can
        watch, so the channel's tabs are listed with yt-dlp after the API too,
        which costs no quota. What that finds is asked of the API first, which
        still describes such a video by its ID, and only the rest is looked up.
        """
        catalogue = self._catalogue(adding=not known) if mapping.youtube_ref(collection_url(url)) else None
        if catalogue is not None:
            try:
                ref = self._channel_ref(collection_url(url), catalogue)
                ids = catalogue.video_ids(catalogue.playlist_id(ref)) if ref is not None else None
            except (YouTubeApiError, runner.YtDlpError) as exc:
                logger.info("Listing %s with yt-dlp, because the YouTube API could not: %s", url, exc)
                ids = None
            if ids is not None:
                logger.info("Listing %s through the YouTube API", url)
                listed = set(known)
                for details in self._details_from_api(catalogue, [video_id for video_id in ids if video_id not in known]):
                    listed.add(details.slug)
                    yield details
                if ref.kind != "playlist":
                    try:
                        # Also what the API listed but would not give details of, which yt-dlp may still see.
                        entries = self._unseen_entries(url, frozenset(listed))
                    except runner.YtDlpError as exc:
                        logger.info("Not listing %s's members-only videos: %s", url, exc)
                        return
                    for details in self._details_from_api(catalogue, list(entries)):
                        entry = entries.pop(details.slug, {})
                        yield details if details.access else replace(details, access=_access(entry))
                    for slug, entry in entries.items():
                        if details := self._from_entry(entry):
                            yield details
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
                if mapping.is_pending(item):
                    # Only yt-dlp tells when an upcoming video starts and whether it is a premiere.
                    if details := self._look_up(mapping.video_url(item["id"])):
                        yield details
                elif mapping.may_be_premiere(item):
                    # yt-dlp calls a finished premiere a video and a livestream a livestream.
                    yield self._look_up(mapping.video_url(item["id"])) or mapping.video(item, short=False)
                else:
                    yield mapping.video(item, short=item["id"] in shorts)

    def _look_up(self, url: str) -> VideoDetails | None:
        """One video through yt-dlp, or None when it cannot be looked up."""
        try:
            info = self._pending_info(url)
        except runner.YtDlpError as exc:
            logger.info("Skipping %s for now: %s", url, exc)
            return None
        return self._video(info, url)

    @staticmethod
    def _pending_info(url: str) -> dict:
        """The video info. An upcoming video has no formats yet, which yt-dlp calls an error
        unless told not to. A video that failed is looked up that way once more, unless it is
        clearly gone or needs signing in, and only an upcoming one is taken from that lookup:
        for any other video a missing format is still an error."""
        try:
            return _lookup("--no-playlist", url)
        except runner.YtDlpError as exc:
            message = str(exc).lower()
            if is_gone_message(message) or any(text in message for text in _SIGN_IN_ERRORS):
                raise
            error = exc
        finally:
            pacing.pause(_LISTING_PAUSE_SECONDS)
        try:
            info = runner.run_json("--no-playlist", "--ignore-no-formats-error", url, cookies=sites.cookies_for(url))
        except runner.YtDlpError:
            raise error from None
        finally:
            pacing.pause(_LISTING_PAUSE_SECONDS)
        if info.get("live_status") != "is_upcoming":
            raise error
        return info

    def check_pending(self, items: Sequence[ItemRef]) -> ItemRefresh:
        """Each item looked up with yt-dlp, which works for every site. A lookup that fails is
        only a removal when yt-dlp says the site no longer has the video."""
        details: dict[str, VideoDetails] = {}
        removed: set[str] = set()
        for ref in items:
            try:
                info = self._pending_info(ref.url)
            except runner.YtDlpError as exc:
                if is_gone_message(str(exc)):
                    removed.add(ref.slug)
                else:
                    logger.info("Could not check %s: %s", ref.url, exc)
                continue
            details[ref.slug] = self._video(info, ref.url)
        return ItemRefresh(details=details, removed=frozenset(removed))

    def _list_with_ytdlp(self, url: str, known: frozenset[str]) -> Iterator[VideoDetails]:
        for entry in self._unseen_entries(url, known).values():
            if details := self._from_entry(entry):
                yield details

    @staticmethod
    def _unseen_entries(url: str, known: frozenset[str]) -> dict[str, dict]:
        """The collection's listed videos VODLoft does not know yet, by slug, in the listing's order.

        YouTube's listing only says how long ago a video came out, which yt-dlp
        turns into a date when asked: the only date a video it cannot look up has.
        """
        entries: dict[str, dict] = {}
        for index, listing_url in enumerate(_listing_urls(url)):
            try:
                listing = runner.run_json(
                    "--flat-playlist", "--extractor-args", "youtubetab:approximate_date", listing_url,
                    cookies=sites.cookies_for(listing_url),
                )
            except runner.YtDlpError as exc:
                if index == 0:
                    raise
                logger.info("Not listing %s: %s", listing_url, exc)
                continue
            for entry in listing.get("entries") or []:
                if not isinstance(entry, dict) or not entry.get("id") or entry.get("title") in _UNAVAILABLE_TITLES:
                    continue
                if (entry.get("url") or entry.get("webpage_url")) and video_slug(entry) not in known:
                    entries.setdefault(video_slug(entry), entry)
        return entries

    def _from_entry(self, entry: dict) -> VideoDetails | None:
        """A listed video, looked up with yt-dlp."""
        entry_url = entry.get("url") or entry.get("webpage_url")
        if details := self._look_up(entry_url):
            return details
        if _access(entry):
            # yt-dlp cannot look up a members-only or premium video without the right cookies,
            # so it is kept from the listing, locked until VODLoft can download it.
            return self._video(entry, entry_url)
        return None

    def latest_items(self, url: str) -> list[ItemRef]:
        """A YouTube collection's 50 newest videos through the API, else its RSS feed's 15, else yt-dlp's listing."""
        url = collection_url(url)
        if mapping.youtube_ref(url) is None:
            return self._latest_with_ytdlp(url)
        catalogue = self._catalogue(adding=False)
        if catalogue is not None:
            try:
                ref = self._channel_ref(url, catalogue)
                if ref is not None:
                    return [ItemRef(video_id, mapping.video_url(video_id))
                            for video_id in catalogue.latest_ids(catalogue.playlist_id(ref))]
            except (YouTubeApiError, runner.YtDlpError) as exc:
                logger.info("Checking %s without the YouTube API, because it could not: %s", url, exc)
        try:
            ref = self._channel_ref(url, None)
            if ref is not None:
                ids = youtube_rss.latest_video_ids(**_feed(ref))
                return [ItemRef(video_id, mapping.video_url(video_id)) for video_id in ids]
        except (youtube_rss.FeedError, runner.YtDlpError) as exc:
            logger.info("Checking %s with yt-dlp, because its RSS feed could not be read: %s", url, exc)
        return self._latest_with_ytdlp(url)

    def newest_episodes(self, url: str) -> list[VideoDetails]:
        """A YouTube collection's 50 newest videos through the API, for 2 units, else its RSS feed's 15,
        else the first 15 of yt-dlp's listing without looking each one up."""
        url = collection_url(url)
        if mapping.youtube_ref(url) is not None:
            catalogue = self._catalogue(adding=False)
            if catalogue is not None:
                try:
                    ref = self._channel_ref(url, catalogue)
                    if ref is not None:
                        ids = catalogue.latest_ids(catalogue.playlist_id(ref))
                        return list(self._details_from_api(catalogue, ids))
                except (YouTubeApiError, runner.YtDlpError) as exc:
                    logger.info("Reading the newest videos of %s without the YouTube API, because it could not: %s", url, exc)
            try:
                ref = self._channel_ref(url, None)
                if ref is not None:
                    return youtube_rss.latest_videos(**_feed(ref))
            except (youtube_rss.FeedError, runner.YtDlpError) as exc:
                logger.info("Reading the newest videos of %s with yt-dlp, because its RSS feed could not be read: %s", url, exc)
        listing = runner.run_json(
            "--flat-playlist", "--playlist-items", f"1:{_LATEST_COUNT}", _listing_urls(url)[0], cookies=sites.cookies_for(url),
        )
        return [
            self._video(entry, entry.get("url") or entry.get("webpage_url"))
            for entry in listing.get("entries") or []
            if isinstance(entry, dict) and entry.get("id") and (entry.get("url") or entry.get("webpage_url"))
            and entry.get("title") not in _UNAVAILABLE_TITLES
        ]

    def _latest_with_ytdlp(self, url: str) -> list[ItemRef]:
        items: dict[str, ItemRef] = {}
        for index, listing_url in enumerate(_listing_urls(url)):
            try:
                listing = runner.run_json(
                    "--flat-playlist", "--playlist-items", f"1:{_LATEST_COUNT}", listing_url, cookies=sites.cookies_for(listing_url),
                )
            except runner.YtDlpError as exc:
                if index == 0:
                    raise
                logger.info("Not checking %s: %s", listing_url, exc)
                continue
            for entry in listing.get("entries") or []:
                entry_url = isinstance(entry, dict) and (entry.get("url") or entry.get("webpage_url"))
                if entry_url and entry.get("id") and entry.get("title") not in _UNAVAILABLE_TITLES:
                    items.setdefault(video_slug(entry), ItemRef(video_slug(entry), entry_url))
        return list(items.values())

    def item_details(self, items: Sequence[ItemRef]) -> dict[str, VideoDetails | None]:
        details: dict[str, VideoDetails | None] = {item.slug: None for item in items}
        youtube = [item for item in items if _is_youtube(item.url)]
        catalogue = self._catalogue(adding=False) if youtube else None
        others = [item for item in items if item not in youtube] if catalogue is not None else list(items)
        if catalogue is not None:
            for video in self._details_from_api(catalogue, [item.slug for item in youtube]):
                details[video.slug] = video
        for item in others:
            details[item.slug] = self._look_up(item.url)
        return details

    def refresh_items(self, url: str, items: Sequence[ItemRef]) -> ItemRefresh:
        """YouTube videos through the API, 50 a unit; the rest, or a batch the API could not answer, from yt-dlp's listing.

        A video the API leaves out may be gone, and yt-dlp is asked whether it is
        (see ``_missing_from_api``). A video missing from yt-dlp's listing may
        just be on a tab or page it did not list, so it stays as it is.

        The API cannot tell a members-only video, so the listing is read for
        those too: it marks the videos only members or paying subscribers can
        watch, and a video it marks keeps that access in the API's details.
        """
        details: dict[str, VideoDetails] = {}
        missing: list[ItemRef] = []
        listing, listed_open = self._refresh_from_listing(url, frozenset(item.slug for item in items))
        youtube = [item.slug for item in items if _is_youtube(item.url)]
        catalogue = self._catalogue(adding=False) if youtube else None
        listed = [item.slug for item in items] if catalogue is None else [item.slug for item in items if not _is_youtube(item.url)]
        if catalogue is not None:
            for start in range(0, len(youtube), MAX_RESULTS):
                batch = youtube[start:start + MAX_RESULTS]
                try:
                    found = {item["id"]: item for item in catalogue.videos(batch)}
                except YouTubeApiError as exc:
                    logger.info("Refreshing %d videos with yt-dlp, because the YouTube API could not: %s", len(batch), exc)
                    listed += batch
                    continue
                for video_id in batch:
                    if video_id in found:
                        details[video_id] = mapping.video(found[video_id], short=False)
                        if (listed_video := listing.get(video_id)) is not None and listed_video.access is not None:
                            details[video_id] = replace(details[video_id], access=listed_video.access)
                    else:
                        missing.append(ItemRef(video_id, mapping.video_url(video_id)))
        details.update((slug, listing[slug]) for slug in listed if slug in listing)
        checked = self._missing_from_api(missing)
        return ItemRefresh(
            details=details | checked.details, removed=checked.removed, refused=checked.refused,
            open=listed_open | checked.open,
        )

    def _missing_from_api(self, items: Sequence[ItemRef]) -> ItemRefresh:
        """What yt-dlp says about videos the YouTube API left out of its answer.

        The API leaves deleted and private videos out, but not only those: it may
        also keep back what only a channel's members can watch. So a video is only
        gone when yt-dlp says so too. A video yt-dlp refuses for lack of a
        membership is refused, and one it can look up is still there.
        """
        details: dict[str, VideoDetails] = {}
        removed: set[str] = set()
        refused: dict[str, str] = {}
        for ref in items:
            try:
                details[ref.slug] = self._video(self._pending_info(ref.url), ref.url)
            except runner.YtDlpError as exc:
                if is_gone_message(str(exc)):
                    removed.add(ref.slug)
                elif (key := self.refused_access(str(exc))) is not None:
                    refused[ref.slug] = key
                else:
                    logger.info("Could not check %s, which the YouTube API left out: %s", ref.url, exc)
        return ItemRefresh(
            details=details, removed=frozenset(removed), refused=refused,
            open=frozenset(slug for slug, found in details.items() if found.access is None),
        )

    def refresh_metadata(self, items: Sequence[ItemRef]) -> ItemRefresh:
        """YouTube videos through the API, 50 a unit; the rest, or a batch the API could not answer, one by one with yt-dlp.

        A video the API leaves out may be gone, and yt-dlp is asked whether it is
        (see ``_missing_from_api``). Any other yt-dlp lookup that fails may just have
        been refused this time, so the video stays as it is, unless yt-dlp says it is
        for members.

        The API cannot tell a members-only video, so a video it answered is looked
        up with yt-dlp as well, for the access it needs.
        """
        details: dict[str, VideoDetails] = {}
        missing: list[ItemRef] = []
        refused: dict[str, str] = {}
        # What yt-dlp could look up and says needs no access.
        looked_open: set[str] = set()
        youtube = [item for item in items if _is_youtube(item.url)]
        catalogue = self._catalogue(adding=False) if youtube else None
        looked_up = [item for item in items if catalogue is None or item not in youtube]
        if catalogue is not None:
            for start in range(0, len(youtube), MAX_RESULTS):
                batch = youtube[start:start + MAX_RESULTS]
                try:
                    found = {item["id"]: item for item in catalogue.videos([ref.slug for ref in batch])}
                except YouTubeApiError as exc:
                    logger.info("Refreshing %d videos with yt-dlp, because the YouTube API could not: %s", len(batch), exc)
                    looked_up += batch
                    continue
                for ref in batch:
                    item = found.get(ref.slug)
                    if item is None:
                        missing.append(ref)
                    elif not mapping.is_pending(item):
                        details[ref.slug] = mapping.video(item, short=False)
                        try:
                            access = _access(self._pending_info(ref.url))
                        except runner.YtDlpError as exc:
                            if (key := self.refused_access(str(exc))) is not None:
                                refused[ref.slug] = key
                            continue
                        if access is not None:
                            details[ref.slug] = replace(details[ref.slug], access=access)
                        else:
                            looked_open.add(ref.slug)
        for ref in looked_up:
            try:
                details[ref.slug] = self._video(self._pending_info(ref.url), ref.url)
                if details[ref.slug].access is None:
                    looked_open.add(ref.slug)
            except runner.YtDlpError as exc:
                if (key := self.refused_access(str(exc))) is not None:
                    refused[ref.slug] = key
                else:
                    logger.info("Skipping %s for now: %s", ref.url, exc)
        checked = self._missing_from_api(missing)
        return ItemRefresh(
            details=details | checked.details, removed=checked.removed, refused=refused | checked.refused,
            open=frozenset(looked_open) | checked.open,
        )

    def _refresh_from_listing(self, url: str, wanted: frozenset[str]) -> tuple[dict[str, VideoDetails], frozenset[str]]:
        """Titles from the collection's flat listing, which takes one request a page instead of one a video.

        The listing has no reliable description or picture, so those are kept. It
        has the length of most YouTube videos, the uploader when the site says, and
        the badge YouTube shows on a video only members or paying subscribers can watch.
        Returns those details, and which of the videos the listing says are open.
        """
        details: dict[str, VideoDetails] = {}
        listed_open: set[str] = set()
        for listing_url in _listing_urls(url):
            try:
                listing = runner.run_json("--flat-playlist", listing_url, cookies=sites.cookies_for(listing_url))
            except runner.YtDlpError as exc:
                logger.info("Not refreshing from %s: %s", listing_url, exc)
                continue
            for entry in listing.get("entries") or []:
                if not isinstance(entry, dict) or not entry.get("id") or not entry.get("title"):
                    continue
                slug = video_slug(entry)
                entry_url = entry.get("url") or entry.get("webpage_url")
                if slug in wanted and entry_url and entry["title"] not in _UNAVAILABLE_TITLES:
                    duration = entry.get("duration")
                    details.setdefault(slug, VideoDetails(
                        slug=slug, url=entry_url, title=entry["title"], description=entry.get("description") or None,
                        duration=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
                        author_name=entry.get("uploader") or entry.get("channel") or None,
                        access=_access(entry),
                    ))
                    if _listed_open(entry):
                        listed_open.add(slug)
        return details, frozenset(listed_open)

    def search(self, query: str) -> SearchResults:
        """YouTube through the API while the search share has room, else through yt-dlp."""
        query = " ".join(query.split())
        if not query:
            return SearchResults([])
        key = query.casefold()
        now = time.monotonic()
        with self._cache_lock:
            cached = self._searches.get(key)
        if cached is not None and now - cached[0] < _SEARCH_CACHE_SECONDS:
            return cached[1]
        answer = self._search(query)
        with self._cache_lock:
            self._searches = {k: v for k, v in self._searches.items() if now - v[0] < _SEARCH_CACHE_SECONDS}
            self._searches[key] = (now, answer)
        return answer

    def _search(self, query: str) -> SearchResults:
        key = api_key.load()
        if key is None:
            reason = "no_key"
        elif quota.status().usage(Share.SEARCH).limit == 0:
            reason = "off"
        else:
            try:
                catalogue = Catalogue(YouTubeApiClient(key), (Share.SEARCH,))
                return SearchResults(youtube_search.search_api(catalogue, query), youtube_search.api_notice())
            except QuotaExceededError as exc:
                logger.info("Searching YouTube with yt-dlp, because the API quota is used up: %s", exc)
                reason = "quota"
            except YouTubeApiError as exc:
                logger.info("Searching YouTube with yt-dlp, because the API could not: %s", exc)
                reason = "error"
        return SearchResults(youtube_search.search_ytdlp(query), youtube_search.ytdlp_notice(reason))

    def quick_check_minutes(self, collections: Sequence[tuple[str, int]]) -> int:
        """With a key, as often as the checks share allows after the daily re-scan; RSS needs no quota."""
        settings = get_settings().youtube_api
        counts = [count for url, count in collections if _is_youtube(url)]
        if api_key.load() is None:
            return settings.min_check_interval_minutes
        interval = quota.check_interval_minutes(
            len(counts), quota.rescan_units(counts), settings.checks_quota, settings.min_check_interval_minutes,
        )
        return interval or settings.min_check_interval_minutes

    def video_playback(self, *, slug: str, url: str, use_cookies: bool = True) -> Playback:
        return Playback(url=url, kind=PlaybackKind.YTDLP, command=runner.command(cookies=sites.cookies_for(url, use_cookies)))

    def media_stream(self, url: str, *, audio: bool, use_cookies: bool = True) -> MediaStream | None:
        if not self.site_for(url).streams:
            raise NotImplementedError(f"{self.site_for(url).name} cannot stream episodes")
        return stream_of(runner.run_json("--no-playlist", url, cookies=sites.cookies_for(url, use_cookies)), audio=audio)

    def live_stream(self, url: str, *, use_cookies: bool = True) -> LiveStream | None:
        site = self.site_for(url)
        if StreamMethod.LIVE not in site.stream_methods:
            raise NotImplementedError(f"{site.name} cannot stream live episodes")
        return live_of(runner.run_json("--no-playlist", url, cookies=sites.cookies_for(url, use_cookies)), site.stream_video_heights)

    def media_tracks(self, url: str, *, use_cookies: bool = True) -> MediaTracks | None:
        site = self.site_for(url)
        if StreamMethod.HLS not in site.stream_methods:
            raise NotImplementedError(f"{site.name} cannot stream episodes as tracks")
        return tracks_of(runner.run_json("--no-playlist", url, cookies=sites.cookies_for(url, use_cookies)), site.stream_video_heights)

    def needs_cookies(self, error: str) -> bool:
        text = error.lower()
        return any(sign in text for sign in _SIGN_IN_ERRORS)

    def refused_access(self, error: str) -> str | None:
        text = error.lower()
        return sites.MEMBERS_KEY if any(sign in text for sign in _MEMBERS_ERRORS) else None

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

    def api_status(self, collections: Sequence[tuple[str, int]] = ()) -> ApiStatus:
        key = api_key.load()
        counts = [count for url, count in collections if on_domain(link_host(url), "youtube.com")]
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
            collection_count=len(counts),
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
