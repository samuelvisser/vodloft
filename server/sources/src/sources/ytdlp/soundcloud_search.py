"""Search SoundCloud: its accounts, albums, playlists and tracks, through yt-dlp's own access to SoundCloud.

SoundCloud's website searches through its web API, which yt-dlp also downloads with. yt-dlp's SoundCloud extractor
keeps the key that API takes, so VODLoft asks the API through it and needs no key of its own. The API is not
documented and may change: when it fails, yt-dlp's track search answers instead, with the accounts that made the
tracks it finds listed first.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..contract import LinkKind, ResolvedLink, SearchNotice, SearchResults
from .. import ytdlp_runner as runner
from ..cookies import site_cookies
from .search_facts import date, facts, length, plural

logger = logging.getLogger(__name__)

_SITE = "soundcloud"
"""The Site key of SoundCloud, whose cookies file searches sign in with."""
_TRACKS = 20
_ACCOUNTS = 5
_LISTS = 5
# SoundCloud's own square artwork, the largest that is not the uploaded original.
_ARTWORK = "t500x500"


def _artwork(entry: dict) -> str | None:
    thumbnails = [t for t in entry.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    wanted = next((t["url"] for t in thumbnails if t.get("id") == _ARTWORK), None)
    return wanted or (thumbnails[-1]["url"] if thumbnails else entry.get("thumbnail"))


def _released(entry: dict) -> datetime | None:
    stamp = entry.get("release_timestamp") or entry.get("timestamp")
    return datetime.fromtimestamp(stamp, timezone.utc) if isinstance(stamp, (int, float)) else None


def _track(entry: dict) -> ResolvedLink | None:
    track_id, url = entry.get("id"), entry.get("webpage_url")
    if not track_id or not isinstance(url, str):
        return None
    return ResolvedLink(
        kind=LinkKind.VIDEO, slug=str(track_id), url=url, title=entry.get("title") or str(track_id),
        description=entry.get("description") or None, image_url=_artwork(entry), author_name=entry.get("uploader"),
        site="SoundCloud", kind_label="Track",
        facts=facts(length(entry.get("duration")), date(_released(entry)), plural(entry.get("view_count"), "play")),
    )


def _accounts(entries: list[dict], avatar: Callable[[str], str | None]) -> list[ResolvedLink]:
    """The accounts that made the most of the tracks found, the one with the best match first among equals, with
    their profile pictures."""
    first: dict[str, dict] = {}
    tracks: Counter[str] = Counter()
    for entry in entries:
        url = entry.get("uploader_url")
        if isinstance(url, str) and url.startswith("https://soundcloud.com/"):
            first.setdefault(url, entry)
            tracks[url] += 1
    found = {url: first[url] for url in sorted(first, key=lambda url: -tracks[url])[:_ACCOUNTS]}
    if not found:
        return []
    with ThreadPoolExecutor(max_workers=len(found)) as pool:
        pictures = list(pool.map(avatar, found))
    return [
        ResolvedLink(
            kind=LinkKind.COLLECTION, slug=url.rstrip("/").rsplit("/", 1)[-1], url=url,
            title=entry.get("uploader") or url.rsplit("/", 1)[-1], image_url=picture, site="SoundCloud",
            kind_label="Account", facts=facts(plural(tracks[url], "matching track")),
        )
        for (url, entry), picture in zip(found.items(), pictures)
    ]


# ---- SoundCloud's web API ----

def _api_artwork(url: str | None) -> str | None:
    """SoundCloud's pictures come at 100 pixels wide (``-large``); the same picture is there at 500 too."""
    return url.replace("-large.", f"-{_ARTWORK}.") if url else None


def _api_date(value: str | None) -> str | None:
    try:
        return date(datetime.fromisoformat(value)) if value else None
    except ValueError:
        return None


def _api_account(user: dict) -> ResolvedLink | None:
    url = user.get("permalink_url")
    if not isinstance(url, str):
        return None
    return ResolvedLink(
        kind=LinkKind.COLLECTION, slug=str(user.get("permalink") or url.rstrip("/").rsplit("/", 1)[-1]), url=url,
        title=user.get("username") or url, description=user.get("description") or None,
        image_url=_api_artwork(user.get("avatar_url")), site="SoundCloud", kind_label="Account",
        facts=facts(plural(user.get("followers_count"), "follower"), plural(user.get("track_count"), "track")),
    )


