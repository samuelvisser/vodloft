"""Bandcamp artists and SoundCloud accounts as creators: an artist whose sections are their albums, or a SoundCloud
account, which may be a musician or a podcast, whose sections are its albums and playlists."""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

from ..contract import CreatorDetails, SectionKind, SectionRef, SectionRole
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


def lists_all_music(url: str) -> bool:
    """Whether a link is the page of all of an artist's music: a Bandcamp artist's page, or a SoundCloud artist's
    page or their Tracks."""
    root = artist_root(url)
    if root is None or not is_artist_page(url):
        return False
    rest = [part for part in urlsplit(url).path.split("/") if part]
    page = (rest[1:] if "soundcloud.com" in root else rest) or [""]
    return page[0] in ({"", "tracks"} if "soundcloud.com" in root else {"", "music"})


def albums(root: str) -> list[SectionRef]:
    """The artist's albums, or a SoundCloud account's albums and playlists, newest first."""
    return [section for section in artist_details(root, lambda step: None).sections if section.kind is SectionKind.LIST]


def all_tracks(url: str, *, newest_albums: int | None = None) -> list[dict]:
    """yt-dlp's flat entries of every track on the artist's page: on Bandcamp the tracks of each album and the tracks
    on none, on SoundCloud their Tracks. With ``newest_albums``, only the tracks of that many of the newest albums."""
    root = artist_root(url)
    cookies = sites.cookies_for(root)
    if "soundcloud.com" in root:
        listing = runner.run_json("--flat-playlist", f"{root}/tracks", cookies=cookies)
        return [entry for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("id")]
    listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/music", cookies=cookies)
    links = [str(entry["url"]) for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("url")]
    album_links = [link for link in links if "/album/" in link]
    if newest_albums is not None:
        album_links = album_links[:newest_albums]
    tracks: list[dict] = []
    with ThreadPoolExecutor(max_workers=_LOOKUPS_AT_ONCE) as pool:
        listings = list(pool.map(lambda link: _album_tracks(link, cookies), album_links))
    for found in listings:
        tracks += found
    # A track on no album is listed by its link alone, so it is looked up for its id.
    for link in (link for link in links if "/track/" in link):
        try:
            info = runner.run_json("--no-playlist", link, cookies=cookies)
        except runner.YtDlpError as exc:
            logger.info("Leaving out %s: %s", link, exc)
            continue
        if info.get("id"):
            tracks.append({"_type": "url", "url": link, "ie_key": "Bandcamp", "id": info["id"], "title": info.get("title")})
    return tracks


def _album_tracks(url: str, cookies) -> list[dict]:
    try:
        listing = runner.run_json("--flat-playlist", url, cookies=cookies)
    except runner.YtDlpError as exc:
        logger.info("Leaving out %s: %s", url, exc)
        return []
    return [entry for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("id")]


def artist_details(root: str, progress: Callable[[str], None]) -> CreatorDetails:
    """The artist and their albums. Bandcamp lists albums and loose tracks; SoundCloud lists albums and, as a feed,
    all of the artist's tracks, so the tracks on no album have a place too."""
    bandcamp = "bandcamp.com" in root
    cookies = sites.cookies_for(root)
    progress("Listing the albums")
    listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/music" if bandcamp else f"{root}/sets", cookies=cookies)
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

    # SoundCloud keeps an artist's albums apart from their playlists, so an account with albums is an artist's. One
    # without may still be, so the user decides.
    album_links = set() if bandcamp else _album_links(root, cookies)
    releases = [_release(url, info, bandcamp, None if bandcamp else sites.ALBUM_LIST if url in album_links else sites.PLAYLIST_LIST)
                for url, info in found.items()]
    releases.sort(key=lambda release: release[0], reverse=True)
    sections = [section for _date, section in releases]
    if not bandcamp:
        sections.append(SectionRef(ref="tracks", url=f"{root}/tracks", title="Tracks", kind=SectionKind.FEED, role=SectionRole.MAIN))
    has_albums = bool(album_links)
    name = next(filter(None, (_artist_name(info) for info in found.values())), None)
    handle = root.rstrip("/").rsplit("/", 1)[-1] if not bandcamp else urlsplit(root).hostname.split(".", 1)[0]
    # How many of each type of list the artist has, in the Site's words, such as "2 albums" and "1 playlist".
    site = sites.site_of("bandcamp" if bandcamp else "soundcloud")
    counts = Counter(site.section_type_of(section) for section in sections if section.kind is SectionKind.LIST)
    facts = tuple(f"{count} {type_.names.one if count == 1 else type_.names.many}" for type_, count in counts.items())
    return CreatorDetails(
        ref=handle, url=root, title=str(name or handle), facts=facts or (f"0 {site.types_of(SectionKind.LIST)[0].names.many}",),
        # Bandcamp only has music; a SoundCloud account may as well be a podcast.
        sections=tuple(sections), music=bandcamp or has_albums, music_known=bandcamp,
        music_reason="It has albums on SoundCloud" if has_albums else None,
    )


def _album_links(root: str, cookies) -> set[str]:
    """The links of a SoundCloud account's albums, which its playlists list among the rest. Artists have them,
    podcasts don't."""
    try:
        listing = runner.run_json("--flat-playlist", f"{root}/albums", cookies=cookies)
    except runner.YtDlpError as exc:
        logger.debug("%s has no albums: %s", root, exc)
        return set()
    return {str(entry["url"]) for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("url")}


def _artist_name(info: dict) -> str | None:
    """Who made an album or track, as the album or its first track names them."""
    track = next((entry for entry in info.get("entries") or [] if isinstance(entry, dict)), {})
    for source in (info, track):
        for key in ("album_artist", "artist", "uploader"):
            if source.get(key):
                return str(source[key])
    return None


def _release(url: str, info: dict, bandcamp: bool = True, list_type: str | None = None) -> tuple[str, SectionRef]:
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
            item_count=count if isinstance(count, int) else None,
            image_url=thumbnails.widest_still(image) if image else None, description=info.get("description") or None,
            year=year, type=list_type,
        )
    return date, SectionRef(
        ref=path, url=url, title=str(info.get("track") or info.get("title") or path), kind=SectionKind.ITEM,
        image_url=thumbnails.widest_still(image) if image else None, year=year,
    )
