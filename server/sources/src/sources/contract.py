"""The contract every Source implements.

The rest of VODLoft talks to a service only through these types, never through
a Source's own client, records or errors. The contract only holds what has a
caller today; methods are added together with the feature that needs them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
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
    COSTLY_SEARCH = "costly_search"
    """Each search costs the Source something, such as API quota, so the search
    page searches when asked instead of while the user types."""
    PROGRAM_UPDATES = "program_updates"
    COOKIES = "cookies"
    API_KEY = "api_key"
    """An optional key for the service's own API, which makes catalogue lookups faster."""
    QUICK_CHECK = "quick_check"
    """Cheaply finding a listed show's newest items, with ``latest_items`` and
    ``item_details``, between full scans of the show."""
    CATALOGUE_REFRESH = "catalogue_refresh"
    """Refreshing the titles, descriptions and thumbnails of a listed show's
    episodes, and telling which ones the Source no longer has, with ``refresh_items``."""


class RssEpisodeType(StrEnum):
    """The podcast episode type an RSS feed gives an episode."""

    FULL = "full"
    TRAILER = "trailer"
    BONUS = "bonus"


MAIN_TAG = "ep"


@dataclass(frozen=True)
class EpisodeTag:
    """A kind of episode a Source tells apart, such as a YouTube Short.

    The key is the first part of an episode's identifier (``short.12``) and what
    Download and RSS profiles select. Episodes with the ``main`` tag follow the
    show's numbering scheme; every other tag counts on its own across the show.
    """

    key: str
    label: str
    help: str
    selected_by_default: bool = True
    rss_episode_type: RssEpisodeType = RssEpisodeType.FULL
    main: bool = False


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
    needs_subscription: bool = False
    """The Source only plays this to a paying account, which VODLoft does not have."""
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
    needs_subscription: bool = False
    """The Source only gives the video to a paying account, so it can be added but not downloaded."""
    kind_label: str | None = None
    """What the Source calls this kind of result, such as Channel or Playlist for a show."""
    facts: tuple[str, ...] = ()
    """Short facts for a search result, such as "412 videos" or "19:05"."""


@dataclass(frozen=True)
class SearchNotice:
    """How a search was answered, shown above its results."""

    badge: str
    text: str
    tone: str = "neutral"
    """neutral, or warning when the search was answered a slower or poorer way."""
    link_label: str | None = None
    link_path: str | None = None
    """A VODLoft page where the user can do something about it, such as add a key."""


@dataclass(frozen=True)
class SearchResults:
    results: list[ResolvedLink]
    notice: SearchNotice | None = None


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
    needs_subscription: bool = False
    """The Source only gives the video to a paying account, such as NPO Plus. VODLoft
    indexes it, but does not download it."""
    season: SeasonRef | None = None
    """The show season a listed episode belongs to, for a Source with real seasons.
    Without one, VODLoft puts the episode in a season per upload year."""
    episode_number: int | None = None
    """The episode's number in its season, when the Source has one."""
    tag: str = MAIN_TAG
    """The key of one of the Source's episode tags."""


@dataclass(frozen=True)
class ItemRef:
    """One of a show's items, as a quick check finds it: its slug and its link."""

    slug: str
    url: str


@dataclass(frozen=True)
class ItemRefresh:
    """What a Source says now about items VODLoft already has.

    ``details`` holds the items it could look up. Only the title, description
    and picture are refreshed from them, and a field the Source left out is kept.
    ``removed`` holds the items the Source says it no longer has. An item in
    neither could not be checked this time and stays as it is.
    """

    details: dict[str, VideoDetails] = field(default_factory=dict)
    removed: frozenset[str] = frozenset()


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


@dataclass(frozen=True)
class SourceProblem:
    """Something about a Source the user should fix, shown under Needs attention on Home."""

    title: str
    detail: str
    fix_url: str | None = None
    """A page outside VODLoft where the user can fix it."""


