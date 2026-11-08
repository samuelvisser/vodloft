"""The contract every Source implements.

The rest of VODLoft talks to a service only through these types, never through
a Source's own client, records or errors. The contract only holds what has a
caller today; methods are added together with the feature that needs them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar
from urllib.parse import urlsplit

from config.settings.site_settings import SITE_SETTINGS, SiteSetting, UpgradeImprovement


class Feature(StrEnum):
    """Optional capabilities. Code that only makes sense for some services
    checks the feature instead of the Source id."""

    COLLECTIONS = "collections"
    MOVIES = "movies"
    MOVIE_EXTRAS = "movie_extras"
    BROWSE = "browse"
    LOGIN = "login"
    LIVE_EPISODES = "live_episodes"
    MEMBERSHIP_LEVELS = "membership_levels"
    VIDEOS = "videos"
    EPISODE_LISTS = "episode_lists"
    """Collections whose episodes the Source lists with ``list_episodes``. VODLoft
    keeps the Source's own seasons, or makes one season per upload year."""
    SEARCH = "search"
    """Finding collections and videos at the Source by name, with ``search``."""
    COSTLY_SEARCH = "costly_search"
    """Each search costs the Source something, such as API quota, so the search
    page searches when asked instead of while the user types."""
    PROGRAM_UPDATES = "program_updates"
    COOKIES = "cookies"
    OPTIONAL_COOKIES = "optional_cookies"
    """Downloads work with or without the cookies file, so each Collection chooses when to use it, and
    ``needs_cookies`` tells from a failed download that the cookies file would help."""
    API_KEY = "api_key"
    """An optional key for the service's own API, which makes catalogue lookups faster."""
    QUICK_CHECK = "quick_check"
    """Cheaply finding a listed collection's newest items, with ``latest_items`` and
    ``item_details``, between full scans of the collection."""
    FORMAT_CHOICES = "format_choices"
    """Quick downloads of this Source's videos can choose their quality,
    container and codec, and "Best" is whatever the Source's program picks on
    its own. Without it, "Best" is MP4 video at the highest resolution and the
    other choices are not offered."""
    YTDLP_OPTIONS = "ytdlp_options"
    """Your own yt-dlp options apply to this Source's downloads. Only the yt-dlp Source has it: NPO Start
    also downloads with yt-dlp, but as a Source of its own it takes no yt-dlp options."""
    METADATA_REFRESH = "metadata_refresh"
    """Looking published items up again for a while, with ``refresh_metadata``, so a
    title or picture changed after publication reaches VODLoft."""
    CATALOGUE_REFRESH = "catalogue_refresh"
    """Refreshing the titles, descriptions and thumbnails of a listed collection's
    episodes, and telling which ones the Source no longer has, with ``refresh_items``."""
    EPISODE_LOOKUPS = "episode_lookups"
    """VODLoft walks the Source's shows itself and looks each episode up on its own: to index a show,
    to follow an upcoming or live episode until it is out, and to refresh its details after
    publication. Sources with ``EPISODE_LISTS`` list and check their episodes in batches instead."""
    PAGE_STREAMS = "page_streams"
    """A feed streams an episode from the streams of its video page (``media_stream``,
    ``media_tracks``, ``live_stream``), which VODLoft can pass on, and MP4 video comes straight from
    the page. Without it a feed is sent to the links ``episode_media`` gives, and MP4 video is
    joined from the HLS stream first."""
    OWN_STUDIO = "own_studio"
    """The service makes its own shows and movies, so VODLoft names it as the studio of what it
    downloads. Without it the studio is left to the media itself."""
    PENDING_CHECKS = "pending_checks"
    """Listing upcoming and live videos with their publish status, and looking them up again
    with ``check_pending`` until they are published. VODLoft shows them, but never records one
    while it is live."""


class StreamMethod(StrEnum):
    """A way an RSS feed can stream a Site's episodes that are not downloaded."""

    FILE = "file"
    """One M4A audio file and one MP4 video file per episode."""
    HLS = "hls"
    """An HLS playlist of the video."""
    LIVE = "live"
    """Episodes while they are live, as HLS."""


