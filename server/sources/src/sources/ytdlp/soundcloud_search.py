"""Search SoundCloud through yt-dlp, which finds tracks by name.

yt-dlp searches SoundCloud's tracks only, so the accounts that made the tracks it finds come first, each of which can
be added as a creator. Albums and playlists are added from their account or by link.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..contract import LinkKind, ResolvedLink
from .. import ytdlp_runner as runner
from ..cookies import site_cookies
from .search_facts import date, facts, length, plural

_SITE = "soundcloud"
"""The Site key of SoundCloud, whose cookies file searches sign in with."""
_TRACKS = 20
_ACCOUNTS = 5
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


def search(query: str, avatar: Callable[[str], str | None]) -> list[ResolvedLink]:
    """The accounts behind the best matching tracks, then the tracks. ``avatar`` finds an account's profile picture."""
    listing = runner.run_json("--flat-playlist", f"scsearch{_TRACKS}:{query}", cookies=site_cookies(_SITE))
    entries = [entry for entry in listing.get("entries") or [] if isinstance(entry, dict)]
    return _accounts(entries, avatar) + [link for entry in entries if (link := _track(entry))]
