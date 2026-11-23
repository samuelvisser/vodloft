"""The contract every Source implements.

The rest of VODLoft talks to a service only through these types, never through
a Source's own client, records or errors. The contract only holds what has a
caller today; methods are added together with the feature that needs them.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar
from urllib.parse import urlsplit

from progress_plan import PlanTracker

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
    """Finding collections and videos by name on each of the Source's ``search_sites``, with ``search``."""
    PROGRAM_UPDATES = "program_updates"
    COOKIES = "cookies"
    """The Source signs in on a Site with the Site's own cookies file (``sources.cookies``)."""
    OPTIONAL_COOKIES = "optional_cookies"
    """Downloads work with or without the Site's cookies file, so each Collection chooses when to use it, and
    ``needs_cookies`` tells from a failed download that the cookies file would help."""
    API_KEY = "api_key"
    """An optional key for the service's own API, which makes catalogue lookups faster."""
    SITE_API = "site_api"
    """A Site's own free API, set up with credentials the user registers there (``Site.site_api``), with
    ``site_api_status``, ``save_site_api``, ``test_site_api`` and ``remove_site_api``."""
    OWN_SEASONS = "own_seasons"
    """The Source's collections have seasons of the Site's own, such as a show's seasons, which the user can't remove.
    The seasons VODLoft makes, such as a season per year, the user can."""
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
    CREATORS = "creators"
    """Looking up a creator, with ``creator_details``: who they are and the sections
    their page offers. Only a Site with ``creators`` offers them."""
    PENDING_CHECKS = "pending_checks"
    """Listing upcoming and live videos with their publish status, and looking them up again
    with ``check_pending`` until they are published. VODLoft shows them, but never records one
    while it is live."""
    LINK_COLLECTIONS = "link_collections"
    """A collection can hold only what lists the user picks have, from any of the Source's Sites, as its link seasons:
    the Source lists them with ``list_items`` and looks their videos up with ``item_details``, and such a collection
    needs no link of its own."""
    CHAPTERS = "chapters"
    """A video's chapters come with its details (``VideoDetails.chapters``), and a download can keep one
    stretch of a video, so a collection can split each video into a part per chapter."""


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

    def for_audio_only(self) -> UpgradeChecks:
        """The same checks for a Site with sound only, which has no resolution, video codec or subtitles."""
        video = {UpgradeImprovement.RESOLUTION, UpgradeImprovement.CODEC, UpgradeImprovement.SUBTITLES}
        return UpgradeChecks(tuple(improvement for improvement in self.improvements if improvement not in video))


@dataclass(frozen=True)
class Names:
    """A word in its singular and plural forms, in lower case and without an article, such as album and albums.
    ``article`` is only set where the first letter does not tell it, as for an hour."""

    singular: str
    plural: str
    article: str = ""

    @property
    def a(self) -> str:
        """The word with its article, such as an album or a playlist."""
        return f"{self.article or ('an' if self.singular[:1] in 'aeiou' else 'a')} {self.singular}"

    @classmethod
    def joined(cls, names: Iterable[Names]) -> Names:
        """One name for several, such as "album or playlist" and "albums and playlists" for SoundCloud's lists, or
        "album, playlist or list" for three. It starts with the first one, and so takes its article."""
        names = list(names)
        return cls(_joined([name.singular for name in names], "or"), _joined([name.plural for name in names], "and"),
                   names[0].article if names else "")


def _joined(words: list[str], conjunction: str) -> str:
    words = list(dict.fromkeys(words))
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} {conjunction} {words[-1]}"


class SectionKind(StrEnum):
    """What one part of a creator is, whatever the Site calls it."""

    FEED = "feed"
    """Grows forever, ordered by date: Videos, Shorts, Live, Reels."""
    LIST = "list"
    """Finite and curated, with a title and artwork of its own, that can be a season of a collection: a playlist or
    an album. Each Source names lists in its own words."""
    SHOW = "show"
    """A show with seasons of its own, such as a Daily Wire show: it grows like a feed, has a title and artwork of its
    own, and is always a collection of its own."""
    ITEM = "item"
    """One movie or video, such as a movie on a Daily Wire host's page."""


SECTION_KIND_NAMES = {
    SectionKind.FEED: Names("feed", "feeds"),
    SectionKind.LIST: Names("list", "lists"),
    SectionKind.SHOW: Names("show", "shows"),
    SectionKind.ITEM: Names("video", "videos"),
}
"""VODLoft's own word for each kind of section, for a kind a Site names no section type for."""


class SectionRole(StrEnum):
    """What a section holds, which only steers the defaults when a creator is added."""

    MAIN = "main"
    SHORT = "short"
    LIVE = "live"


