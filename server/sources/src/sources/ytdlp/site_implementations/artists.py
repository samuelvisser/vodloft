"""How yt-dlp does on Bandcamp and SoundCloud what their contracts say they have: an artist, whose sections are their
albums, or a SoundCloud account, which may be a musician or a podcast, whose sections are its albums and playlists."""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import ClassVar
from urllib.parse import urlsplit

from ...contract import CreatorDetails, SectionKind, SectionRef
from ... import ytdlp_runner as runner
from .. import sites, thumbnails
from ..site_contracts.soundcloud import ALBUM_LIST, PLAYLIST_LIST
from .other_sites import OtherSitesImplementation

logger = logging.getLogger(__name__)

# Albums are looked up a few at a time: one lookup per album, as the artist's page only lists their links.
_LOOKUPS_AT_ONCE = 6


class ArtistImplementation(OtherSitesImplementation):
    """What Bandcamp and SoundCloud share: an artist's page lists their albums, each looked up on its own."""

    music_pages: ClassVar[frozenset[str]]
    """The artist's pages of all their music."""
    artist_pages: ClassVar[frozenset[str]] = frozenset({"", "music", "albums", "sets", "tracks", "popular-tracks"})
    """The artist's pages that list their music, which make adding the artist the obvious choice."""
    single_key: ClassVar[str] = "single"

    def page(self, url: str) -> str | None:
        """Which of the artist's own pages a link is, such as "" for their front page or "music"; None for one album
        or track, or a link of no artist's."""
        root = self.creator_root(url)
        if root is None:
            return None
        rest = _parts(url)[len(_parts(root)):]
        return (rest[0] if rest else "") if len(rest) <= 1 else None

    def creator_page(self, url: str) -> str | None:
        return self.creator_root(url) if self.page(url) in self.artist_pages else None

    def is_creator_page(self, url: str) -> bool:
        """The artist's page of all their music."""
        return self.page(url) in self.music_pages

    def season_lists(self, url: str) -> list[SectionRef]:
        """The artist's albums, or a SoundCloud account's albums and playlists, newest first."""
        root = self.creator_root(url)
        if root is None:
            raise runner.YtDlpError(f"This link is not an artist on {self.site.name}")
        return [section for section in self.creator_details(root, lambda step: None).sections if section.kind is SectionKind.LIST]

    def all_music(self, url: str, newest_albums: int | None = None) -> list[dict] | None:
        return self.tracks(self.creator_root(url), newest_albums) if self.is_creator_page(url) else None

    def tracks(self, root: str, newest_albums: int | None) -> list[dict]:
        raise NotImplementedError

    def release_links(self, root: str) -> list[str]:
        """The links of the artist's albums, and of their tracks on none where the page lists them."""
        raise NotImplementedError

    def look_up(self, url: str, cookies) -> dict:
        return runner.run_json("--flat-playlist", url, cookies=cookies)

    def list_key(self, root: str, cookies) -> Callable[[str], str]:
        """Which of the Site's types of list each album link is."""
        raise NotImplementedError

    def creator_details(self, root: str, progress: Callable[[str], None]) -> CreatorDetails:
        root = self.creator_root(root) or root
        cookies = sites.cookies_for(root)
        progress("Listing the albums")
        links = self.release_links(root)
        found: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=_LOOKUPS_AT_ONCE) as pool:
            lookups = {pool.submit(self.look_up, url, cookies): url for url in links}
            for done, lookup in enumerate(as_completed(lookups), start=1):
                progress(f"Reading the albums: {done} of {len(links)}")
                try:
                    found[lookups[lookup]] = lookup.result()
                except runner.YtDlpError as exc:
                    logger.info("Leaving out %s: %s", lookups[lookup], exc)
            key_of = self.list_key(root, cookies)
            releases = [self._release(url, info, key_of(url)) for url, info in found.items()]
            releases.sort(key=lambda release: release[0], reverse=True)
            sections = [section for _date, section in releases]
            sections += self.feed_sections(root, self.read_feeds(root, pool))
        name = next(filter(None, (_artist_name(info) for info in found.values())), None)
        handle = self.handle(root)
        # How many of each type of list the artist has, in the Site's words, such as "2 albums" and "1 playlist".
        counts = Counter(section.type for section in sections if section.kind is SectionKind.LIST)
        facts = tuple(f"{count} {type_.names.singular if count == 1 else type_.names.plural}" for type_, count in counts.items())
        return CreatorDetails(
            ref=handle, url=root, title=str(name or handle),
            facts=facts or (f"0 {self.site.types_of(SectionKind.LIST)[0].names.plural}",),
            sections=tuple(sections), **self.music(sections),
        )

    def handle(self, root: str) -> str:
        raise NotImplementedError

    def music(self, sections: list[SectionRef]) -> dict:
        """Whether the creator is a music artist, and how sure the Site is."""
        raise NotImplementedError

    def _release(self, url: str, info: dict, list_key: str) -> tuple[str, SectionRef]:
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
        image_url = thumbnails.widest_still(image) if image else None
        if info.get("_type") == "playlist":
            count = info.get("playlist_count")
            return date, self.section(
                path, url, list_key, title=str(info.get("album") or info.get("title") or path),
                item_count=count if isinstance(count, int) else None, image_url=image_url,
                description=info.get("description") or None, year=year,
            )
        return date, self.section(path, url, self.single_key, title=str(info.get("track") or info.get("title") or path),
                                  image_url=image_url, year=year)