VIDEO_HEIGHTS = (360, 480, 720, 1080, 1440, 2160, 4320)
"""Every video resolution a Local Media Profile can download up to."""


@dataclass(frozen=True)
class UpgradeChecks:
    """What the upgrade check can find on a Site. A Site that offers no improvements has no upgrade check."""

    improvements: tuple[UpgradeImprovement, ...] = ()
    """What can count as a better version, in the order a Download Profile shows them."""


@dataclass(frozen=True)
class SiteSettings:
    """Which of the settings in ``config.settings.site_settings`` a Site shows, and what it starts with.

    A setting with a system default shows on every Site unless the Site ``hides`` it, because the
    Site does not support it. A setting without one shows only on a Site that ``shows`` it. A preset is
    the value a setting starts with on the Site, until the user gives it one of its own or sets it
    back to the system default.
    """

    shows: frozenset[SiteSetting] = frozenset()
    hides: frozenset[SiteSetting] = frozenset()
    presets: Mapping[SiteSetting, Any] = field(default_factory=lambda: MappingProxyType({}), hash=False)

    def offers(self, key: SiteSetting) -> bool:
        return key not in self.hides if SITE_SETTINGS[key].has_system_default else key in self.shows


@dataclass(frozen=True)
class DownloadOptions:
    """What a Local Media Profile can choose for a Site's media. A Site that names none offers these defaults."""

    video_heights: tuple[int, ...] = VIDEO_HEIGHTS
    """The resolutions worth downloading up to: the Site has nothing higher than the highest one,
    and asking for less than the lowest one still gets the lowest."""
    audio_only: bool = True
    hls_bundle: bool = False
    """The Site's HLS stream, kept with every resolution in it."""
    quality_choices: bool = True
    """Codecs, container, quality goal, audio format and audio language pick the version that is
    downloaded. A Site with fixed versions, such as The Daily Wire, has nothing to choose."""

    @classmethod
    def combined(cls, options: Iterable[DownloadOptions]) -> DownloadOptions:
        """Everything that at least one of these offers."""
        options = list(options)
        if not options:
            return cls()
        return cls(
            video_heights=tuple(sorted({height for option in options for height in option.video_heights})),
            audio_only=any(option.audio_only for option in options),
            hls_bundle=any(option.hls_bundle for option in options),
            quality_choices=any(option.quality_choices for option in options),
        )


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
    collection's numbering scheme; every other tag counts on its own across the collection.
    ``singular`` and ``plural`` name a count of them, such as "1 livestream" or "726 livestreams".
    """

    key: str
    label: str
    help: str
    singular: str
    plural: str
    selected_by_default: bool = True
    rss_episode_type: RssEpisodeType = RssEpisodeType.FULL
    main: bool = False


class EpisodePublishStatus(StrEnum):
    """Where an episode is in its life at the Source. Each Source names these its own way."""

    SCHEDULED = "scheduled"
    """Announced for a later time, such as an upcoming livestream or premiere."""
    DELAYED = "delayed"
    """Its planned start has passed, but it has not started."""
    LIVE = "live"
    """Live right now."""
    SOURCE_PROCESSING = "source_processing"
    """Finished, but the Source is still preparing the recording."""
    PUBLISHED_PRELIMINARY = "published_preliminary"
    """Published and downloadable, but the Source will still replace the media, such as
    a Daily Wire episode that still opens with its countdown."""
    PUBLISHED_FINAL = "published_final"
    """Published for good."""
    NO_USABLE_MEDIA = "no_usable_media"
    """The Source has nothing usable for it right now; VODLoft keeps checking for a while."""


@dataclass(frozen=True)
class PublishStatusLabel:
    """How a Source names one publish status, with a sentence about what it means there."""

    status: EpisodePublishStatus
    label: str
    help: str


DEFAULT_PUBLISH_STATUS_LABELS: tuple[PublishStatusLabel, ...] = (
    PublishStatusLabel(EpisodePublishStatus.SCHEDULED, "Upcoming", "Announced for a later time."),
    PublishStatusLabel(EpisodePublishStatus.DELAYED, "Delayed", "Its planned start has passed, but it has not started yet."),
    PublishStatusLabel(EpisodePublishStatus.LIVE, "Live", "Live right now."),
    PublishStatusLabel(
        EpisodePublishStatus.SOURCE_PROCESSING, "Processing at the source",
        "Finished, but the source is still preparing the recording.",
    ),
    PublishStatusLabel(
        EpisodePublishStatus.PUBLISHED_PRELIMINARY, "Preliminary version",
        "Published, but the source will still replace the media with a final version.",
    ),
    PublishStatusLabel(EpisodePublishStatus.PUBLISHED_FINAL, "Published", "Published for good."),
    PublishStatusLabel(
        EpisodePublishStatus.NO_USABLE_MEDIA, "No usable media",
        "The source has nothing usable for it right now. VODLoft keeps checking for a while.",
    ),
)


def publish_status_labels_with(*overrides: PublishStatusLabel) -> tuple[PublishStatusLabel, ...]:
    """The default labels, with a Source's own names for some statuses in their place."""
    own = {label.status: label for label in overrides}
    return tuple(own.get(label.status, label) for label in DEFAULT_PUBLISH_STATUS_LABELS)