LIST_TYPE = "list"
"""The key of VODLoft's own kind of list, the playlist, which most Sites have."""


MAIN_TAG = "ep"


@dataclass(frozen=True)
class SectionType:
    """One type of section a Site's creators have, such as a feed, an album or a playlist on SoundCloud, and what
    the Site calls it. ``key`` is stored with each section and with the settings for what happens with a new list or
    show, so it never changes."""

    key: str
    kind: SectionKind
    names: Names
    """What the Site calls a section of the type. A channel has one section of each type of feed, which is named
    after its type, such as Shorts, and holds what it names, such as "12 shorts"."""
    albums: bool = False
    """The type of list that best describes an artist's albums. A new channel collection on a Site with such types
    adds new lists of those types and skips the others; on any other Site, it adds every type."""
    role: SectionRole = SectionRole.MAIN
    """What a feed of the type holds: a channel's main videos, or its Shorts or livestreams."""
    episode_tag: str = MAIN_TAG
    """The key of the Site's episode tag that the videos of a feed of the type get, such as YouTube's short, by which
    VODLoft tells a feed's videos apart in a collection that lists several feeds. The main feed's videos get the
    main tag."""

    @property
    def title(self) -> str:
        """The name of the one section of a feed type, such as Shorts."""
        plural = self.names.plural
        return plural[:1].upper() + plural[1:]

    @property
    def feed_ref(self) -> str:
        """The ref of the one section of a feed of the type, by which a collection's feeds setting names it: its
        key, unless its Source names it otherwise."""
        return self.key


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
    hls_heights: tuple[int, ...] = ()
    """The resolutions of the Site's HLS bundle, which keeps several together; none when it has no bundle."""
    subtitles: bool = False
    """The Site's media has subtitles a profile can save."""
    quality_choices: bool = False
    """Codecs, container, quality goal, audio format and audio language pick the version that is
    downloaded. Only a Site downloaded with a program that chooses among versions, such as yt-dlp, turns it
    on; a Site with fixed versions, such as The Daily Wire, has nothing to choose."""
    info_file: bool = False
    """The program that downloads the Site's media writes an info file about each video, as yt-dlp does, which a
    profile can save beside the media."""

    @property
    def hls_bundle(self) -> bool:
        """Whether a profile can keep the Site's media as an HLS bundle."""
        return bool(self.hls_heights)

    def for_audio_only(self) -> DownloadOptions:
        """The same options for a Site with sound only: no resolutions, HLS bundle or subtitles, only its audio."""
        return replace(self, video_heights=(), hls_heights=(), subtitles=False)

    @classmethod
    def combined(cls, options: Iterable[DownloadOptions]) -> DownloadOptions:
        """Everything that at least one of these offers."""
        options = list(options)
        if not options:
            return cls()
        return cls(
            video_heights=tuple(sorted({height for option in options for height in option.video_heights})),
            audio_only=any(option.audio_only for option in options),
            hls_heights=tuple(sorted({height for option in options for height in option.hls_heights})),
            subtitles=any(option.subtitles for option in options),
            quality_choices=any(option.quality_choices for option in options),
            info_file=any(option.info_file for option in options),
        )


class RssEpisodeType(StrEnum):
    """The podcast episode type an RSS feed gives an episode."""

    FULL = "full"
    TRAILER = "trailer"
    BONUS = "bonus"



@dataclass(frozen=True)
class EpisodeTag:
    """A kind of episode a Source tells apart, such as a YouTube Short.

    The key is the first part of an episode's identifier (``short.12``) and what
    Download and RSS profiles select. Episodes with the ``main`` tag follow the
    collection's numbering scheme; every other tag counts on its own across the collection.
    ``names`` name a count of them, such as "1 livestream" or "726 livestreams"; ``label`` is the tag itself, such as
    Ep. Extra.
    """

    key: str
    label: str
    help: str
    names: Names
    selected_by_default: bool = True
    rss_episode_type: RssEpisodeType = RssEpisodeType.FULL
    main: bool = False


VIDEO_TAGS = (EpisodeTag(MAIN_TAG, "Video", "A normal video", Names("video", "videos"), main=True),)
"""VODLoft's own episode tags: every video is a normal one."""
TRACK_TAGS = (EpisodeTag(MAIN_TAG, "Track", "A normal track", Names("track", "tracks"), main=True),)
"""VODLoft's own episode tags on a Site with sound only."""
_VIDEO_DOWNLOADS = DownloadOptions()


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


class ReleaseDate(StrEnum):
    """Which moment a Source's release date of an item marks."""

    START = "start"
    """When the item came out or its stream began, as YouTube gives it: VODLoft calls it Released."""
    END = "end"
    """When the item was finished and put up, such as after a livestream ended, as The Daily Wire
    gives it: VODLoft calls it Published."""


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
    CREATOR = "creator"


