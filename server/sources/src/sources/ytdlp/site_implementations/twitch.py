"""How yt-dlp does on Twitch what Twitch's contract says it has: a channel, its videos and clips, and its
collections."""
from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import requests

from progress_plan import PlanTracker, StageSpec

from ...contract import LIST_TYPE, MAIN_TAG, ApiKeyRejected, CreatorDetails, SearchNotice, SearchResults, SectionRef
from ... import site_api_keys
from ... import ytdlp_runner as runner
from .. import sites, twitch_api
from ..site_contracts.twitch import CLIP_TAG
from .other_sites import OtherSitesImplementation

logger = logging.getLogger(__name__)

_HOSTS = frozenset({"twitch.tv", "www.twitch.tv", "m.twitch.tv", "go.twitch.tv"})
_LOGIN = re.compile(r"^[A-Za-z0-9_]{2,25}$")
# Twitch's own pages, which are no channel's.
_OWN_PAGES = frozenset({
    "videos", "collections", "directory", "downloads", "drops", "friends", "inventory", "jobs", "login", "messages",
    "moderator", "p", "payments", "popout", "prime", "search", "settings", "signup", "subscriptions", "team", "turbo",
    "wallet", "embed", "store", "user",
})
# A channel's pages that stand for the channel itself.
_CHANNEL_PAGES = frozenset({"", "videos", "about", "schedule", "home"})
_PAGE_TIMEOUT_SECONDS = 15
_BROWSER = "Mozilla/5.0"
_META = re.compile(r'<meta[^>]+property="og:(title|image)"[^>]+content="([^"]*)"')


def _parts(url: str) -> list[str]:
    return [part for part in urlsplit(url).path.split("/") if part]


class TwitchImplementation(OtherSitesImplementation):
    key = "twitch"
    list_keys = frozenset({LIST_TYPE})

    def test_api(self, values: dict[str, str]) -> None:
        try:
            twitch_api.test(values)
        except twitch_api.TwitchApiError as exc:
            raise ApiKeyRejected(f"Could not test the client ID and secret: {exc}") from None

    def search(self, query: str) -> SearchResults:
        """Twitch's channels whose name matches, through its own API."""
        values = site_api_keys.load(self.site.key)
        if values is None:
            raise runner.YtDlpError("Set up the Twitch API under Settings to search Twitch")
        try:
            results = twitch_api.search_channels(values, query)
        except ApiKeyRejected as exc:
            site_api_keys.record_problem(self.site.key, str(exc))
            raise runner.YtDlpError(str(exc)) from None
        except twitch_api.TwitchApiError as exc:
            raise runner.YtDlpError(f"Twitch could not be searched: {exc}") from None
        site_api_keys.record_problem(self.site.key, None)
        return SearchResults(results, SearchNotice(badge="Search via Twitch API", text="Twitch finds channels by name"))

    def creator_root(self, url: str) -> str | None:
        """The channel a link of Twitch's is on: its own page, one of its tabs, or one of its clips."""
        if (urlsplit(url).hostname or "").lower() not in _HOSTS:
            return None
        parts = _parts(url)
        if not parts or parts[0].lower() in _OWN_PAGES or not _LOGIN.match(parts[0]):
            return None
        return f"https://www.twitch.tv/{parts[0].lower()}"

    def _page(self, url: str) -> str | None:
        """Which of the channel's own pages a link is, such as "" for its front page; None for anything else."""
        if self.creator_root(url) is None:
            return None
        rest = _parts(url)[1:]
        return (rest[0].lower() if rest else "") if len(rest) <= 1 else None

    def creator_page(self, url: str) -> str | None:
        return self.creator_root(url) if self._page(url) in _CHANNEL_PAGES else None

    def is_creator_page(self, url: str) -> bool:
        """The channel's Videos page of all its videos, which a collection of the channel lists."""
        return self._page(url) == "videos" and parse_qs(urlsplit(url).query).get("filter", ["all"])[0] == "all"

    def collection_link(self, url: str) -> str:
        """The channel's own page shows its stream; the collection of the channel lists all its videos."""
        if self._page(url) in _CHANNEL_PAGES - {"videos"}:
            return f"{self.creator_root(url)}/{self.feed_types[0].path}"
        return url

    def episode_tag(self, info: dict, url: str) -> str:
        """A clip, as yt-dlp's extractor of clips says; every other video is a video."""
        return CLIP_TAG if info.get("extractor_key") == "TwitchClips" or "/clip/" in url else MAIN_TAG

    def creator_details(self, ref: str, plan: PlanTracker) -> CreatorDetails:
        """A channel: its name and picture from its page, the feeds it has, and its collections, all looked up at
        once."""
        root = self.creator_root(ref)
        if root is None:
            raise runner.YtDlpError("This link is not a Twitch channel")
        with ThreadPoolExecutor(max_workers=len(self.feed_types) + 2, thread_name_prefix="channel-lookup") as pool:
            listings = self.read_feeds(root, pool, plan)
            # The collections take longest, so their step comes last.
            plan.add(
                StageSpec(id="page", code="read_page", label="Reading the channel's page"),
                StageSpec(id="collections", code="read_lists", label=f"Reading the {self.site.section_list_names.plural}"),
            )
            playlists = plan.follow("collections", pool.submit(self.playlists, root))
            page = plan.follow("page", pool.submit(self.page_facts, root))
            sections = self.feed_sections(root, listings) + playlists.result()
            name, avatar = page.result()
        login = root.rsplit("/", 1)[-1]
        return CreatorDetails(
            ref=login, url=root, title=name or login, handle=login, avatar_url=avatar, sections=tuple(sections),
        )

    def page_facts(self, root: str) -> tuple[str | None, str | None]:
        """The channel's name and picture, which only its page shows: "Name - Twitch", or "Name - Live on Twitch"
        while it streams."""
        try:
            response = requests.get(root, headers={"User-Agent": _BROWSER}, timeout=_PAGE_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.info("No name or picture for %s: %s", root, exc)
            return None, None
        meta = {key: html.unescape(value) for key, value in _META.findall(response.text)}
        title = meta.get("title", "")
        name = title.rsplit(" - ", 1)[0].strip() if " - " in title else None
        return name or None, meta.get("image") or None

    def season_lists(self, url: str) -> list[SectionRef]:
        """The channel's collections, newest first."""
        root = self.creator_root(url)
        if root is None:
            raise runner.YtDlpError("This link is not a Twitch channel")
        return self.playlists(root)

    def playlists(self, root: str) -> list[SectionRef]:
        """The collections a channel lists, newest first."""
        try:
            listing = runner.run_json("--flat-playlist", "--ignore-errors", f"{root}/videos?filter=collections", cookies=sites.cookies_for(root))
        except runner.YtDlpError as exc:
            logger.info("Not listing the collections of %s: %s", root, exc)
            return []
        return [
            self.section(
                str(entry["id"]), str(entry.get("url") or f"https://www.twitch.tv/collections/{entry['id']}"), LIST_TYPE,
                title=str(entry["title"]), image_url=entry.get("thumbnail") or None,
            )
            for entry in listing.get("entries") or []
            if isinstance(entry, dict) and entry.get("id") and entry.get("title")
        ]

    def listing_urls(self, url: str, feeds: frozenset[str] | None = None) -> list[str]:
        """For the channel's Videos page, the page of each of its feeds, of only ``feeds`` when given."""
        if not self.is_creator_page(url):
            return [url]
        root = self.creator_root(url)
        return [f"{root}/{type_.path}" for type_ in self.feed_types if feeds is None or type_.path in feeds]