def _api_set(playlist: dict) -> ResolvedLink | None:
    """An album or a playlist. An album says what kind it is, such as an EP."""
    url = playlist.get("permalink_url")
    if not isinstance(url, str):
        return None
    kind = str(playlist.get("set_type") or "")
    label = "EP" if kind == "ep" else kind.capitalize() if kind else "Playlist"
    tracks = playlist.get("tracks") or []
    first = next((track for track in tracks if isinstance(track, dict) and track.get("artwork_url")), {})
    user = playlist.get("user") or {}
    return ResolvedLink(
        kind=LinkKind.COLLECTION, slug=str(playlist.get("id") or url.rsplit("/", 1)[-1]), url=url,
        title=playlist.get("title") or url, description=playlist.get("description") or None,
        image_url=_api_artwork(playlist.get("artwork_url") or first.get("artwork_url") or user.get("avatar_url")),
        author_name=user.get("username"), site="SoundCloud", kind_label=label,
        facts=facts(plural(playlist.get("track_count"), "track"),
                    _api_date(playlist.get("release_date") or playlist.get("display_date"))),
    )


def _api_track(track: dict) -> ResolvedLink | None:
    url = track.get("permalink_url")
    if not isinstance(url, str):
        return None
    duration = track.get("duration")
    return ResolvedLink(
        kind=LinkKind.VIDEO, slug=str(track.get("id") or url.rsplit("/", 1)[-1]), url=url,
        title=track.get("title") or url, description=track.get("description") or None,
        image_url=_api_artwork(track.get("artwork_url") or (track.get("user") or {}).get("avatar_url")),
        author_name=(track.get("user") or {}).get("username"), site="SoundCloud", kind_label="Track",
        facts=facts(length(duration / 1000 if isinstance(duration, (int, float)) else None),
                    _api_date(track.get("display_date") or track.get("created_at")),
                    plural(track.get("playback_count"), "play")),
    )


_API_SEARCHES = (
    ("search/users", _ACCOUNTS, _api_account),
    ("search/albums", _LISTS, _api_set),
    ("search/playlists_without_albums", _LISTS, _api_set),
    ("search/tracks", _TRACKS, _api_track),
)


def _search_api(query: str) -> list[ResolvedLink]:
    """Accounts, albums, playlists and tracks, the way SoundCloud's website searches them, asked through yt-dlp's
    SoundCloud extractor, which keeps the key SoundCloud's web API takes up to date."""
    from yt_dlp import YoutubeDL

    cookies = site_cookies(_SITE)
    options = {"quiet": True, "no_warnings": True, **({"cookiefile": str(cookies)} if cookies else {})}
    results: list[ResolvedLink] = []
    with YoutubeDL(options) as ydl:
        extractor = ydl.get_info_extractor("Soundcloud")
        extractor.initialize()
        for endpoint, limit, to_link in _API_SEARCHES:
            answer = extractor._call_api(
                extractor._API_V2_BASE + endpoint, None, query={"q": query, "limit": limit},
                headers=extractor._HEADERS, note=False,
            )
            found = [item for item in (answer or {}).get("collection") or [] if isinstance(item, dict)]
            results += [link for item in found[:limit] if (link := to_link(item))]
    return results


# ---- yt-dlp's track search ----

def _search_tracks(query: str, avatar: Callable[[str], str | None]) -> list[ResolvedLink]:
    """The accounts behind the best matching tracks, then the tracks. ``avatar`` finds an account's profile picture."""
    listing = runner.run_json("--flat-playlist", f"scsearch{_TRACKS}:{query}", cookies=site_cookies(_SITE))
    entries = [entry for entry in listing.get("entries") or [] if isinstance(entry, dict)]
    return _accounts(entries, avatar) + [link for entry in entries if (link := _track(entry))]


def search(query: str, avatar: Callable[[str], str | None]) -> SearchResults:
    """SoundCloud's own search, or yt-dlp's track search when that fails. ``avatar`` finds an account's profile
    picture for the track search, which does not tell it."""
    try:
        return SearchResults(_search_api(query))
    except Exception as exc:  # noqa: BLE001 - an undocumented API can fail in any way; the track search still answers
        logger.info("Searching SoundCloud's tracks with yt-dlp, because SoundCloud's search could not answer: %s", exc)
    return SearchResults(_search_tracks(query, avatar), SearchNotice(
        badge="Tracks only", tone="warning",
        text="SoundCloud's own search could not answer, so VODLoft searched its tracks with yt-dlp. The accounts "
             "that made them come first; albums and playlists are left out.",
    ))