LINK_KIND_NAMES = {
    LinkKind.COLLECTION: Names("collection", "collections"),
    LinkKind.MOVIE: Names("movie", "movies"),
    LinkKind.EPISODE: Names("episode", "episodes"),
    LinkKind.VIDEO: Names("video", "videos"),
    LinkKind.CREATOR: Names("creator", "creators"),
}
"""VODLoft's own word for each kind of media a link can be."""


@dataclass(frozen=True)
class SectionRef:
    """One section of a creator. ``ref`` is the Site's own id for it, which stays the same when it is renamed.
    ``type`` is one of the Site's section types, which says what kind of section it is and what it holds; a feed is
    named after its type, and only a list, show or item has a ``title`` of its own."""

    ref: str
    url: str
    type: SectionType
    title: str = ""
    item_count: int | None = None
    image_url: str | None = None
    description: str | None = None
    access: str | None = None
    """The key of the ``Access`` the section needs, as for videos."""
    """A list with seasons of its own, such as a Daily Wire show, keeps them."""
    year: str | None = None
    """The year an album came out."""

    def __post_init__(self) -> None:
        if self.kind is SectionKind.FEED or not self.title:
            object.__setattr__(self, "title", self.type.title)

    @property
    def kind(self) -> SectionKind:
        return self.type.kind

    @property
    def role(self) -> SectionRole:
        return self.type.role


@dataclass(frozen=True)
class CreatorDetails:
    """A creator on one Site: who they are, and the sections their page offers.

    ``ref`` is the Site's own id for the creator. ``url`` is None for a creator the Site has no page of its own for,
    such as a Daily Wire host, which is only found through VODLoft's Browse page.
    """

    ref: str
    url: str | None
    title: str
    handle: str | None = None
    description: str | None = None
    avatar_url: str | None = None
    banner_url: str | None = None
    links: tuple[str, ...] = ()
    """The creator's own links, such as their website."""
    facts: tuple[str, ...] = ()
    """Short facts, such as "1.2M subscribers"."""
    sections: tuple[SectionRef, ...] = ()
    music: bool = False
    """A music artist, whose lists are albums: their collections are Music collections. Where the Site can't be sure,
    it is the Source's guess, which the user can change before the creator is added."""
    music_known: bool = False
    """The Site makes ``music`` certain: Bandcamp only has artists, and The Daily Wire only hosts."""
    music_reason: str | None = None
    """Why the Source took the creator for a music artist, when it guessed so, such as "It has releases on YouTube
    Music"."""


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
class Chapter:
    """A stretch of a video the uploader named, in seconds from its start."""

    title: str
    start: float
    end: float


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
    chapters: tuple[Chapter, ...] | None = None
    """The video's chapters, for a Source with ``Feature.CHAPTERS``: empty when it has none, and None when the
    listing did not say, so ``video_details`` has to be asked."""


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
    show VODLoft for lack of that access, and ``open`` the items it saw anyone
    may watch now. An item in none of them could not be checked this time and
    stays as it is, and a detail that leaves out the access it needs says nothing
    about whether it is open.
    """

    details: dict[str, VideoDetails] = field(default_factory=dict)
    removed: frozenset[str] = frozenset()
    refused: dict[str, str] = field(default_factory=dict)
    open: frozenset[str] = frozenset()


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
    list_type: str | None = None
    """The key of the Site's type of list the link is, such as an album or a playlist on SoundCloud, for a Site whose
    lists come in several types that their links don't tell apart."""


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
    """What a Site's cookies file signs in as, shown next to it in the settings."""

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
class QuickCheckCollection:
    """A collection that gets quick checks, as a Source needs it to tell what checking it costs."""

    url: str
    episode_count: int = 0
    feeds: frozenset[str] | None = None
    """The feeds of its channel the collection lists, or None for all that its link lists."""
    lists_only: bool = False
    """It holds only the seasons of its lists, so each check reads every one of its lists again."""
    least_minutes: int = 0
    """How long the collection waits between two checks anyway, such as six hours when it is checked less often."""


@dataclass(frozen=True)
class QuickCheckCost:
    """What one quick check of a collection costs, and how long the collection waits between checks anyway."""

    units: int
    least_minutes: int = 0
    feeds: int = 0
    """The feeds a check reads, each a call; a collection that follows all of its channel's feeds reads them as one."""


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
    check_costs: tuple[QuickCheckCost, ...] = ()
    """What a quick check of each of those collections costs."""


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