class BandcampImplementation(ArtistImplementation):
    """A Bandcamp artist lists albums and loose tracks; everything they have is music."""

    key = "bandcamp"
    list_keys = frozenset({"album", "single"})
    music_pages = frozenset({"", "music"})

    def creator_root(self, url: str) -> str | None:
        host = (urlsplit(url).hostname or "").lower()
        if host.endswith(".bandcamp.com") and host.count(".") == 2 and host not in {"www.bandcamp.com", "daily.bandcamp.com"}:
            return f"https://{host}"
        return None

    def handle(self, root: str) -> str:
        return urlsplit(root).hostname.split(".", 1)[0]

    def release_links(self, root: str) -> list[str]:
        return self._music_links(root, sites.cookies_for(root))

    def _music_links(self, root: str, cookies) -> list[str]:
        listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/music", cookies=cookies)
        return [str(entry["url"]) for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("url")]

    def look_up(self, url: str, cookies) -> dict:
        # Bandcamp names an album's cover and release date only on its first track.
        return runner.run_json("--playlist-items", "1", "--ignore-errors", url, cookies=cookies)

    def list_key(self, root: str, cookies) -> Callable[[str], str]:
        return lambda link: "album"

    def music(self, sections: list[SectionRef]) -> dict:
        # Bandcamp only has music.
        return {"music": True, "music_known": True}

    def tracks(self, root: str, newest_albums: int | None) -> list[dict]:
        """The tracks of each album and the tracks on none; with ``newest_albums``, only the tracks of that many of
        the newest albums."""
        cookies = sites.cookies_for(root)
        links = self._music_links(root, cookies)
        album_links = [link for link in links if "/album/" in link]
        if newest_albums is not None:
            album_links = album_links[:newest_albums]
        tracks: list[dict] = []
        with ThreadPoolExecutor(max_workers=_LOOKUPS_AT_ONCE) as pool:
            for found in pool.map(lambda link: _album_tracks(link, cookies), album_links):
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


class SoundCloudImplementation(ArtistImplementation):
    """A SoundCloud account lists its sets, which are albums or playlists, and all its tracks as a feed, so the
    tracks on no album have a place too. An account may be a musician's or a podcast's."""

    key = "soundcloud"
    list_keys = frozenset({ALBUM_LIST, PLAYLIST_LIST, "single"})
    music_pages = frozenset({"", "tracks"})
    # SoundCloud's own pages, which are not an artist's.
    _own_pages = frozenset({"discover", "search", "stream", "upload", "you", "charts", "pages", "people", "settings", "messages", "jobs"})

    def creator_root(self, url: str) -> str | None:
        parts = urlsplit(url)
        if (parts.hostname or "").lower() in {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}:
            first = next((part for part in parts.path.split("/") if part), "")
            if first and first not in self._own_pages:
                return f"https://soundcloud.com/{first}"
        return None

    def handle(self, root: str) -> str:
        return root.rstrip("/").rsplit("/", 1)[-1]

    def release_links(self, root: str) -> list[str]:
        listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/sets", cookies=sites.cookies_for(root))
        return [str(entry["url"]) for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("url")]

    def list_key(self, root: str, cookies) -> Callable[[str], str]:
        # SoundCloud keeps an artist's albums apart from their playlists, so an account with albums is an artist's.
        albums = self._album_links(root, cookies)
        return lambda link: ALBUM_LIST if link in albums else PLAYLIST_LIST

    def music(self, sections: list[SectionRef]) -> dict:
        # One without albums may still be an artist's, so the user decides.
        has_albums = any(section.type.key == ALBUM_LIST for section in sections)
        return {"music": has_albums, "music_reason": "It has albums on SoundCloud" if has_albums else None}

    @staticmethod
    def _album_links(root: str, cookies) -> set[str]:
        """The links of an account's albums, which its sets list among its playlists. Artists have them, podcasts
        don't."""
        try:
            listing = runner.run_json("--flat-playlist", f"{root}/albums", cookies=cookies)
        except runner.YtDlpError as exc:
            logger.debug("%s has no albums: %s", root, exc)
            return set()
        return {str(entry["url"]) for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("url")}

    def tracks(self, root: str, newest_albums: int | None) -> list[dict]:
        """Every track on the account's Tracks."""
        listing = runner.run_json("--flat-playlist", f"{root}/tracks", cookies=sites.cookies_for(root))
        return [entry for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("id")]


def _parts(url: str) -> list[str]:
    return [part for part in urlsplit(url).path.split("/") if part]


def _album_tracks(url: str, cookies) -> list[dict]:
    try:
        listing = runner.run_json("--flat-playlist", url, cookies=cookies)
    except runner.YtDlpError as exc:
        logger.info("Leaving out %s: %s", url, exc)
        return []
    return [entry for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("id")]


def _artist_name(info: dict) -> str | None:
    """Who made an album or track, as the album or its first track names them."""
    track = next((entry for entry in info.get("entries") or [] if isinstance(entry, dict)), {})
    for source in (info, track):
        for key in ("album_artist", "artist", "uploader"):
            if source.get(key):
                return str(source[key])
    return None
