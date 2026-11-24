"""How yt-dlp does on Bandcamp and SoundCloud what their contracts say they have: an artist, whose sections are their
albums, or a SoundCloud account, which may be a musician or a podcast, whose sections are its albums and playlists."""
from __future__ import annotations

import html
import json
import logging
import re
from collections import Counter
from dataclasses import replace
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import ClassVar
from urllib.parse import urlsplit, urlunsplit

import requests

from progress_plan import PlanTracker, StageSpec

from ...contract import CollectionDetails, CreatorDetails, SearchResults, SectionKind, SectionRef
from ... import ytdlp_runner as runner
from .. import sites, soundcloud_search, thumbnails
from ..site_contracts.soundcloud import ALBUM_LIST, PLAYLIST_LIST
from .other_sites import OtherSitesImplementation
from sources.ytdlp_options import keep_call_options

logger = logging.getLogger(__name__)

# Albums are looked up a few at a time: one lookup per album, as the artist's page only lists their links.
_LOOKUPS_AT_ONCE = 6
_PAGE_TIMEOUT_SECONDS = 15
_BROWSER = "Mozilla/5.0"
# SoundCloud's own pages.
_HOSTS = frozenset({"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"})
# What yt-dlp adds to the name of a SoundCloud account's page, such as " (All)" or " (Tracks)".
_PAGE_SUFFIX = re.compile(r" \((?:All|Tracks|Albums|Playlists|Reposts|Likes|Spotlight)\)$")
_OG_IMAGE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')
# What SoundCloud's page knows about the account, for its own script.
_HYDRATION = re.compile(r"window\.__sc_hydration\s*=\s*(\[.*?\]);\s*</script>", re.S)