@dataclass(frozen=True)
class EpisodeMedia:
    """Where the current media of an episode can be fetched from."""

    video_url: str | None
    audio_url: str | None
    drm_protected: bool = False


@dataclass(frozen=True)
class MediaStream:
    """One stream of an episode, for a feed's player.

    VODLoft passes it on, or, where the Site has ``stream_proxy_choice`` and the feed does not
    proxy, sends the player straight to its URL.
    """

    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    """The request headers the URL needs."""
    expires_at: float | None = None
    """When the URL stops working, as a Unix time, when the Source can tell."""
    size_bytes: int | None = None
    ready: bool = True
    """The stream already is what the feed asked for: M4A audio, or MP4 video with sound.
    Audio that is not ready is transcoded to AAC by VODLoft."""
    codecs: str | None = None
    """The stream's codecs as HLS names them, such as ``avc1.640028`` or ``mp4a.40.2``."""
    bitrate: int | None = None
    """Bits per second, on average."""
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class MediaTracks:
    """An episode's video without sound and its audio, as fragmented MP4 files with a segment index,
    from which VODLoft writes HLS playlists and joins MP4 files."""

    video: tuple[MediaStream, ...]
    """One per height the Site streams, from the highest down."""
    audio: MediaStream


@dataclass(frozen=True)
class LiveStream:
    """An episode while it is live, as HLS media playlists that the Site keeps adding to."""

    video: tuple[MediaStream, ...]
    """One playlist per resolution, from the highest down. Each has sound unless ``audio`` is given."""
    audio: MediaStream | None = None
    """The sound as a playlist of its own, shared by every video playlist."""


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
    access: str | None = None
    """The key of the ``Access`` the Source only plays this with, which VODLoft does not have."""
    kind: PlaybackKind = PlaybackKind.URL
    command: tuple[str, ...] = ()


class LinkKind(StrEnum):
    COLLECTION = "collection"
    MOVIE = "movie"
    EPISODE = "episode"
    VIDEO = "video"


@dataclass(frozen=True)
class LinkPreview:
    """A first look at a link, from a faster lookup than ``resolve``: enough to show while the rest loads."""

    title: str
    image_url: str | None = None
    author_name: str | None = None
    site: str | None = None