@dataclass(frozen=True)
class ApiQuotaShare:
    """A part of the daily quota, set aside for one kind of call."""

    name: str
    used: int
    limit: int


@dataclass(frozen=True)
class ApiStatus:
    """The API key of a Source with ``Feature.API_KEY``, and how much of today's quota it spent."""

    key_hint: str | None
    """The last characters of the key, or None when no key is set."""
    shares: tuple[ApiQuotaShare, ...]
    daily_quota: int
    exhausted: bool
    """The service said today's quota is used up."""
    resets_at: datetime
    problem: str | None = None
    problem_fix_url: str | None = None
    show_count: int = 0
    """The shows the key speeds up."""
    rescan_units: int = 0
    """What one full re-scan of those shows costs, so the settings can say how often each gets checked."""


class ApiKeyRejected(ValueError):
    """The service does not accept the key; the message says what to do about it."""

    def __init__(self, message: str, fix_url: str | None = None):
        super().__init__(message)
        self.fix_url = fix_url


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
    episode_tags: ClassVar[tuple[EpisodeTag, ...]] = (
        EpisodeTag(MAIN_TAG, "Episode", "An episode of the show", main=True),
    )
    """Every tag the Source gives episodes, the main one first."""
    subscription_name: ClassVar[str | None] = None
    """What the Source calls the paid subscription some of its videos need, such as NPO Plus."""
    search_label: ClassVar[str | None] = None
    """What the search button names, when that is not the Source's name, such as YouTube for yt-dlp."""

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def handles(self, url: str) -> bool:
        """True when the link's host is one of this Source's domains or a subdomain of one."""
        if ANY_DOMAIN in self.domains:
            return True
        host = link_host(url)
        return any(on_domain(host, domain) for domain in self.domains)

    def episode_tags_for(self, url: str | None) -> tuple[EpisodeTag, ...]:
        """The tags episodes of the show at this link can get, or all of them without a link."""
        return self.episode_tags

    def episode_tag(self, key: str | None) -> EpisodeTag | None:
        return next((tag for tag in self.episode_tags if tag.key == key), None)

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

    def latest_items(self, url: str) -> list[ItemRef]:
        """The show's newest items, newest first. Only Sources with ``Feature.QUICK_CHECK`` implement it."""
        raise NotImplementedError(f"{self.name} has no quick check")

    def item_details(self, items: Sequence[ItemRef]) -> dict[str, VideoDetails | None]:
        """Details per item slug. None means the item is gone, private or not
        finished yet, so a later check tries it again. ``Feature.QUICK_CHECK`` only."""
        raise NotImplementedError(f"{self.name} has no quick check")

    def refresh_items(self, url: str, items: Sequence[ItemRef]) -> ItemRefresh:
        """What the Source says now about these items of the show at ``url``.
        Only Sources with ``Feature.CATALOGUE_REFRESH`` implement it."""
        raise NotImplementedError(f"{self.name} cannot refresh a show's items")

    def quick_check_minutes(self, shows: Sequence[tuple[str, int]]) -> int:
        """How often each of these shows, given as link and episode count, can
        get a quick check. ``Feature.QUICK_CHECK`` only."""
        raise NotImplementedError(f"{self.name} has no quick check")

    def search(self, query: str) -> SearchResults:
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

    def problems(self) -> list[SourceProblem]:
        """What the user should fix about this Source right now."""
        return []

    def api_status(self, shows: Sequence[tuple[str, int]] = ()) -> ApiStatus:
        """The API key and today's quota. ``shows`` are the link and episode count of
        each of this Source's shows. Only Sources with ``Feature.API_KEY`` implement it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def save_api_key(self, key: str) -> None:
        """Test the key with one call and store it. Raises ApiKeyRejected when the service does not accept it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def test_api_key(self) -> None:
        """Test the stored key with one call. Raises ApiKeyRejected when the service does not accept it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def remove_api_key(self) -> None:
        raise NotImplementedError(f"{self.name} takes no API key")
