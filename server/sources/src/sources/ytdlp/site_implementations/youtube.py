"""How yt-dlp does on YouTube what YouTube's contract says it has: a channel, its tabs and its playlists."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit, urlunsplit

from ...contract import LIST_TYPE, MAIN_TAG, CollectionDetails, CreatorDetails, SearchResults, SectionRef, link_host, on_domain
from ... import ytdlp_runner as runner
from .. import sites, thumbnails, youtube_search
from ..youtube_api import QuotaExceededError, Share, YouTubeApiClient, YouTubeApiError, key as api_key, mapping, quota
from ..youtube_api.catalogue import Catalogue
from .other_sites import OtherSitesImplementation
from sources.ytdlp_options import keep_call_options

logger = logging.getLogger(__name__)

_YOUTUBE_CHANNEL = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_CHANNEL_PAGE = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)(?:/(?:videos|shorts|streams|playlists|featured))?/?$")
# A playlist's own picture on YouTube. YouTube serves it only under the signed link it lists it with; yt-dlp adds a
# widest form without the signature, which YouTube answers with a grey placeholder.
_UNSIGNED_PLAYLIST_PICTURE = re.compile(r"^https?://i\d?\.ytimg\.com/s_p/[^?]+$")
_LIVE_STATUSES = {"is_live", "is_upcoming", "was_live", "post_live"}


def collection_url(url: str) -> str:
    """A YouTube channel's link lists its tabs; the collection is its Videos tab."""
    parts = urlsplit(url)
    if on_domain(link_host(url), "youtube.com") and _YOUTUBE_CHANNEL.match(parts.path):
        return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/videos"))
    return url


def channel_root(url: str) -> str | None:
    """A YouTube channel's own link, without a tab, or None when the link is not a channel."""
    parts = urlsplit(url)
    if not on_domain(link_host(url), "youtube.com"):
        return None
    match = _CHANNEL_PAGE.match(parts.path)
    if not match:
        return None
    return urlunsplit(("https", "www.youtube.com", f"/{match.group(1)}", "", ""))


def picture(info: dict) -> str | None:
    """The picture yt-dlp names for a video or playlist, as it names it."""
    if info.get("thumbnail"):
        return info["thumbnail"]
    candidates = [
        t for t in info.get("thumbnails") or []
        if isinstance(t, dict) and t.get("url") and not _UNSIGNED_PLAYLIST_PICTURE.match(t["url"])
    ]
    return candidates[-1]["url"] if candidates else None


def _count(number: int) -> str:
    """A large count the way YouTube shows it, such as 1.2M."""
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if number >= size:
            return f"{number / size:.1f}".rstrip("0").rstrip(".") + suffix
    return str(number)


