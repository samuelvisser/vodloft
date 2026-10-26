"""The contract every Source implements.

The rest of VODLoft talks to a service only through these types, never through
a Source's own client, records or errors. The contract only holds what has a
caller today; methods are added together with the feature that needs them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar
from urllib.parse import urlsplit


class Feature(StrEnum):
    """Optional capabilities. Code that only makes sense for some services
    checks the feature instead of the Source id."""

    SHOWS = "shows"
    MOVIES = "movies"
    MOVIE_EXTRAS = "movie_extras"
    BROWSE = "browse"
    LOGIN = "login"
    LIVE_EPISODES = "live_episodes"
    MEMBERSHIP_LEVELS = "membership_levels"
    RSS_STREAMING = "rss_streaming"
    VIDEOS = "videos"
    EPISODE_LISTS = "episode_lists"
    """Shows whose episodes the Source lists with ``list_episodes``. VODLoft
    keeps the Source's own seasons, or makes one season per upload year."""
    SEARCH = "search"
    """Finding shows and videos at the Source by name, with ``search``."""
    PROGRAM_UPDATES = "program_updates"
    COOKIES = "cookies"


@dataclass(frozen=True)
class EpisodeMedia:
    """Where the current media of an episode can be fetched from."""

    video_url: str | None
    audio_url: str | None
    drm_protected: bool = False


class PlaybackKind(StrEnum):
    """How the downloader fetches a playback URL."""

    URL = "url"
    """The URL is the media itself: a file or an HLS playlist."""
    YTDLP = "ytdlp"
    """The URL is a web page that yt-dlp downloads with ``Playback.command``."""


@dataclass(frozen=True)
class Playback:
    """The playable URL of a movie, movie extra, single video or listed episode.

    ``metadata`` is the Source's own movie extra record when the playback lookup
    also returned fresher metadata. Only Sources with ``Feature.MOVIE_EXTRAS``
    return it, and the movie feature that applies it is The Daily Wire's.
    ``command`` is the yt-dlp program and options for ``PlaybackKind.YTDLP``.
    """

    url: str
    metadata: Any = None
    drm_protected: bool = False
    kind: PlaybackKind = PlaybackKind.URL
    command: tuple[str, ...] = ()


class LinkKind(StrEnum):
    SHOW = "show"
    MOVIE = "movie"
    EPISODE = "episode"
    VIDEO = "video"


@dataclass(frozen=True)
class ResolvedLink:
    """What a link points to, with enough to show a preview before anything is added.

    An episode link names the show it belongs to in ``show_slug`` and
    ``show_url`` when the Source can tell, because VODLoft adds whole shows.
    """

    kind: LinkKind
    slug: str
    url: str
    title: str
    description: str | None = None
    image_url: str | None = None
    author_name: str | None = None
    show_slug: str | None = None
    show_url: str | None = None
    site: str | None = None
    """The site the link is on, for a Source that serves many sites."""
    drm_protected: bool = False
    """The video is protected by DRM, so it can be added but not downloaded."""


@dataclass(frozen=True)
class SeasonRef:
    """A season as the Source names it."""

    slug: str
    number: int
    title: str | None = None

    @property
    def name(self) -> str:
        return self.title or f"Season {self.number}"


@dataclass(frozen=True)
class VideoDetails:
    """Everything VODLoft stores about a single video.

    ``slug`` is the Source's own id for the video and ``url`` its canonical link.
    """

    slug: str
    url: str
    title: str
    description: str | None = None
    duration: float | None = None
    image_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    published_at: datetime | None = None
    drm_protected: bool = False
    """The video is protected by DRM, so it can be added but not downloaded."""
    season: SeasonRef | None = None
    """The show season a listed episode belongs to, for a Source with real seasons.
    Without one, VODLoft puts the episode in a season per upload year."""
    episode_number: int | None = None
    """The episode's number in its season, when the Source has one."""


@dataclass(frozen=True)
class ShowDetails:
    """What VODLoft stores about a show from a Source with ``Feature.EPISODE_LISTS``."""

    slug: str
    url: str
    title: str
    description: str | None = None
    image_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    seasons: tuple[SeasonRef, ...] = ()
    """The show's own seasons, for a Source that has them, so they can be picked
    before the episodes are indexed."""