@dataclass(frozen=True)
class ApiField:
    """One value a Site's API takes, such as its client ID, and whether it is a secret that is never shown again."""

    key: str
    label: str
    secret: bool = False


@dataclass(frozen=True)
class GuideStep:
    """One step of how to get something, with a button to the page it is done on."""

    text: str
    button: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class SiteApi:
    """A free API of a Site's own that the user can register VODLoft with, such as Twitch's, and what it makes
    better. VODLoft works on the Site without it."""

    name: str
    """What the Site calls it, such as Twitch API."""
    fields: tuple[ApiField, ...]
    benefits: str
    """What it makes better, as a sentence."""
    steps: tuple[GuideStep, ...] = ()
    """How to register VODLoft there and get the values of its ``fields``."""
    searches: bool = False
    """The Site's search goes through the API, so VODLoft only searches the Site once it is set up."""


@dataclass(frozen=True)
class Retention:
    """A Site that removes its media itself after a while, such as Twitch its past broadcasts."""

    kept_for: timedelta
    """The least time the Site keeps media after it is published. Media that leaves the Site sooner is missing, as
    on any other Site."""
    description: str
    """How the Site removes its media, as a sentence."""


@dataclass(frozen=True)
class SiteApiStatus:
    """Which values of a Site's API are set, each by its last few characters or, for one that is not secret, as it
    is; and the last problem the Site reported with them."""

    hints: Mapping[str, str]
    problem: str | None = None

    @property
    def set_up(self) -> bool:
        return bool(self.hints)


class ApiKeyRejected(ValueError):
    """The service does not accept the key; the message says what to do about it, and ``field`` which of a Site's
    API values it is about, when it is about one."""

    def __init__(self, message: str, fix_url: str | None = None, field: str | None = None):
        super().__init__(message)
        self.fix_url = fix_url
        self.field = field


ANY_DOMAIN = "*"


class ChannelSeason(StrEnum):
    """What the one season of a channel collection's own videos holds, beside the seasons of its lists."""

    EVERYTHING = "everything"
    """Every video of its feeds, also the ones a list has, so the season is the whole channel. It is named after the
    Site's channel collections, such as Channel on YouTube."""
    UNLISTED = "unlisted"
    """Only the videos of its feeds that none of its lists has, named as the Site calls such videos
    (``Site.loose_season``), such as Videos, or Singles in a Music collection."""


class ProfileSeasons(StrEnum):
    """Which seasons a new Download Profile of a seasonal collection picks, beside the upcoming ones."""

    NEWEST = "newest"
    """The newest season only, as for a show whose seasons are the Site's own."""
    ALL = "all"
    """Every season, as for an artist whose albums VODLoft makes seasons of."""


