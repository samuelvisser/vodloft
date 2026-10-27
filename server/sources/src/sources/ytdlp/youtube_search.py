"""Search YouTube: through the YouTube Data API when there is a key and search quota, through yt-dlp otherwise.

Both paths give the same results, so the search page does not care which one
answered; the notice above the results says which one did, and why.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote_plus

from ..contract import LinkKind, ResolvedLink, SearchNotice
from .. import ytdlp_runner as runner
from .youtube_api import mapping, quota
from .youtube_api.catalogue import Catalogue
from .youtube_api.quota import Share

logger = logging.getLogger(__name__)

SEARCH_UNITS = 102
"""One search call, plus a batch of channel details and one of video details."""
_YTDLP_VIDEOS = 20
_YTDLP_CHANNELS = 5
_YTDLP_PLAYLISTS = 5
# YouTube's own "channels only" and "playlists only" search filters, encoded the way its own links are.
_CHANNELS_FILTER = "EgIQAg%253D%253D"
_PLAYLISTS_FILTER = "EgIQAw%253D%253D"
SETTINGS_PATH = "/settings?tab=sources"


def _count(value) -> str | None:
    """18100000 as 18.1M, 2400 as 2.4K."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if number >= size:
            return f"{number / size:.1f}".removesuffix(".0") + suffix
    return str(number)


def _plural(value, word: str) -> str | None:
    count = _count(value)
    if count is None:
        return None
    return f"{count} {word}" if count == "1" else f"{count} {word}s"


def _length(seconds: float | None) -> str | None:
    if not seconds:
        return None
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _date(value: datetime | None) -> str | None:
    return f"{value.day} {value:%b %Y}" if value else None


def _facts(*facts: str | None) -> tuple[str, ...]:
    return tuple(fact for fact in facts if fact)


# ---- The YouTube Data API ----

def _api_channel(item: dict, channel: dict | None) -> ResolvedLink:
    snippet = item.get("snippet") or {}
    channel_id = item["id"]["channelId"]
    stats = (channel or {}).get("statistics") or {}
    subscribers = None if stats.get("hiddenSubscriberCount") else _plural(stats.get("subscriberCount"), "subscriber")
    return ResolvedLink(
        kind=LinkKind.SHOW, slug=channel_id, url=mapping.channel_url(channel_id),
        title=snippet.get("channelTitle") or snippet.get("title") or channel_id,
        description=snippet.get("description") or None, image_url=mapping.thumbnail(snippet.get("thumbnails")),
        site="YouTube", kind_label="Channel", facts=_facts(subscribers, _plural(stats.get("videoCount"), "video")),
    )


def _api_playlist(item: dict, playlist: dict | None) -> ResolvedLink:
    snippet = item.get("snippet") or {}
    playlist_id = item["id"]["playlistId"]
    count = ((playlist or {}).get("contentDetails") or {}).get("itemCount")
    return ResolvedLink(
        kind=LinkKind.SHOW, slug=playlist_id, url=f"https://www.youtube.com/playlist?list={playlist_id}",
        title=snippet.get("title") or playlist_id, description=snippet.get("description") or None,
        image_url=mapping.thumbnail(snippet.get("thumbnails")), author_name=snippet.get("channelTitle"),
        site="YouTube", kind_label="Playlist", facts=_facts(_plural(count, "video")),
    )


def _api_video(item: dict, video: dict | None) -> ResolvedLink:
    snippet = item.get("snippet") or {}
    video_id = item["id"]["videoId"]
    if video is not None and mapping.is_pending(video):
        when = "Live now" if (video.get("snippet") or {}).get("liveBroadcastContent") == "live" else "Upcoming"
        facts = _facts(when)
    elif video is not None:
        facts = _facts(_length(mapping.duration((video.get("contentDetails") or {}).get("duration"))),
                       _date(mapping.published_at(video)))
    else:
        facts = _facts(_date(mapping.published_at(item)))
    return ResolvedLink(
        kind=LinkKind.VIDEO, slug=video_id, url=mapping.video_url(video_id),
        title=snippet.get("title") or video_id, description=snippet.get("description") or None,
        image_url=mapping.thumbnail(snippet.get("thumbnails")), author_name=snippet.get("channelTitle"),
        site="YouTube", kind_label="Video", facts=facts,
    )


def search_api(catalogue: Catalogue, query: str) -> list[ResolvedLink]:
    """search.list, then the details that make the cards useful. A failed detail call only costs the facts."""
    items = [item for item in catalogue.search(query) if isinstance(item.get("id"), dict)]
    ids = {kind: [item["id"][key] for item in items if item["id"].get(key)]
           for kind, key in (("channel", "channelId"), ("playlist", "playlistId"), ("video", "videoId"))}
    details: dict[str, dict] = {}
    for kind, lookup in (("channel", catalogue.channels), ("playlist", catalogue.playlists), ("video", catalogue.videos)):
        if not ids[kind]:
            continue
        try:
            details |= {found["id"]: found for found in lookup(ids[kind])}
        except Exception as exc:  # noqa: BLE001 - the search itself already answered
            logger.info("Showing YouTube %s results without details: %s", kind, exc)
    results = []
    for item in items:
        key = item["id"]
        if key.get("channelId") and not key.get("videoId") and not key.get("playlistId"):
            results.append(_api_channel(item, details.get(key["channelId"])))
        elif key.get("playlistId"):
            results.append(_api_playlist(item, details.get(key["playlistId"])))
        elif key.get("videoId"):
            results.append(_api_video(item, details.get(key["videoId"])))
    return results


