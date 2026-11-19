"""Music artists on Bandcamp and SoundCloud as channels: an artist whose sections are their albums."""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

from ..contract import ChannelDetails, SectionKind, SectionRef, SectionRole
from .. import ytdlp_runner as runner
from . import sites, thumbnails

logger = logging.getLogger(__name__)

# SoundCloud's own pages, which are not an artist's.
_SOUNDCLOUD_PAGES = {"discover", "search", "stream", "upload", "you", "charts", "pages", "people", "settings", "messages", "jobs"}
# The pages of an artist's own that list their music, which make adding the artist the obvious choice.
_ARTIST_PAGES = {"", "music", "albums", "sets", "tracks", "popular-tracks"}
# Albums are looked up a few at a time: one lookup per album, as the artist's page only lists their links.
_LOOKUPS_AT_ONCE = 6


def artist_root(url: str) -> str | None:
    """The page of the Bandcamp or SoundCloud artist a link belongs to, or None when it belongs to none."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.endswith(".bandcamp.com") and host.count(".") == 2 and host not in {"www.bandcamp.com", "daily.bandcamp.com"}:
        return f"https://{host}"
    if host in {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}:
        first = next((part for part in parts.path.split("/") if part), "")
        if first and first not in _SOUNDCLOUD_PAGES:
            return f"https://soundcloud.com/{first}"
    return None


def is_artist_page(url: str) -> bool:
    """Whether a link is the artist's own page or its list of music, rather than one album or track."""
    root = artist_root(url)
    if root is None:
        return False
    rest = [part for part in urlsplit(url).path.split("/") if part]
    if "soundcloud.com" in root:
        rest = rest[1:]
    return len(rest) <= 1 and (rest[0] if rest else "") in _ARTIST_PAGES


def artist_details(root: str, progress: Callable[[str], None]) -> ChannelDetails:
    """The artist and their albums. Bandcamp lists albums and loose tracks; SoundCloud lists albums and, as a feed,
    all of the artist's tracks, so the tracks on no album have a place too."""
    bandcamp = "bandcamp.com" in root
    cookies = sites.cookies_for(root)
    progress("Listing the albums")
    listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/music" if bandcamp else f"{root}/albums", cookies=cookies)
    links = [str(entry["url"]) for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("url")]

    def look_up(url: str) -> dict:
        # SoundCloud names an album's cover and release date in its listing; on Bandcamp only its first track does.
        if bandcamp:
            return runner.run_json("--playlist-items", "1", "--ignore-errors", url, cookies=cookies)
        return runner.run_json("--flat-playlist", url, cookies=cookies)

    found: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=_LOOKUPS_AT_ONCE) as pool:
        lookups = {pool.submit(look_up, url): url for url in links}
        for done, lookup in enumerate(as_completed(lookups), start=1):
            progress(f"Reading the albums: {done} of {len(links)}")
            try:
                found[lookups[lookup]] = lookup.result()
            except runner.YtDlpError as exc:
                logger.info("Leaving out %s: %s", lookups[lookup], exc)

    releases = [_release(url, info) for url, info in found.items()]
    releases.sort(key=lambda release: release[0], reverse=True)
    sections = [section for _date, section in releases]
    if not bandcamp:
        sections.append(SectionRef(ref="tracks", url=f"{root}/tracks", title="Tracks", kind=SectionKind.FEED, role=SectionRole.MAIN, kind_label="Feed"))
    name = next(filter(None, (_artist_name(info) for info in found.values())), None)
    handle = root.rstrip("/").rsplit("/", 1)[-1] if not bandcamp else urlsplit(root).hostname.split(".", 1)[0]
    albums = sum(1 for section in sections if section.kind is SectionKind.LIST)
    return ChannelDetails(
        ref=handle, url=root, title=str(name or handle), facts=(f"{albums} {'album' if albums == 1 else 'albums'}",),
        sections=tuple(sections), music=True,
    )


def _artist_name(info: dict) -> str | None:
    """Who made an album or track, as the album or its first track names them."""
    track = next((entry for entry in info.get("entries") or [] if isinstance(entry, dict)), {})
    for source in (info, track):
        for key in ("album_artist", "artist", "uploader"):
            if source.get(key):
                return str(source[key])
    return None


def _release(url: str, info: dict) -> tuple[str, SectionRef]:
    """An album, or a track on its own, with its release date to sort the artist's music by."""
    track = info if info.get("_type") != "playlist" else next(
        (entry for entry in info.get("entries") or [] if isinstance(entry, dict)), {},
    )
    date = str(info.get("release_date") or track.get("release_date") or info.get("upload_date") or track.get("upload_date") or "")
    path = urlsplit(url).path.strip("/")
    image = info.get("thumbnail") or track.get("thumbnail") or next(
        (item.get("url") for item in reversed(info.get("thumbnails") or []) if isinstance(item, dict) and item.get("url")), None,
    )
    year = date[:4] if len(date) >= 4 else None
    if info.get("_type") == "playlist":
        count = info.get("playlist_count")
        return date, SectionRef(
            ref=path, url=url, title=str(info.get("album") or info.get("title") or path), kind=SectionKind.LIST,
            kind_label="Album", item_count=count if isinstance(count, int) else None,
            image_url=thumbnails.widest_still(image) if image else None, description=info.get("description") or None,
            year=year,
        )
    return date, SectionRef(
        ref=path, url=url, title=str(info.get("track") or info.get("title") or path), kind=SectionKind.ITEM, kind_label="Single",
        image_url=thumbnails.widest_still(image) if image else None, year=year,
    )