def initials_of(name: str) -> str:
    """A Site's name in at most two capitals, for a Site whose contract names none: the first letters of its first two
    words, such as SC for SoundCloud or DW for The Daily Wire, or the first two letters of a one-word name. A name that
    is a domain, such as example.com, goes by the part before its ending: EX."""
    if "." in name and " " not in name.strip():
        name = name.strip().lower().removeprefix("www.").split(".")[0]
    words = [word for part in re.findall(r"[A-Za-z0-9]+", name) for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+", part)]
    if len(words) > 2 and words[0].lower() == "the":
        words = words[1:]
    letters = "".join(word[0] for word in words[:2]) if len(words) > 1 else "".join(words)[:2]
    return letters.upper()


@dataclass(frozen=True)
class Site:
    """One website as the user knows it, such as YouTube or The Daily Wire, whichever Source fetches it.

    ``key`` is stored with every collection and video, so it never changes. One Site can
    span several domains, such as youtube.com and youtu.be; ``domains`` holds the ones known.
    """

    key: str
    name: str
    domains: tuple[str, ...] = ()
    icon: str | None = None
    """The Font Awesome icon of the Site, as ``prefix:name``, such as ``fab:youtube``: Font Awesome's brand icon of the
    Site where it has one, or a custom icon in VODLoft's Kit (``fak:``, drawn in ``ui/src/icons/custom``) where Font
    Awesome has none. VODLoft shows it where the Site's name does not fit, such as a creator's links on a phone.
    A Site without one shows a globe with its ``initials``."""
    initials: str = ""
    """The Site's name in at most two letters, such as YT for YouTube, shown beside a globe where the Site has no
    ``icon``. Left out, they are made from its name (``initials_of``)."""
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
    video_output_help: Mapping[str, str] = field(default_factory=dict, hash=False)
    """What a feed's video output does on this Site, where it differs from the usual explanation, by
    the output's value (``audio_hls``, ``audio_mp4``, ``mp4`` or ``mp4_hls``)."""
    downloads: DownloadOptions = _VIDEO_DOWNLOADS
    """What a Local Media Profile can choose for the Site's media. Left out on a Site that is ``audio_only``, it
    offers only audio."""
    upgrade_checks: UpgradeChecks = UpgradeChecks()
    episode_tags: tuple[EpisodeTag, ...] = VIDEO_TAGS
    """Every tag the Site gives episodes, the main one first, such as YouTube's Videos, Shorts and Livestreams. Left
    out, every episode is a normal video, or a track on a Site that is ``audio_only``."""
    settings: SiteSettings = field(default_factory=SiteSettings, hash=False)
    """Which settings the Site shows in Settings and on its Download Profiles, and its presets."""
    takes_cookies: bool = True
    """Sources sign in on the Site with its cookies file. A Site with a sign-in of its own that cookies
    can't stand in for, such as The Daily Wire, has none."""
    cookies_help: str | None = None
    """How to export a cookies file that signs in on the Site, when the Site needs more than the usual."""
    takes_api_key: bool = False
    """A Source with ``Feature.API_KEY`` that fetches the Site uses its key there, such as yt-dlp's
    YouTube Data API key on YouTube."""
    site_api: SiteApi | None = None
    """The Site's own free API that the user can register VODLoft with, through a Source with ``Feature.SITE_API``,
    such as Twitch's for its search."""
    accesses: tuple[Access, ...] = ()
    """What the Site only gives some of its videos with, such as NPO Plus or a channel membership,
    by the keys its Sources tell."""
    creators: bool = False
    """The Site has creators VODLoft can add, through a Source with ``Feature.CREATORS``."""
    audio_only: bool = False
    """The Site has sound only, such as Bandcamp's tracks. A Music collection on it holds tracks rather than music
    videos, and what the Site leaves out of ``downloads`` and ``episode_tags`` is for sound: tracks, downloaded as
    audio."""
    creator_names: Names = Names("creator", "creators")
    """What the Site calls a creator, such as host on The Daily Wire or artist on Bandcamp. VODLoft names the Site's
    creators by it everywhere."""
    channel_collection_names: Names = Names("collection", "collections")
    """What the Site calls a collection of a channel, a creator's page of all their uploads, such as a channel on
    YouTube or a show on The Daily Wire."""
    list_collection_names: Names = Names("collection", "collections")
    """What the Site calls a collection of one of its lists, such as a playlist on YouTube."""
    channel_season_names: Names | None = None
    """What the Site calls the seasons of a channel collection, such as playlists on YouTube. Left out, they are
    named as the collection's type names its seasons."""
    list_season_names: Names | None = None
    """What the Site calls the seasons of a list collection, such as groups on SoundCloud. Left out, they are named as
    the collection's type names its seasons."""
    custom_season_names: Names = Names("list", "lists")
    """What VODLoft calls the seasons of a custom collection on the Site, whose seasons are the lists the user gave
    it, unless the collection's type names its seasons itself. A custom collection is on the Site of its first list."""
    channel_season: ChannelSeason | None = None
    """What a new channel collection's channel season holds. Left out, the whole channel, or on a Site that is
    ``audio_only`` only what is in none of its lists, such as an artist's singles."""
    section_types: tuple[SectionType, ...] = (
        SectionType("videos", SectionKind.FEED, Names("video", "videos")),
        SectionType(LIST_TYPE, SectionKind.LIST, Names("playlist", "playlists")),
    )
    """Every type of section the Site's creators have, in the order VODLoft shows them, such as YouTube's Videos,
    Live and Shorts and its playlists, or The Daily Wire's shows and movies. Each section a Source finds is one of
    them, by its key; VODLoft names sections and keeps settings by them everywhere."""
    link_seasons: bool = False
    """A collection made from a creator's channel can make the channel's lists, such as its playlists, its seasons:
    link seasons, through its Source's ``is_creator_page``, ``season_lists`` and ``list_items``."""
    every_list_a_season: bool = True
    """A new channel collection makes every one of the channel's lists a season, as a channel shows all its lists.
    A Site whose contract says False makes only the lists the user picks seasons."""
    whole_lists: bool = True
    """A new channel collection puts a video in every list season that has it, so each list is whole. A Site whose
    contract says False puts a video in the first of them only, unless the collection's type says otherwise."""
    profile_seasons: ProfileSeasons | None = None
    """Which seasons a new Download Profile of a collection on the Site picks, beside the upcoming ones. Left out, it
    follows where the seasons come from: the newest where they are the Site's own (a Source with
    ``Feature.OWN_SEASONS``), every season where VODLoft makes them from lists, years or anything else."""
    loose_season: str | None = None
    """What VODLoft calls the season it makes itself of the videos in none of a collection's link seasons. Left out,
    Videos, or on a Site that is ``audio_only`` Singles. A collection type can name it itself
    (``CollectionContract.loose_season``)."""
    share_hosts: tuple[str, ...] = ()
    """The hosts of the short links the Site's apps share, such as SoundCloud's on.soundcloud.com, which redirect to
    the Site's own pages. Their links are the Site's, and VODLoft follows them to the page they stand for."""
    searchable: bool = False
    """VODLoft can find the Site's collections and videos by name, through a Source with ``Feature.SEARCH``."""
    costly_search: bool = False
    """Each search of the Site costs something, such as API quota or a slow lookup, so the search page searches when
    asked instead of while the user types."""
    retention: Retention | None = None
    """How the Site removes its media itself after a while, such as Twitch its past broadcasts. Media that leaves
    such a Site once it is older than the Retention's ``kept_for`` is removed by its retention: VODLoft expects it to
    go, so it does not ask on Home whether to keep its downloads, and says what deleting a download then means."""
    shows_locked: bool = True
    """A collection on the Site shows what VODLoft has no access to until the user hides it. On a Site
    whose collections mix locked videos among open ones, such as a YouTube channel's members-only
    videos, it starts hidden. Where a collection is locked as a whole, as on The Daily Wire, hiding it
    would empty the collection."""

    def __post_init__(self) -> None:
        if self.icon is not None and not re.fullmatch(r"[a-z]+:[a-z0-9-]+", self.icon):
            raise ValueError(f"The icon of {self.name}, {self.icon!r}, is not a Font Awesome icon as prefix:name")
        if not self.initials:
            object.__setattr__(self, "initials", initials_of(self.name) or initials_of(self.key))
        # Only a stand-in without a name, such as for "any Site", has none.
        if self.initials and not re.fullmatch(r"[A-Z0-9]{1,2}", self.initials):
            raise ValueError(f"The initials of {self.name}, {self.initials!r}, are not one or two capitals or digits")
        # What a Site with sound only leaves out is for sound; whatever it sets itself stays as it is.
        if self.audio_only and self.downloads is _VIDEO_DOWNLOADS:
            object.__setattr__(self, "downloads", self.downloads.for_audio_only())
        if self.audio_only and self.episode_tags is VIDEO_TAGS:
            object.__setattr__(self, "episode_tags", TRACK_TAGS)
        if self.loose_season is None:
            object.__setattr__(self, "loose_season", "Singles" if self.audio_only else "Videos")
        if self.channel_season is None:
            object.__setattr__(
                self, "channel_season", ChannelSeason.UNLISTED if self.audio_only else ChannelSeason.EVERYTHING,
            )

    @property
    def media_names(self) -> Names:
        """What the Site calls one of its videos, from its main episode tag: a video, or a track on a Site with sound
        only, such as the items a playlist holds."""
        return self.episode_tags[0].names

    def episode_tag(self, key: str | None) -> EpisodeTag | None:
        """One of the Site's episode tags by its key."""
        return next((tag for tag in self.episode_tags if tag.key == key), None)

    def types_of(self, *kinds: SectionKind) -> tuple[SectionType, ...]:
        """The Site's section types of these kinds, such as its lists."""
        return tuple(type_ for type_ in self.section_types if type_.kind in kinds)

    @property
    def section_list_names(self) -> Names:
        """What the Site calls its lists, all its types of list together, such as "albums and playlists" on
        SoundCloud; VODLoft's own word on a Site whose creators have none."""
        return self.names_of(SectionKind.LIST)

    def names_of(self, *kinds: SectionKind) -> Names:
        """The Site's section types of these kinds named together, or VODLoft's word for the first kind."""
        types = self.types_of(*kinds)
        return Names.joined([type_.names for type_ in types]) if types else SECTION_KIND_NAMES[kinds[0]]

    def list_collection_names_of(self, list_type: str | None) -> Names:
        """What the Site calls a collection of one of its lists of this type, such as an album on SoundCloud, or its
        ``list_collection_names`` while the type is not known."""
        return self.section_type(list_type).names if list_type else self.list_collection_names

    def section_type(self, key: str) -> SectionType:
        """The Site's section type by its key. A section of a type the Site does not have is a mistake in its Source,
        so it raises ``KeyError``."""
        found = next((type_ for type_ in self.section_types if type_.key == key), None)
        if found is None:
            raise KeyError(f"{self.name} has no type of section {key!r}")
        return found

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


def combined_tags(tag_sets: Iterable[tuple[EpisodeTag, ...]]) -> tuple[EpisodeTag, ...]:
    """The tags of several Sites, each key once, in their order: the first Site's main tag stays the main one."""
    tags: dict[str, EpisodeTag] = {}
    for tag_set in tag_sets:
        for tag in tag_set:
            tags.setdefault(tag.key, tag)
    return tuple(tags.values())


class Source(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    domains: ClassVar[tuple[str, ...]]
    features: ClassVar[frozenset[Feature]]
    sites: ClassVar[tuple[Site, ...]] = ()
    """The Sites this Source is made for, such as The Daily Wire, with what this Source offers on
    each. A Source that serves many sites, as yt-dlp does, names none and tells them apart in
    ``site_for``. Another Source never uses these: on a Site it has no contract for, a Source
    offers a Site's defaults."""
    api_key_sites: ClassVar[tuple[Site, ...]] = ()
    """The Sites a Source with ``Feature.API_KEY`` uses its key on, such as YouTube for yt-dlp. They
    are listed under Authentication from the start, so the key can be added before anything from them."""
    sites_label: ClassVar[str | None] = None
    """What the Source downloads from, in a few words, when its name does not say so, such as
    "YouTube, and many more" for yt-dlp."""
    publish_status_labels: ClassVar[tuple[PublishStatusLabel, ...]] = DEFAULT_PUBLISH_STATUS_LABELS
    """What the Source calls each publish status, every status included."""
    release_date: ClassVar[ReleaseDate] = ReleaseDate.START
    """Which moment the release date the Source gives its items marks."""
    kind_names: ClassVar[Mapping[LinkKind, Names]] = MappingProxyType({})
    """What the Source calls a kind of media where its own word differs from VODLoft's, such as
    Show for a Daily Wire collection. VODLoft uses these words only where it shows the Source's
    own catalogue, and a search result's ``kind_label`` still wins for that one result."""

    @property
    def named_kinds(self) -> dict[LinkKind, Names]:
        """What the Source calls each kind of media: its own word (``kind_names``), or VODLoft's."""
        return {kind: self.kind_names.get(kind, LINK_KIND_NAMES[kind]) for kind in LinkKind}

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

    def has_site_contract(self, site_key: str) -> bool:
        """Whether this Source has a contract of its own for the Site with the key, rather than only the
        defaults it offers any site."""
        return self.site_of(site_key) is not None

    def collection_ref(self, url: str) -> str | None:
        """The id one of this Source's ``sites`` gives the collection at the link, told from the
        link alone, or None when it is not a collection's link. A Source that names Sites implements it."""
        return None

    def episode_tags_for(self, url: str | None) -> tuple[EpisodeTag, ...]:
        """The tags the Site of the collection at this link gives episodes, or without a link, the tags of every Site
        this Source fetches, each once."""
        if url is not None:
            site = self.site_for(url)
            return site.episode_tags if site is not None else VIDEO_TAGS
        return combined_tags(site.episode_tags for site in self.sites) or VIDEO_TAGS

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

    def creator_details(self, ref: str, plan: PlanTracker | None = None) -> CreatorDetails:
        """Look up a creator by its link, or by the ``ref`` it had before. Only Sources with ``Feature.CREATORS``
        implement it.

        A lookup can take a while, so it reports its progress by ``plan``: each Site adds the steps it takes to look a
        creator up, such as reading each of its feeds or listing its playlists, labelled in words such as "Reading
        the playlists", and runs them, counting how many of how many where a step goes through a known number."""
        raise NotImplementedError(f"{self.name} has no creators")

    def creator_of(self, url: str) -> str | None:
        """The creator a collection's link belongs to, as ``creator_details`` takes it, or None when the link is not
        one creator's. Slow: it may ask the Site. Only Sources with ``Feature.CREATORS`` implement it."""
        raise NotImplementedError(f"{self.name} has no creators")

    def music_reason(self, url: str, details: CollectionDetails) -> str | None:
        """Why the collection behind a link, looked up as ``details``, is probably music, such as an album or a
        channel of a music artist, or None when nothing says so. A guess the user can change; it may ask the Site.
        Only Sources with ``Feature.EPISODE_LISTS`` implement it."""
        return None

    def is_creator_page(self, url: str) -> bool:
        """Whether a collection's link is a creator's own page of all their uploads, such as a YouTube channel, whose
        playlists can be its seasons, rather than one playlist. Told without asking the Site. Only Sources with a Site with ``link_seasons`` implement it."""
        return False

    def is_list(self, url: str) -> bool:
        """Whether a collection's link is one list, such as a playlist or an album, rather than a channel: a creator's
        page or one of its feeds. Told without asking the Site."""
        return False

    def season_lists(self, url: str) -> list[SectionRef]:
        """The playlists of the channel at ``url``, as the Site lists them, newest first. Only Sources with a Site with
        ``link_seasons`` implement it."""
        raise NotImplementedError(f"{self.name} has no playlists to make seasons of")

    def list_items(self, url: str) -> tuple[ItemRef, ...]:
        """The videos a playlist lists, in the playlist's own order, such as an album's track order. Only Sources with
        a Site with ``link_seasons`` implement it, and their ``item_details`` looks the videos up."""
        raise NotImplementedError(f"{self.name} has no playlists to make seasons of")

    def list_episodes(
        self, url: str, *, known: frozenset[str], feeds: frozenset[str] | None = None,
    ) -> Iterator[VideoDetails]:
        """The collection's episodes whose slugs are not in ``known``.

        ``feeds`` are the refs of the creator's feeds, as ``creator_details`` names them, that a creator's own
        collection takes, such as only a YouTube channel's Videos; None lists all that the link lists.

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

    def latest_items(self, url: str, *, feeds: frozenset[str] | None = None) -> list[ItemRef]:
        """The collection's newest items, newest first, of only ``feeds`` when given, as ``list_episodes`` takes them.
        Only Sources with ``Feature.QUICK_CHECK`` implement it."""
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

    def quick_check_minutes(self, collections: Sequence[QuickCheckCollection]) -> int:
        """How often each of these collections can get a quick check, at most: a collection that waits longer
        anyway keeps its own wait. ``Feature.QUICK_CHECK`` only."""
        raise NotImplementedError(f"{self.name} has no quick check")

    @property
    def search_sites(self) -> tuple[Site, ...]:
        """The Sites the Source finds things on by name, each ``searchable``: those of its ``sites``. A Source of many
        sites names its own."""
        return tuple(site for site in self.sites if site.searchable)

    def search(self, site: Site, query: str) -> SearchResults:
        """Collections and videos on one of the ``search_sites`` whose name matches the query. Only Sources with
        ``Feature.SEARCH`` implement it."""
        raise NotImplementedError(f"{self.name} cannot be searched")

    def search_ready(self, site: Site) -> bool:
        """Whether the Source can search the Site now: one whose search goes through its own API
        (``SiteApi.searches``) only once that API is set up."""
        return site.site_api is None or not site.site_api.searches or self.site_api_status(site).set_up

    def site_api_status(self, site: Site) -> SiteApiStatus:
        """Which values of the Site's own API are set. Only Sources with ``Feature.SITE_API`` implement it."""
        raise NotImplementedError(f"{self.name} uses no API of {site.name}")

    def save_site_api(self, site: Site, values: Mapping[str, str]) -> None:
        """Test the values of the Site's API with one call and store them. Raises ApiKeyRejected when the Site does
        not accept them."""
        raise NotImplementedError(f"{self.name} uses no API of {site.name}")

    def test_site_api(self, site: Site) -> None:
        """Test the stored values with one call. Raises ApiKeyRejected when the Site does not accept them."""
        raise NotImplementedError(f"{self.name} uses no API of {site.name}")

    def remove_site_api(self, site: Site) -> None:
        raise NotImplementedError(f"{self.name} uses no API of {site.name}")

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

    def cookies_status(self, site_key: str) -> CookiesStatus | None:
        """What the Site's cookies file signs in as, for a Source with ``Feature.COOKIES`` that can tell."""
        return None

    def cookies_changed(self, site_key: str) -> None:
        """The Site's cookies file was replaced or removed, for a Source with ``Feature.COOKIES`` that
        remembers what it signed in as."""

    @property
    def download_streams(self) -> int | None:
        """How many downloads from this Source may run at once, when the Source limits that,
        such as the streams an account may play at the same time."""
        return None

    def has_access(self, key: str) -> bool | None:
        """True when VODLoft can download what needs this access, False when it cannot, and None
        when only a download can tell, such as for a channel membership a cookies file may have."""
        return None

    def learn_access(self) -> None:
        """Ask the service what its sign-in gives, such as a membership level, for a Source that keeps it."""

    def download_refused(self, key: str) -> None:
        """A download was refused for lack of this access, so what VODLoft has may have changed,
        such as the membership level of the account it signs in with."""

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

    def api_status(self, collections: Sequence[QuickCheckCollection] = ()) -> ApiStatus:
        """The API key and today's quota, and what checking ``collections``, this Source's collections, costs.
        Only Sources with ``Feature.API_KEY`` implement it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def save_api_key(self, key: str) -> None:
        """Test the key with one call and store it. Raises ApiKeyRejected when the service does not accept it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def test_api_key(self) -> None:
        """Test the stored key with one call. Raises ApiKeyRejected when the service does not accept it."""
        raise NotImplementedError(f"{self.name} takes no API key")

    def remove_api_key(self) -> None:
        raise NotImplementedError(f"{self.name} takes no API key")