class YouTubeImplementation(OtherSitesImplementation):
    key = "youtube"
    list_keys = frozenset({LIST_TYPE})

    def search(self, query: str) -> SearchResults:
        """Through the YouTube Data API while the search share has room, else through yt-dlp."""
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

    def collection_link(self, url: str) -> str:
        return collection_url(url)

    def episode_tag(self, info: dict, url: str) -> str:
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

    def creator_root(self, url: str) -> str | None:
        return channel_root(collection_url(url))

    def creator_page(self, url: str) -> str | None:
        # A channel's Videos tab is the whole channel too.
        return channel_root(url) if self.is_creator_page(url) else None

    def is_creator_page(self, url: str) -> bool:
        """A channel's own link or its Videos tab, which stand for all its uploads. Not one playlist, nor only a
        channel's Shorts or Live tab."""
        ref = mapping.youtube_ref(collection_url(url))
        return ref is not None and ref.kind != "playlist" and ref.tab == "videos" and channel_root(collection_url(url)) is not None

    def creator_details(self, ref: str, progress: Callable[[str], None]) -> CreatorDetails:
        """A channel through yt-dlp, which costs no API quota: its details, the feeds it has, and its playlists.
        ``ref`` is the channel's link or its ID.

        Each of the channel's pages is a lookup of its own, of a second or more, so they are all looked up at once."""
        root = channel_root(ref) if ref.startswith("http") else mapping.channel_url(ref)
        if root is None:
            raise runner.YtDlpError("This link is not a YouTube channel")
        progress("Reading the channel, its videos and its playlists")
        main = next(type_ for type_ in self.feed_types if type_.key == "videos")
        with ThreadPoolExecutor(max_workers=len(self.feed_types) + 2, thread_name_prefix="channel-lookup", **keep_call_options()) as pool:
            listings = self.read_feeds(root, pool)
            playlists = pool.submit(self.playlists, root)
            releases = pool.submit(self.has_releases, root)
            info = listings[main.key].result()
            channel_id = str(info.get("channel_id") or "")
            if not channel_id:
                raise runner.YtDlpError("YouTube did not say which channel this is")
            handle = info.get("uploader_id") if str(info.get("uploader_id") or "").startswith("@") else None
            # The handle's link is the one people paste, so a collection added from it before is recognised.
            root = f"https://www.youtube.com/{handle}" if handle else mapping.channel_url(channel_id)
            sections = self.feed_sections(root, listings) + playlists.result()
            has_releases = releases.result()
        pictures = {str(item.get("id")): item.get("url") for item in info.get("thumbnails") or [] if isinstance(item, dict)}
        followers = info.get("channel_follower_count")
        return CreatorDetails(
            ref=channel_id, url=root, title=str(info.get("channel") or info.get("uploader") or channel_id),
            handle=handle, description=info.get("description") or None,
            avatar_url=pictures.get("avatar_uncropped"), banner_url=pictures.get("banner_uncropped"),
            facts=(f"{_count(followers)} subscribers",) if isinstance(followers, int) else (),
            sections=tuple(sections),
            music=has_releases, music_reason="It has releases on YouTube Music" if has_releases else None,
        )

    def season_lists(self, url: str) -> list[SectionRef]:
        """A channel's playlists, newest first."""
        root = channel_root(collection_url(url))
        if root is None:
            raise runner.YtDlpError("This link is not a YouTube channel")
        return self.playlists(root)

    def playlists(self, root: str) -> list[SectionRef]:
        """The playlists a channel lists, newest first."""
        try:
            # A page YouTube refuses part way still leaves the playlists of the pages before it.
            listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/playlists", cookies=sites.cookies_for(root))
        except runner.YtDlpError as exc:
            logger.info("Not listing the playlists of %s: %s", root, exc)
            return []
        entries = [
            entry for entry in listing.get("entries") or []
            if isinstance(entry, dict) and entry.get("id") and entry.get("title")
        ]
        # A channel may list hundreds of playlists, whose pictures are checked all at once.
        images = thumbnails.widest_stills([picture(entry) for entry in entries])
        found = []
        for entry, image in zip(entries, images):
            count = entry.get("playlist_count")
            found.append(self.section(
                str(entry["id"]), f"https://www.youtube.com/playlist?list={entry['id']}", LIST_TYPE, title=str(entry["title"]),
                item_count=count if isinstance(count, int) else None, image_url=image,
                description=entry.get("description") or None,
            ))
        return found

    def has_releases(self, root: str) -> bool:
        """Whether a channel has a Releases tab, which only music artists have. yt-dlp can't always list what is on
        it, but says when a channel has none. It is a guess the user can change: a channel can be an artist's and
        still be more than their music."""
        try:
            self.read(f"{root}/releases")
            return True
        except runner.YtDlpError as exc:
            logger.debug("%s has no releases: %s", root, exc)
            return False

    def listing_urls(self, url: str, feeds: frozenset[str] | None = None) -> list[str]:
        """For a channel's Videos tab, the tab of each of its feeds, of only ``feeds`` when given."""
        url = collection_url(url)
        ref = mapping.youtube_ref(url)
        if ref is None or ref.kind == "playlist" or ref.tab != "videos":
            return [url]
        parts = urlsplit(url)
        base = parts.path.rstrip("/").removesuffix("/videos")
        return [
            urlunsplit(parts._replace(path=f"{base}/{type_.path}")) for type_ in self.feed_types
            if feeds is None or type_.path in feeds
        ]

    def music_reason(self, url: str, details: CollectionDetails) -> str | None:
        """An album on YouTube Music, or a collection whose channel has releases on YouTube Music, as a music
        artist's has (see ``has_releases``)."""
        if parse_qs(urlsplit(url).query).get("list", [""])[0].startswith("OLAK5uy_"):
            return "It is an album on YouTube Music"
        root = channel_root(collection_url(url)) or (channel_root(details.author_url) if details.author_url else None)
        if root is not None and self.has_releases(root):
            return "Its channel has releases on YouTube Music"
        return None