@dataclass(frozen=True)
class ResolvedLink:
    """What a link points to, with enough to show a preview before anything is added.

    An episode link names the collection it belongs to in ``collection_slug`` and
    ``collection_url`` when the Source can tell, because VODLoft adds whole collections.
    """

    kind: LinkKind
    slug: str
    url: str
    title: str
    description: str | None = None
    image_url: str | None = None
    author_name: str | None = None
    collection_slug: str | None = None
    collection_url: str | None = None
    site: str | None = None
    """The site the link is on, for a Source that serves many sites."""
    drm_protected: bool = False
    """The video is protected by DRM, so it can be added but not downloaded."""
    access: str | None = None
    """The key of the ``Access`` the Source only gives the video with, such as a paid subscription."""
    kind_label: str | None = None
    """What the Source calls this kind of result, such as Channel or Playlist for a collection."""
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
class VideoFormat:
    """One video stream a Source offers for a single video."""

    height: int
    """The smaller side in pixels, as yt-dlp's ``res`` counts it, so a portrait 1080p video is 1080."""
    codec: str
    """``h264``, ``h265``, ``vp9``, ``av1`` or another codec's name."""
    size_bytes: int | None = None
    """The stream's size, exact or estimated, when the Source says."""


@dataclass(frozen=True)
class VideoFormats:
    """What a single video can be downloaded as, for quick download choices."""

    videos: tuple[VideoFormat, ...] = ()
    audio_size_bytes: int | None = None
    """The size of the best audio stream, when the Source says."""
    duration: float | None = None


@dataclass(frozen=True)
class SponsorBlockSegment:
    """One SponsorBlock segment of a video, in seconds."""

    category: str
    start: float
    end: float


@dataclass(frozen=True)
class UpgradeOffer:
    """What a video is offered as right now, for the upgrade check."""

    videos: tuple[VideoFormat, ...] = ()
    subtitle_languages: frozenset[str] = frozenset()
    """The languages of the site's own subtitles, without auto-generated ones."""
    sponsorblock: tuple[SponsorBlockSegment, ...] | None = None
    """The SponsorBlock segments of the asked types, or None when SponsorBlock was not asked."""
    duration: float | None = None
    """The length of the stream the Site serves now, in seconds, for a Site that offers
    ``UpgradeImprovement.LENGTH``; None when it could not be told."""


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
    access: str | None = None
    """The key of the ``Access`` the Source only gives the video with, such as NPO Plus or a
    channel membership. VODLoft indexes it, and downloads it only while it has that access."""
    season: SeasonRef | None = None
    """The collection season a listed episode belongs to, for a Source with real seasons.
    Without one, VODLoft puts the episode in a season per upload year."""
    episode_number: int | None = None
    """The episode's number in its season, when the Source has one."""
    tag: str = MAIN_TAG
    """The key of one of the Source's episode tags."""
    number_text: str | None = None
    """The episode's number exactly as the Source writes it, when that says more than
    ``episode_number``, such as 2460.10 for an extra of episode 2460 at The Daily Wire."""
    publish_status: EpisodePublishStatus = EpisodePublishStatus.PUBLISHED_FINAL
    """Where the video is in its life, for a Source with ``Feature.PENDING_CHECKS``: an upcoming or
    live video has nothing to download yet."""
    scheduled_at: datetime | None = None
    """When an upcoming video is due to start."""


@dataclass(frozen=True)
class ItemRef:
    """One of a collection's items, as a quick check finds it: its slug and its link."""

    slug: str
    url: str


@dataclass(frozen=True)
class ItemRefresh:
    """What a Source says now about items VODLoft already has.

    ``details`` holds the items it could look up. Only the title, description
    and picture are refreshed from them, and a field the Source left out is kept.
    ``removed`` holds the items the Source says it no longer has. ``refused``
    holds, by the key of the access they need, the items the Source would not
    show VODLoft for lack of that access. An item in none of them could not be
    checked this time and stays as it is.
    """

    details: dict[str, VideoDetails] = field(default_factory=dict)
    removed: frozenset[str] = frozenset()
    refused: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionDetails:
    """What VODLoft stores about a collection from a Source with ``Feature.EPISODE_LISTS``."""

    slug: str
    url: str
    title: str
    description: str | None = None
    image_url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    seasons: tuple[SeasonRef, ...] = ()
    """The collection's own seasons, for a Source that has them, so they can be picked
    before the episodes are indexed."""


MIN_NEWEST_EPISODES = 5
"""A Source whose cheapest lookup gives fewer episodes looks a little further, up to this many."""