class ArtistImplementation(OtherSitesImplementation):
    """What Bandcamp and SoundCloud share: an artist's page lists their albums, each looked up on its own."""

    music_pages: ClassVar[frozenset[str]]
    """The artist's pages of all their music."""
    single_key: ClassVar[str] = "single"

    def page(self, url: str) -> str | None:
        """Which of the artist's own pages a link is, such as "" for their front page or "music"; None for one album
        or track, or a link of no artist's."""
        root = self.creator_root(url)
        if root is None:
            return None
        rest = _parts(url)[len(_parts(root)):]
        return (rest[0] if rest else "") if len(rest) <= 1 else None

    def is_creator_page(self, url: str) -> bool:
        """The artist's page of all their music."""
        return self.page(url) in self.music_pages

    def is_list(self, url: str) -> bool:
        """One of the artist's albums or sets, rather than one of their pages."""
        return self.creator_root(url) is not None and self.page(url) is None

    def season_lists(self, url: str) -> list[SectionRef]:
        """The artist's albums, or a SoundCloud account's albums and playlists, newest first."""
        root = self.creator_root(url)
        if root is None:
            raise runner.YtDlpError(f"This link is not an artist on {self.site.name}")
        return [section for section in self.creator_details(root, PlanTracker()).sections if section.kind is SectionKind.LIST]

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

    def creator_details(self, root: str, plan: PlanTracker) -> CreatorDetails:
        root = self.creator_root(root) or root
        cookies = sites.cookies_for(root)
        # Named by what the Site calls its lists, such as "albums and playlists" on SoundCloud.
        lists = self.site.section_list_names.plural
        found: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=_LOOKUPS_AT_ONCE, **keep_call_options()) as pool:
            # The artist's feeds and pictures are read beside their lists. The feeds are quick, so their steps come
            # first and the lists, which take longest, last.
            listings = self.read_feeds(root, pool, plan)
            pictures = pool.submit(self.pictures, root)
            plan.add(
                StageSpec(id="list", code="list_lists", label=f"Listing the {lists}"),
                StageSpec(id="read", code="read_lists", label=f"Reading the {lists}"),
            )
            with plan.running("list"):
                links = self.release_links(root)
                key_of = self.list_key(root, cookies)
            with plan.running("read"):
                plan.progress("read", 0.0, done=0, total=len(links))
                lookups = {pool.submit(self.look_up, url, cookies): url for url in links}
                for done, lookup in enumerate(as_completed(lookups), start=1):
                    plan.progress("read", done / len(links), done=done, total=len(links))
                    try:
                        found[lookups[lookup]] = lookup.result()
                    except runner.YtDlpError as exc:
                        logger.info("Leaving out %s: %s", lookups[lookup], exc)
            releases = [self._release(url, info, key_of(url)) for url, info in found.items()]
            releases.sort(key=lambda release: release[0], reverse=True)
            sections = [section for _date, section in releases]
            sections += self.feed_sections(root, listings)
        name = next(filter(None, (_artist_name(info) for info in found.values())), None)
        handle = self.handle(root)
        # How many of each type of list the artist has, in the Site's words, such as "2 albums" and "1 playlist".
        counts = Counter(section.type for section in sections if section.kind is SectionKind.LIST)
        # Listed in the Site's order of its list types, not in the order the lookups happened to finish.
        facts = tuple(f"{counts[type_]} {type_.names.singular if counts[type_] == 1 else type_.names.plural}"
                      for type_ in self.site.types_of(SectionKind.LIST) if counts[type_])
        avatar, banner = pictures.result()
        return CreatorDetails(
            ref=handle, url=root, title=str(name or handle), avatar_url=avatar, banner_url=banner,
            facts=facts or (f"0 {self.site.types_of(SectionKind.LIST)[0].names.plural}",),
            sections=tuple(sections), **self.music(sections),
        )

    def handle(self, root: str) -> str:
        raise NotImplementedError

    def pictures(self, root: str) -> tuple[str | None, str | None]:
        """The artist's picture and banner, where the Site shows ones that yt-dlp does not give."""
        return None, None

    def complete_collection(self, details: CollectionDetails, url: str) -> CollectionDetails:
        """A collection of all the artist's music is pictured by the artist's picture, which yt-dlp leaves out."""
        root = self.creator_root(url)
        if details.image_url is None and root and self.is_creator_page(url):
            return replace(details, image_url=self.pictures(root)[0])
        return details

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
        with ThreadPoolExecutor(max_workers=_LOOKUPS_AT_ONCE, **keep_call_options()) as pool:
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

    def shared_page(self, url: str) -> str:
        """SoundCloud's share links lead to the page with tracking parameters only, which are left out."""
        return urlunsplit(urlsplit(url)._replace(query="", fragment=""))

    def search(self, query: str) -> SearchResults:
        return soundcloud_search.search(query, self.avatar)

    def creator_root(self, url: str) -> str | None:
        parts = urlsplit(url)
        if (parts.hostname or "").lower() in _HOSTS:
            first = next((part for part in parts.path.split("/") if part), "")
            if first and first not in self._own_pages:
                return f"https://soundcloud.com/{first}"
        return None

    def handle(self, root: str) -> str:
        return root.rstrip("/").rsplit("/", 1)[-1]

    def avatar(self, root: str) -> str | None:
        return self.pictures(root)[0]

    def complete_collection(self, details: CollectionDetails, url: str) -> CollectionDetails:
        """yt-dlp names an account's page after the account and the page, such as "Flume (All)" or "Flume (Tracks)";
        the collection is the account's, so it takes the account's own name."""
        details = super().complete_collection(details, url)
        if not self.is_creator_page(url):
            return details
        name = _PAGE_SUFFIX.sub("", details.title)
        return replace(details, title=name, author_name=details.author_name or name)

    def list_type(self, info: dict, url: str) -> str | None:
        """A set is an album when SoundCloud gives it a type of release, such as an album, an EP or a single, which
        yt-dlp calls its album type; a playlist has none, which yt-dlp calls a playlist."""
        if not self.is_list(url):
            return None
        return PLAYLIST_LIST if info.get("album_type") in (None, "", "playlist") else ALBUM_LIST

    def pictures(self, root: str) -> tuple[str | None, str | None]:
        """The account's profile picture and banner, which yt-dlp leaves out. Its page shares the picture as its
        og:image, and gives its own script the banner, which SoundCloud calls the account's visual."""
        try:
            response = requests.get(root, headers={"User-Agent": _BROWSER}, timeout=_PAGE_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.info("No pictures for %s: %s", root, exc)
            return None, None
        found = _OG_IMAGE.search(response.text)
        return (html.unescape(found.group(1)) if found else None), _visual(response.text)

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


def _visual(page: str) -> str | None:
    """The banner of the account a SoundCloud page is, from what the page gives its own script."""
    found = _HYDRATION.search(page)
    try:
        hydration = json.loads(found.group(1)) if found else []
    except ValueError:
        return None
    user = next((item.get("data") for item in hydration if isinstance(item, dict) and item.get("hydratable") == "user"), None)
    visuals = ((user or {}).get("visuals") or {}).get("visuals") or [] if isinstance(user, dict) else []
    return next((str(visual["visual_url"]) for visual in visuals if isinstance(visual, dict) and visual.get("visual_url")), None)


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