def api_notice() -> SearchNotice:
    usage = quota.status().usage(Share.SEARCH)
    left = max(usage.limit - usage.used, 0) // SEARCH_UNITS
    return SearchNotice(
        badge="Search via YouTube API",
        text=f"About {left} API {'search' if left == 1 else 'searches'} left today",
    )


# ---- yt-dlp ----

def _image(entry: dict) -> str | None:
    thumbnails = [t for t in entry.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    if not thumbnails:
        return entry.get("thumbnail")
    url = thumbnails[-1]["url"]
    # Channel avatars come without a scheme.
    return f"https:{url}" if url.startswith("//") else url


def _ytdlp_channel(entry: dict) -> ResolvedLink | None:
    channel_id = entry.get("channel_id") or entry.get("id")
    if not isinstance(channel_id, str) or not channel_id.startswith("UC"):
        return None
    return ResolvedLink(
        kind=LinkKind.SHOW, slug=channel_id, url=mapping.channel_url(channel_id),
        title=entry.get("title") or entry.get("channel") or channel_id, description=entry.get("description") or None,
        image_url=_image(entry), site="YouTube", kind_label="Channel",
        facts=_facts(_plural(entry.get("channel_follower_count"), "subscriber"),
                     _plural(entry.get("playlist_count"), "video")),
    )


def _ytdlp_playlist(entry: dict) -> ResolvedLink | None:
    playlist_id = entry.get("id")
    if not isinstance(playlist_id, str) or entry.get("ie_key") != "YoutubeTab" or playlist_id.startswith("UC"):
        return None
    return ResolvedLink(
        kind=LinkKind.SHOW, slug=playlist_id, url=f"https://www.youtube.com/playlist?list={playlist_id}",
        title=entry.get("title") or playlist_id, image_url=_image(entry),
        author_name=entry.get("channel") or entry.get("uploader"), site="YouTube", kind_label="Playlist",
        facts=_facts(_plural(entry.get("playlist_count"), "video")),
    )


def _ytdlp_video(entry: dict) -> ResolvedLink | None:
    video_id = entry.get("id")
    if not isinstance(video_id, str) or entry.get("ie_key") not in (None, "Youtube"):
        return None
    live = entry.get("live_status")
    return ResolvedLink(
        kind=LinkKind.VIDEO, slug=video_id, url=mapping.video_url(video_id),
        title=entry.get("title") or video_id, description=entry.get("description") or None,
        image_url=_image(entry), author_name=entry.get("channel") or entry.get("uploader"),
        site="YouTube", kind_label="Video",
        facts=_facts("Live now" if live == "is_live" else "Upcoming" if live == "is_upcoming" else _length(entry.get("duration"))),
    )


def _entries(*args: str) -> list[dict]:
    return [entry for entry in runner.run_json("--flat-playlist", *args).get("entries") or [] if isinstance(entry, dict)]


def _filtered(query: str, search_filter: str, count: int, to_link) -> list[ResolvedLink]:
    """Channel or playlist results are a bonus: when YouTube's filtered search fails, the videos still answer."""
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={search_filter}"
    try:
        return [link for entry in _entries("--playlist-items", f"1:{count}", url) if (link := to_link(entry))]
    except runner.YtDlpError as exc:
        logger.info("A filtered YouTube search with yt-dlp failed: %s", exc)
        return []


def search_ytdlp(query: str) -> list[ResolvedLink]:
    """yt-dlp's YouTube search: the top channels, playlists and videos, read at the same time."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        channels = pool.submit(_filtered, query, _CHANNELS_FILTER, _YTDLP_CHANNELS, _ytdlp_channel)
        playlists = pool.submit(_filtered, query, _PLAYLISTS_FILTER, _YTDLP_PLAYLISTS, _ytdlp_playlist)
        videos = pool.submit(_entries, f"ytsearch{_YTDLP_VIDEOS}:{query}")
        found = [link for entry in videos.result() if (link := _ytdlp_video(entry))]
        return channels.result() + playlists.result() + found


def ytdlp_notice(reason: str) -> SearchNotice:
    """Why yt-dlp answered: no key, the search share is off or used up, or the API failed."""
    if reason == "no_key":
        return SearchNotice(
            badge="Search via yt-dlp",
            text="No YouTube API key set. A free key makes search faster and adds channel and video details.",
            link_label="Add a free key", link_path=SETTINGS_PATH,
        )
    if reason == "off":
        return SearchNotice(
            badge="Search via yt-dlp",
            text="Search through the YouTube API is turned off: its share of the daily quota is 0.",
            link_label="Change the split", link_path=SETTINGS_PATH,
        )
    if reason == "quota":
        return SearchNotice(
            badge="Slower search via yt-dlp", tone="warning",
            text="Today's YouTube API search quota is used up, so VODLoft searched with yt-dlp. Results take longer "
                 "and have fewer details. API search is back after Google's daily reset.",
        )
    return SearchNotice(
        badge="Slower search via yt-dlp", tone="warning",
        text="The YouTube API could not answer this search, so VODLoft searched with yt-dlp. Results take longer "
             "and have fewer details.",
    )