@dataclass(frozen=True)
class ProgramStatus:
    """The program a Source runs, for a Source with ``Feature.PROGRAM_UPDATES``."""

    name: str
    version: str | None
    last_update_at: datetime | None = None
    last_update_error: str | None = None


@dataclass(frozen=True)
class CookiesStatus:
    """What the Source's cookies file signs in as, shown next to it in the settings."""

    label: str
    ok: bool
    detail: str | None = None


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
    collection_count: int = 0
    """The collections the key speeds up."""
    rescan_units: int = 0
    """What one full re-scan of those collections costs, so the settings can say how often each gets checked."""


@dataclass(frozen=True)
class Access:
    """Something a Site only gives some of its videos with, such as a paid subscription,
    a membership level or a channel membership.

    ``key`` is stored with every media item that needs it, so it never changes. The Source that
    fetches the video tells the key; the Site says what it is called.
    """

    key: str
    label: str
    """What the Site calls it, such as NPO Plus, as the badge on a locked item shows it."""
    description: str
    """One sentence on who can watch what needs it, such as "Only NPO Plus subscribers can watch this"."""


class ApiKeyRejected(ValueError):
    """The service does not accept the key; the message says what to do about it."""

    def __init__(self, message: str, fix_url: str | None = None):
        super().__init__(message)
        self.fix_url = fix_url


ANY_DOMAIN = "*"


@dataclass(frozen=True)
class Site:
    """One website as the user knows it, such as YouTube or The Daily Wire, whichever Source fetches it.

    ``key`` is stored with every collection and video, so it never changes. One Site can
    span several domains, such as youtube.com and youtu.be; ``domains`` holds the ones known.
    """

    key: str
    name: str
    domains: tuple[str, ...] = ()
    stream_methods: frozenset[StreamMethod] = frozenset()
    """How RSS feeds can stream the Site's episodes straight from it, without downloading them
    first. A Site with none only serves downloads."""
    stream_video_heights: tuple[int, ...] = ()
    """The resolutions the Site streams video at, for a Site that ``streams``."""
    stream_file_height: int | None = None
    """The one resolution of ``stream_video_heights`` the Site has as an MP4 file with sound. The
    others are separate ``media_tracks``, which VODLoft joins into an MP4 file before a feed plays it."""
    stream_proxy_choice: bool = False
    """The Site's streams play for any address, so a feed can send podcast apps straight to them
    instead of passing them through VODLoft."""
    downloads: DownloadOptions = DownloadOptions()
    upgrade_checks: UpgradeChecks = UpgradeChecks()
    settings: SiteSettings = field(default_factory=SiteSettings, hash=False)
    """Which settings the Site shows in Settings and on its Download Profiles, and its presets."""
    accesses: tuple[Access, ...] = ()
    """What the Site only gives some of its videos with, such as NPO Plus or a channel membership,
    by the keys its Sources tell."""

    def access(self, key: str | None) -> Access | None:
        """One of ``accesses`` by its key."""
        return next((access for access in self.accesses if access.key == key), None)

    @property
    def streams(self) -> bool:
        return bool(self.stream_methods)


def link_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def domain_site(url: str) -> Site:
    """The Site of a link that belongs to no known site: its own domain, without www."""
    host = link_host(url).removeprefix("www.")
    return Site(f"generic:{host}", host, (host,))


def names_a_podcast(name: str | None) -> bool:
    """True when a collection's name or slug says it is a podcast, like "PBD Podcast" or "the-podcasts"."""
    return "podcast" in (name or "").lower()


def on_domain(host: str, domain: str) -> bool:
    """True when the host is the domain or a subdomain of it."""
    return host == domain or host.endswith(f".{domain}")


