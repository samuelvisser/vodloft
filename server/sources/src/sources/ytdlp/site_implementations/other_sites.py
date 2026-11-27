"""OtherSitesImplementation: how yt-dlp does on any site what that site's contract says it has.

A site's contract (``site_contracts``) says what the site has; its implementation here says how yt-dlp gets it there.
``OtherSitesImplementation`` does everything the generic yt-dlp way, for every site without an implementation of its
own; a site's own implementation subclasses it and overrides only what yt-dlp has to do differently there, the way
its contract subclasses ``OtherSites``. Only the yt-dlp Source uses implementations.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Executor, Future
from typing import ClassVar
from urllib.parse import urljoin

from progress_plan import PlanTracker, StageSpec

from ...contract import MAIN_TAG, CollectionDetails, CreatorDetails, CreatorTier, DeviceCode, SearchResults, SectionRef, SectionRole, SignInRejected, Site, link_host
from ...site_accounts import SignedIn
import requests

from ... import ytdlp_runner as runner
from .. import sites
from ..site_contracts import YtdlpFeedSectionType

logger = logging.getLogger(__name__)

_SHARE_TIMEOUT_SECONDS = 15
_BROWSER = "Mozilla/5.0"

Read = Callable[[str], dict]
"""Looks a link up through yt-dlp: its first item, or the video itself."""


class OtherSitesImplementation:
    key: ClassVar[str | None] = None
    """The key of the Site the implementation is for; None for every site without one of its own."""
    list_keys: ClassVar[frozenset[str]] = frozenset()
    """The keys of the Site's section types besides its feeds that ``creator_details`` finds, such as playlists.
    Feeds are read by their path, so each section type of the Site's contract is a feed or one of these."""

    def __init__(self, site: Site, read: Read) -> None:
        self.site = site
        self.read = read

    def full_link(self, url: str) -> str:
        """The page a share link on one of the Site's ``share_hosts`` leads to, when that is the Site's own; any other
        link as it is."""
        if link_host(url) not in self.site.share_hosts:
            return url
        try:
            response = requests.head(url, headers={"User-Agent": _BROWSER}, timeout=_SHARE_TIMEOUT_SECONDS, allow_redirects=False)
        except requests.RequestException as exc:
            logger.info("Could not follow the share link %s: %s", url, exc)
            return url
        target = urljoin(url, response.headers.get("Location") or "")
        if not response.is_redirect or link_host(target) in self.site.share_hosts or sites.site_for(target).key != self.site.key:
            return url
        return self.shared_page(target)

    def shared_page(self, url: str) -> str:
        """The page a share link led to, as VODLoft keeps it."""
        return url

    def collection_link(self, url: str) -> str:
        """The page a collection of the link lists, such as a channel's videos for its front page; the link itself
        when it lists one already."""
        return url

    def listing(self, url: str, limit: int | None = None) -> dict | None:
        """A page's videos, as yt-dlp's flat listing of it gives them, for a page the implementation lists itself
        because yt-dlp can't, or can only slowly, such as Patreon's; None for yt-dlp to list it. ``limit`` is how many
        videos are wanted, the first first, and 0 for the page alone. An entry may be complete, such as a video the
        Site locks, with what a lookup would give: its ``_access`` and ``_access_refused``; it is then not looked up."""
        return None

    def refused_access(self, info: dict, key: str) -> str:
        """The access a video needs that yt-dlp could not get for lack of ``key``, where the Site tells it more
        exactly, such as the cheapest of the creator's tiers that unlocks a Patreon post."""
        return key

    def creator_tiers(self, url: str) -> tuple[CreatorTier, ...]:
        """The paid tiers of the creator a link is of, on a Site whose creators set up tiers of their own."""
        return ()

    def served_picture(self, url: str | None) -> str | None:
        """The picture yt-dlp gives a video, or None when the Site is known not to serve it, so that VODLoft shows its
        own picture instead of an empty one."""
        return url

    def episode_tag(self, info: dict, url: str) -> str:
        """Which of the Site's episode tags yt-dlp's full lookup of a video gives it."""
        return MAIN_TAG

    def test_api(self, values: dict[str, str]) -> None:
        """Ask the Site's own API (``Site.site_api``) once with these values. Raises ApiKeyRejected when the Site does
        not accept them."""
        raise runner.YtDlpError(f"VODLoft uses no API of {self.site.name}")

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        """Sign in on the Site with what the user filled in for its ``PASSWORD`` or ``TOKEN`` account sign-in
        (``Site.account_sign_in``). Raises SignInRejected when the Site does not accept it."""
        raise SignInRejected(f"VODLoft can't sign in on {self.site.name} with an account")

    def start_code_sign_in(self) -> DeviceCode:
        """Ask the Site for a code the user enters on its own page, for a ``DEVICE_CODE`` account sign-in."""
        raise SignInRejected(f"VODLoft can't sign in on {self.site.name} with a code")

    def finish_code_sign_in(self, code: DeviceCode, stop: Callable[[float], bool]) -> SignedIn:
        """Wait until the user entered the code; ``stop`` waits the seconds it is given and tells whether to give up.
        Raises SignInCodeEnded when the code ran out or the user turned it down."""
        raise SignInRejected(f"VODLoft can't sign in on {self.site.name} with a code")

    def renew_sign_in(self, signed_in: SignedIn) -> SignedIn:
        """The sign-in again, before it runs out (``SignedIn.renew_at``). Raises SignInRejected when the Site no
        longer accepts it."""
        raise SignInRejected(f"VODLoft can't renew a sign-in on {self.site.name}")

    def search(self, query: str) -> SearchResults:
        """The Site's collections and videos whose name matches the query, on a Site whose contract makes it
        ``searchable``."""
        raise runner.YtDlpError(f"VODLoft can't search {self.site.name}")

    # Creators

    def creator_root(self, url: str) -> str | None:
        """The creator's own page that a link of theirs belongs to, such as a channel for one of its playlists; None
        when the link belongs to no creator VODLoft knows on the Site."""
        return None

    def complete_collection(self, details: CollectionDetails, url: str) -> CollectionDetails:
        """The collection of the link as yt-dlp describes it, with what yt-dlp leaves out or names its own way filled
        in, such as an artist account's name and picture."""
        return details

    def list_type(self, info: dict, url: str) -> str | None:
        """Which of the Site's types of list the link is, as yt-dlp describes it, for a Site whose lists come in
        several types that their links don't tell apart."""
        return None

    def is_creator_page(self, url: str) -> bool:
        """Whether the link stands for all of a creator's uploads, so that a collection of it can make the creator's
        lists its seasons."""
        return False

    def is_list(self, url: str) -> bool:
        """Whether the link is one of the Site's lists, rather than a creator's page or one of its feeds."""
        return False

    def creator_details(self, ref: str, plan: PlanTracker) -> CreatorDetails:
        """The creator, looked up by steps the implementation adds to ``plan`` and runs."""
        raise runner.YtDlpError(f"VODLoft can't add creators from {self.site.name}")

    def season_lists(self, url: str) -> list[SectionRef]:
        """The creator's lists that can be the seasons of a collection of theirs, newest first."""
        raise runner.YtDlpError(f"{self.site.name} has no lists VODLoft can make seasons of")

    @property
    def feed_types(self) -> tuple[YtdlpFeedSectionType, ...]:
        return tuple(type_ for type_ in self.site.section_types if isinstance(type_, YtdlpFeedSectionType))

    def read_feeds(self, root: str, pool: Executor, plan: PlanTracker) -> dict[str, Future]:
        """Starts looking up each of the Site's feeds on the creator's page, all at once, each a step of ``plan``. A
        feed besides the main one that is not there, such as a creator without Shorts, is skipped."""
        plan.add(*(
            StageSpec(id=f"feed_{type_.key}", code="read_feed", label=f"Reading the {type_.names.plural}")
            for type_ in self.feed_types
        ))
        return {
            type_.key: plan.follow(
                f"feed_{type_.key}", pool.submit(self.read, f"{root}/{type_.path}"),
                failed="failed" if type_.role is SectionRole.MAIN else "skipped",
            )
            for type_ in self.feed_types
        }

    def feed_sections(self, root: str, listings: Mapping[str, Future]) -> list[SectionRef]:
        """The creator's feeds, from ``read_feeds``: each one the creator has. A feed besides the main one, such as
        Shorts, only counts when it lists something."""
        sections = []
        for type_ in self.feed_types:
            try:
                listing = listings[type_.key].result()
            except runner.YtDlpError as exc:
                # A creator without Shorts or livestreams has no such page.
                logger.debug("%s has no %s: %s", root, type_.path, exc)
                continue
            if listing.get("entries") or type_.role is SectionRole.MAIN:
                sections.append(SectionRef(ref=type_.path, url=f"{root}/{type_.path}", type=type_))
        return sections

    # Collections

    def listing_urls(self, url: str, feeds: frozenset[str] | None = None) -> list[str]:
        """The pages that list a collection's videos; for a creator's page, the page of each of its feeds, or of only
        the feeds whose refs are ``feeds``."""
        return [url]

    def all_music(self, url: str, newest_albums: int | None = None) -> list[dict] | None:
        """yt-dlp's flat entries of everything on an artist's page of all their music, which no single listing has;
        None for any other link, which ``listing_urls`` lists."""
        return None

    def music_reason(self, url: str, details: CollectionDetails) -> str | None:
        """Why a collection of the link is likely music, or None."""
        return f"It is on {self.site.name}, a site for music" if self.site.audio_only else None

    def section(self, ref: str, url: str, key: str, **values) -> SectionRef:
        """A section of the Site's type ``key``."""
        return SectionRef(ref=ref, url=url, type=self.site.section_type(key), **values)

