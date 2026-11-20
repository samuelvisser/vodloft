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

from ...contract import CollectionDetails, CreatorDetails, SectionRef, SectionRole, Site
from ... import ytdlp_runner as runner
from ..site_contracts import YtdlpFeedSectionType

logger = logging.getLogger(__name__)

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

    # Creators

    def creator_root(self, url: str) -> str | None:
        """The creator's own page that a link of theirs belongs to, such as a channel for one of its playlists; None
        when the link belongs to no creator VODLoft knows on the Site."""
        return None

    def creator_page(self, url: str) -> str | None:
        """The creator whose own page the link is, so that it can be added as the creator instead; None for one of
        their lists or videos."""
        return None

    def is_creator_page(self, url: str) -> bool:
        """Whether the link stands for all of a creator's uploads, so that a collection of it can make the creator's
        lists its seasons."""
        return False

    def creator_details(self, ref: str, progress: Callable[[str], None]) -> CreatorDetails:
        raise runner.YtDlpError(f"VODLoft can't add creators from {self.site.name}")

    def season_lists(self, url: str) -> list[SectionRef]:
        """The creator's lists that can be the seasons of a collection of theirs, newest first."""
        raise runner.YtDlpError(f"{self.site.name} has no lists VODLoft can make seasons of")

    @property
    def feed_types(self) -> tuple[YtdlpFeedSectionType, ...]:
        return tuple(type_ for type_ in self.site.section_types if isinstance(type_, YtdlpFeedSectionType))

    def read_feeds(self, root: str, pool: Executor) -> dict[str, Future]:
        """Starts looking up each of the Site's feeds on the creator's page, all at once."""
        return {type_.key: pool.submit(self.read, f"{root}/{type_.path}") for type_ in self.feed_types}

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