class Source(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    domains: ClassVar[tuple[str, ...]]
    features: ClassVar[frozenset[Feature]]
    episode_tags: ClassVar[tuple[EpisodeTag, ...]] = (
        EpisodeTag(MAIN_TAG, "Episode", "An episode of the collection", "episode", "episodes", main=True),
    )
    """Every tag the Source gives episodes, the main one first."""
    cookies_help: ClassVar[str | None] = None
    """What a cookies file does for this Source, for a Source with ``Feature.COOKIES``."""
    sites: ClassVar[tuple[Site, ...]] = ()
    """The Sites this Source is made for, such as The Daily Wire, with what this Source offers on
    each. A Source that serves many sites, as yt-dlp does, names none and tells them apart in
    ``site_for``. Another Source never uses these: on a Site it has no contract for, a Source
    offers a Site's defaults."""
    sites_label: ClassVar[str | None] = None
    """What the Source downloads from, in a few words, when its name does not say so, such as
    "YouTube, and many more" for yt-dlp."""
    search_label: ClassVar[str | None] = None
    """What the search button names, when that is not the Source's name, such as YouTube for yt-dlp."""
    publish_status_labels: ClassVar[tuple[PublishStatusLabel, ...]] = DEFAULT_PUBLISH_STATUS_LABELS
    """What the Source calls each publish status, every status included."""
    kind_names: ClassVar[Mapping[LinkKind, str]] = MappingProxyType({})
    """What the Source calls a kind of media where its own word differs from VODLoft's, such as
    Show for a Daily Wire collection. VODLoft uses these words only where it shows the Source's
    own catalogue, and a search result's ``kind_label`` still wins for that one result."""

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def handles(self, url: str) -> bool:
        """True when the link's host is one of this Source's domains or a subdomain of one."""
        if ANY_DOMAIN in self.domains:
            return True
        host = link_host(url)
        return any(on_domain(host, domain) for domain in self.domains)

    @property
    def download_options(self) -> DownloadOptions:
        """What a Local Media Profile can choose for this Source's media: what any of its Sites offers.
        A Source that names no Sites downloads from sites that offer the defaults."""
        return DownloadOptions.combined(site.downloads for site in self.sites)

    def site_for(self, url: str) -> Site | None:
        """This Source's own contract for the Site of a link, told without a network request, or None
        when this Source has none for it."""
        host = link_host(url)
        return next((site for site in self.sites if any(on_domain(host, domain) for domain in site.domains)), None)

    def site_of(self, site_key: str) -> Site | None:
        """This Source's own contract for the Site with the key, or None when it has none. A Source
        that tells its Sites apart in ``site_for`` implements it."""
        return next((site for site in self.sites if site.key == site_key), None)

    def collection_ref(self, url: str) -> str | None:
        """The id one of this Source's ``sites`` gives the collection at the link, told from the
        link alone, or None when it is not a collection's link. A Source that names Sites implements it."""
        return None

    def episode_tags_for(self, url: str | None) -> tuple[EpisodeTag, ...]:
        """The tags episodes of the collection at this link can get, or all of them without a link."""
        return self.episode_tags

    def episode_tag(self, key: str | None) -> EpisodeTag | None:
        return next((tag for tag in self.episode_tags if tag.key == key), None)

    @abstractmethod
    def resolve(self, url: str) -> ResolvedLink | None:
        """Say what a link points to, or None when this Source does not recognise it."""

    def preview(self, url: str) -> LinkPreview | None:
        """A title and image for a link, faster than ``resolve``, or None when this Source has no faster way."""
        return None

    def first_frame(self, url: str, image_url: str | None) -> bytes | None:
        """A JPEG from the start of a video whose own picture, ``image_url``, is missing.

        None when the picture is there, or when this Source cannot take a frame.
        """
        return None

    def episode_media(
        self, *, slug: str, members_only: bool, interactive: bool = False,
    ) -> EpisodeMedia:
        """Look up the current media URLs of an episode. Only Sources without
        ``Feature.PAGE_STREAMS`` implement it; the others play each episode with ``video_playback``."""
        raise NotImplementedError(f"{self.name} plays its episodes with video_playback")

    def media_stream(self, url: str, *, audio: bool, use_cookies: bool = True) -> MediaStream | None:
        """The audio or video stream of a listed episode, for an RSS feed that streams it. Only Sources
        with ``Feature.PAGE_STREAMS`` whose Site ``streams`` implement it. None when the episode has no
        such stream; ``use_cookies`` as for ``video_playback``."""
        raise NotImplementedError(f"{self.name} cannot stream episodes")

    def media_tracks(self, url: str, *, use_cookies: bool = True) -> MediaTracks | None:
        """The video and audio tracks of a listed episode, for an RSS feed that streams it as HLS or joins
        its MP4. Only Sources with ``Feature.PAGE_STREAMS`` whose Site streams ``StreamMethod.HLS``
        implement it. None when the episode has no such tracks."""
        raise NotImplementedError(f"{self.name} cannot stream episodes as tracks")

    def live_stream(self, url: str, *, use_cookies: bool = True) -> LiveStream | None:
        """A listed episode's HLS playlists while it is live, for an RSS feed. Only Sources with
        ``Feature.PAGE_STREAMS`` whose Site streams ``StreamMethod.LIVE`` implement it. None when the
        episode is not live."""
        raise NotImplementedError(f"{self.name} cannot stream live episodes")

    def movie_playback(
        self, *, movie_slug: str, title: str, duration: float | None,
        extra_slug: str | None = None, is_extra: bool = False, is_official_trailer: bool = False,
    ) -> Playback:
        """Resolve the playable URL of a movie or one of its extras. Only Sources with ``Feature.MOVIES`` implement it."""
        raise NotImplementedError(f"{self.name} has no movies")

    def video_details(self, url: str) -> VideoDetails:
        """Look up a single video. Only Sources with ``Feature.VIDEOS`` implement it."""
        raise NotImplementedError(f"{self.name} has no single videos")

    def video_formats(self, url: str) -> VideoFormats:
        """The streams a single video is offered in. Only Sources with ``Feature.FORMAT_CHOICES`` implement it."""
        raise NotImplementedError(f"{self.name} offers no format choices")

    def upgrade_offer(self, url: str, *, sponsorblock_categories: Sequence[str] = ()) -> UpgradeOffer:
        """What a video is offered as now, asking SponsorBlock for the given segment types.
        Only Sources whose Sites offer ``upgrade_checks`` implement it."""
        raise NotImplementedError(f"{self.name} has no upgrade checks")

    def video_playback(self, *, slug: str, url: str, use_cookies: bool = True) -> Playback:
        """Resolve the playable URL of a single video, or of an episode of a collection
        from ``list_episodes``. Only Sources with ``Feature.VIDEOS`` or
        ``Feature.EPISODE_LISTS`` implement it. ``use_cookies`` False leaves the cookies file out,
        for a Source with ``Feature.OPTIONAL_COOKIES``."""
        raise NotImplementedError(f"{self.name} has no single videos")

    def collection_details(self, url: str) -> CollectionDetails:
        """Look up a collection. Only Sources with ``Feature.EPISODE_LISTS`` implement it."""
        raise NotImplementedError(f"{self.name} does not list episodes")

    def list_episodes(self, url: str, *, known: frozenset[str]) -> Iterator[VideoDetails]:
        """The collection's episodes whose slugs are not in ``known``.

        An episode that cannot be looked up right now is left out, so a later
        scan tries it again.
        """
        raise NotImplementedError(f"{self.name} does not list episodes")

    def newest_episodes(self, url: str) -> list[VideoDetails]:
        """The newest episodes of the collection at this link, from whatever lookup costs the Source least,
        such as one page of its API or an RSS feed, newest first, and at least ``MIN_NEWEST_EPISODES`` when it has them.
        VODLoft shows them as examples while the collection is added, and never saves them.
        Only Sources with ``Feature.COLLECTIONS`` implement it."""
        raise NotImplementedError(f"{self.name} has no collections")

    def latest_items(self, url: str) -> list[ItemRef]:
        """The collection's newest items, newest first. Only Sources with ``Feature.QUICK_CHECK`` implement it."""
        raise NotImplementedError(f"{self.name} has no quick check")

    def item_details(self, items: Sequence[ItemRef]) -> dict[str, VideoDetails | None]:
        """Details per item slug. None means the item is gone, private or not
        finished yet, so a later check tries it again. ``Feature.QUICK_CHECK`` only."""
        raise NotImplementedError(f"{self.name} has no quick check")

    def refresh_items(self, url: str, items: Sequence[ItemRef]) -> ItemRefresh:
        """What the Source says now about these items of the collection at ``url``.
        Only Sources with ``Feature.CATALOGUE_REFRESH`` implement it."""
        raise NotImplementedError(f"{self.name} cannot refresh a collection's items")

    def refresh_metadata(self, items: Sequence[ItemRef]) -> ItemRefresh:
        """What the Source says now about these items, which can be of any collection or
        none. Only Sources with ``Feature.METADATA_REFRESH`` implement it."""
        raise NotImplementedError(f"{self.name} cannot refresh items")

    def check_pending(self, items: Sequence[ItemRef]) -> ItemRefresh:
        """What the Source says now about upcoming and live items, with their publish status.
        ``removed`` holds the items it clearly no longer has, such as a cancelled stream.
        Only Sources with ``Feature.PENDING_CHECKS`` implement it."""
        raise NotImplementedError(f"{self.name} cannot check pending items")

    def quick_check_minutes(self, collections: Sequence[tuple[str, int]]) -> int:
        """How often each of these collections, given as link and episode count, can
        get a quick check. ``Feature.QUICK_CHECK`` only."""
        raise NotImplementedError(f"{self.name} has no quick check")

    def search(self, query: str) -> SearchResults:
        """Collections and videos whose name matches the query. Only Sources with ``Feature.SEARCH`` implement it."""
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

    def import_sign_in(self, records: Mapping[str, str]) -> None:
        """Take over the sign-in another program kept, such as WireLoft's, for a Source with
        ``Feature.LOGIN``: each record in this Source's own stored form, by its store key."""
        raise NotImplementedError(f"{self.name} has no sign-in to take over")

    def needs_cookies(self, error: str) -> bool:
        """True when a failed download says signing in would help, for a Source with ``Feature.OPTIONAL_COOKIES``."""
        return False

    def has_cookies(self) -> bool:
        """True when a cookies file is stored. Only Sources with ``Feature.COOKIES`` implement it."""
        raise NotImplementedError(f"{self.name} takes no cookies file")

    def save_cookies(self, content: bytes) -> None:
        """Store a cookies file that every lookup and download uses. Raises ValueError for a file it cannot use."""
        raise NotImplementedError(f"{self.name} takes no cookies file")

    def remove_cookies(self) -> None:
        raise NotImplementedError(f"{self.name} takes no cookies file")

    def cookies_status(self) -> CookiesStatus | None:
        """What the stored cookies file signs in as, for a Source that can tell."""
        return None

    @property
    def download_streams(self) -> int | None:
        """How many downloads from this Source may run at once, when the Source limits that,
        such as the streams an account may play at the same time."""
        return None

    def has_access(self, key: str) -> bool | None:
        """True when VODLoft can download what needs this access, False when it cannot, and None
        when only a download can tell, such as for a channel membership a cookies file may have."""
        return None

    def refused_access(self, error: str) -> str | None:
        """The key of the access a failed download or lookup says the video needs, or None
        when the failure has nothing to do with access."""
        return None

    def current_access(self, *, slug: str, url: str) -> str | None:
        """The key of the access the video needs right now, or None when anyone can download it.
        Raises when the Source could not be asked."""
        try:
            return self.video_details(url).access
        except Exception as exc:
            if (key := self.refused_access(str(exc))) is not None:
                return key
            raise

    def problems(self) -> list[SourceProblem]:
        """What the user should fix about this Source right now."""
        return []

    def api_status(self, collections: Sequence[tuple[str, int]] = ()) -> ApiStatus:
        """The API key and today's quota. ``collections`` are the link and episode count of
        each of this Source's collections. Only Sources with ``Feature.API_KEY`` implement it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def save_api_key(self, key: str) -> None:
        """Test the key with one call and store it. Raises ApiKeyRejected when the service does not accept it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def test_api_key(self) -> None:
        """Test the stored key with one call. Raises ApiKeyRejected when the service does not accept it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def remove_api_key(self) -> None:
        raise NotImplementedError(f"{self.name} takes no API key")