@dataclass(frozen=True)
class ProgramStatus:
    """The program a Source runs, for a Source with ``Feature.PROGRAM_UPDATES``."""

    name: str
    version: str | None
    last_update_at: datetime | None = None
    last_update_error: str | None = None


ANY_DOMAIN = "*"


def link_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def on_domain(host: str, domain: str) -> bool:
    """True when the host is the domain or a subdomain of it."""
    return host == domain or host.endswith(f".{domain}")


class Source(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    domains: ClassVar[tuple[str, ...]]
    features: ClassVar[frozenset[Feature]]

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def handles(self, url: str) -> bool:
        """True when the link's host is one of this Source's domains or a subdomain of one."""
        if ANY_DOMAIN in self.domains:
            return True
        host = link_host(url)
        return any(on_domain(host, domain) for domain in self.domains)

    @abstractmethod
    def resolve(self, url: str) -> ResolvedLink | None:
        """Say what a link points to, or None when this Source does not recognise it."""

    def episode_media(
        self, *, slug: str, members_only: bool, interactive: bool = False,
    ) -> EpisodeMedia:
        """Look up the current media URLs of an episode. Only Sources whose shows
        do not have ``Feature.EPISODE_LISTS`` implement it; the others play each
        episode with ``video_playback``."""
        raise NotImplementedError(f"{self.name} plays its episodes with video_playback")

    def movie_playback(
        self, *, movie_slug: str, title: str, duration: float | None,
        extra_slug: str | None = None, is_extra: bool = False, is_official_trailer: bool = False,
    ) -> Playback:
        """Resolve the playable URL of a movie or one of its extras. Only Sources with ``Feature.MOVIES`` implement it."""
        raise NotImplementedError(f"{self.name} has no movies")

    def video_details(self, url: str) -> VideoDetails:
        """Look up a single video. Only Sources with ``Feature.VIDEOS`` implement it."""
        raise NotImplementedError(f"{self.name} has no single videos")

    def video_playback(self, *, slug: str, url: str) -> Playback:
        """Resolve the playable URL of a single video, or of an episode of a show
        from ``list_episodes``. Only Sources with ``Feature.VIDEOS`` or
        ``Feature.EPISODE_LISTS`` implement it."""
        raise NotImplementedError(f"{self.name} has no single videos")

    def show_details(self, url: str) -> ShowDetails:
        """Look up a show. Only Sources with ``Feature.EPISODE_LISTS`` implement it."""
        raise NotImplementedError(f"{self.name} does not list episodes")

    def list_episodes(self, url: str, *, known: frozenset[str]) -> Iterator[VideoDetails]:
        """The show's episodes whose slugs are not in ``known``.

        An episode that cannot be looked up right now is left out, so a later
        scan tries it again.
        """
        raise NotImplementedError(f"{self.name} does not list episodes")

    def search(self, query: str) -> list[ResolvedLink]:
        """Shows and videos whose name matches the query. Only Sources with ``Feature.SEARCH`` implement it."""
        raise NotImplementedError(f"{self.name} cannot be searched")

    def program_status(self) -> ProgramStatus:
        """The program this Source runs. Only Sources with ``Feature.PROGRAM_UPDATES`` implement it."""
        raise NotImplementedError(f"{self.name} has no program to update")

    def program_update_due(self) -> bool:
        """True when the weekly update should fetch a new version of the program."""
        raise NotImplementedError(f"{self.name} has no program to update")

    def update_program(self) -> ProgramStatus:
        """Fetch the latest version of the program and use it from now on."""
        raise NotImplementedError(f"{self.name} has no program to update")

    def has_cookies(self) -> bool:
        """True when a cookies file is stored. Only Sources with ``Feature.COOKIES`` implement it."""
        raise NotImplementedError(f"{self.name} takes no cookies file")

    def save_cookies(self, content: bytes) -> None:
        """Store a cookies file that every lookup and download uses. Raises ValueError for a file it cannot use."""
        raise NotImplementedError(f"{self.name} takes no cookies file")

    def remove_cookies(self) -> None:
        raise NotImplementedError(f"{self.name} takes no cookies file")
