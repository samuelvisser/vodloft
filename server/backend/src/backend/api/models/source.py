from __future__ import annotations

from datetime import datetime
from collections.abc import Iterable, Mapping
from typing import Annotated, Literal, Optional

from pydantic import AliasChoices, AliasPath, Field, ValidationInfo, computed_field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from backend.api.models.base import RequestBase, ResponseBase
from backend.services.media_access import access_granted, access_locked, site_access
from backend.types.collection_types import CollectionType
from backend.types.link_season_types import CollectionKind
from config.settings.site_settings import UpgradeRepeat
from sources import Feature, ProfileSeasons, ReleaseDate, SiteSetting, StreamMethod, UnknownSourceError, UpgradeImprovement, get_source, site_of
from sources.ytdlp_options import MAX_OPTIONS_LENGTH, OptionsRefused, ytdlp_option_arguments


def source_features(source_key: str) -> list[str]:
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return []
    return sorted(feature.value for feature in source.features)


class NamesAPIRead(ResponseBase):
    """A word in lower case: singular, plural, and singular with its article, such as album, albums and an album."""

    singular: str
    plural: str
    a: str


class SourcedResponse(ResponseBase):
    """A response for something that comes from a Source.

    It names the Source and its Features. Every field is always sent, so the
    client checks a Feature to know whether a field means anything for the item.
    """

    source_key: str

    @computed_field
    @property
    def source_features(self) -> list[str]:
        return source_features(self.source_key)


class LockableResponse(ResponseBase):
    """Media that may need an access, such as a channel membership, and is locked without it."""

    source_key: str
    site_key: Optional[str] = Field(
        default=None, exclude=True,
        validation_alias=AliasChoices("site_key", AliasPath("collection", "site_key"), AliasPath("episode", "collection", "site_key")),
    )
    """The Site the media is on, which names the access."""
    access: Optional[str] = None
    """The key of the access the media needs; ``access_label`` is what its Site calls it."""
    access_refused_at: Optional[datetime] = None
    access_check_at: Optional[datetime] = None
    """When VODLoft next checks whether the locked media opened up."""

    @computed_field
    @property
    def access_locked(self) -> bool:
        """VODLoft cannot download the media without the access, so it does not try."""
        return access_locked(self.source_key, self.access, self.access_refused_at)

    @computed_field
    @property
    def access_granted(self) -> bool:
        """VODLoft has the access the media needs, such as through the account it signs in with."""
        return access_granted(self.source_key, self.access, self.access_refused_at)

    @computed_field
    @property
    def access_label(self) -> Optional[str]:
        """What the media's Site calls the access, such as Members only or NPO Plus."""
        found = site_access(self.source_key, self.site_key, self.access)
        return found.label if found is not None else None

    @computed_field
    @property
    def access_description(self) -> Optional[str]:
        """One sentence from the media's Site on who can watch it, such as "Only NPO Plus subscribers can watch this."."""
        found = site_access(self.source_key, self.site_key, self.access)
        return found.description if found is not None else None


class RetentionAPIRead(ResponseBase):
    """A Site that removes its media itself after a while, such as Twitch its past broadcasts."""

    site_name: str
    retention: str
    """How the Site removes its media, as a sentence."""


class RetentionResponse(LockableResponse):
    """Media on a Site that may have removed it itself, as it removes all its media after a while."""

    removed_by_retention: bool = False

    @computed_field
    @property
    def removed_by(self) -> Optional[RetentionAPIRead]:
        """The Site whose retention removed the media, and how that Site removes its media; None for media its Site
        did not remove so."""
        if not self.removed_by_retention or self.site_key is None:
            return None
        site = site_of(self.site_key)
        return RetentionAPIRead(site_name=site.name, retention=site.retention.description if site.retention else "")


class DownloadOptionsAPIRead(ResponseBase):
    """What a Local Media Profile can download for a Site, or for any Site of a Source."""

    video_heights: list[int]
    audio_only: bool
    hls_bundle: bool
    hls_heights: list[int]
    subtitles: bool
    quality_choices: bool
    info_file: bool


class UpgradeChecksAPIRead(ResponseBase):
    """What the upgrade check can find on a Site; nothing to find means no upgrade check."""

    improvements: list[UpgradeImprovement]


class DownloadProfileDefaultsAPIRead(ResponseBase):
    """What a new Download Profile on a Site starts with: the Site's own settings, its presets or the system defaults."""

    download_with_countdown: bool
    upgrade_check: bool
    upgrade_after_days: int
    upgrade_repeat: UpgradeRepeat
    upgrade_improvements: list[UpgradeImprovement]
    upgrade_length_minutes: int


class SourceSiteAddedAPIRead(ResponseBase):
    """A Site of a Source, and whether it is added to VODLoft, so Add Media offers to browse or search it."""

    key: str
    name: str
    added: bool = False
    """Told by the ``added_sites`` the Sources are read with."""

    @model_validator(mode="after")
    def _added(self, info: ValidationInfo) -> "SourceSiteAddedAPIRead":
        self.added = self.key in (info.context or {}).get("added_sites", ())
        return self


class SearchSiteAPIRead(SourceSiteAddedAPIRead):
    """A Site a Source finds things on by name, such as YouTube or SoundCloud for yt-dlp."""

    costly_search: bool
    """Each search costs something, so the search page searches when asked instead of while the user types."""
    ready: bool = False
    """The Source can search the Site now: one whose search goes through its own API once that is set up. Told by
    the ``ready_sites`` the Sources are read with."""

    @model_validator(mode="after")
    def _ready(self, info: ValidationInfo) -> "SearchSiteAPIRead":
        self.ready = self.key in (info.context or {}).get("ready_sites", ())
        return self


class SourceAPIRead(ResponseBase):
    id: str
    name: str
    domains: list[str]
    features: list[str]
    sites_label: Optional[str] = None
    sites: list[SourceSiteAddedAPIRead] = Field(default_factory=list)
    """The Sites the Source is made for, such as The Daily Wire, whose catalogue it browses."""
    search_sites: list[SearchSiteAPIRead] = Field(default_factory=list)
    """The Sites the Source can search by name, each with a search button of its own."""
    kind_names: dict[str, NamesAPIRead] = Field(validation_alias="named_kinds")
    """What the Source calls each kind of media, such as show for a Daily Wire collection, or VODLoft's word."""
    release_date: ReleaseDate
    download_options: DownloadOptionsAPIRead
    site_keys: list[str] = Field(default_factory=list, validation_alias="sites")
    """The Sites the Source is made for, such as The Daily Wire; none for a Source of many sites, such as yt-dlp."""

    @field_validator("features", mode="before")
    @classmethod
    def _sorted_feature_names(cls, features: Iterable[Feature | str]) -> list[str]:
        return sorted(str(feature) for feature in features)

    @field_validator("site_keys", mode="before")
    @classmethod
    def _site_keys(cls, sites: Iterable[object]) -> list[str]:
        return [site if isinstance(site, str) else site.key for site in sites]

    @field_validator("kind_names", mode="before")
    @classmethod
    def _kind_name_keys(cls, kind_names: Mapping[object, object]) -> dict[str, object]:
        return {str(kind): name for kind, name in kind_names.items()}


class ResolveAPIRequest(RequestBase):
    url: str = Field(min_length=1, max_length=2048)
    # Ask only this Source, when the user picked one of several that claim the link.
    source_key: Optional[str] = None


class ResolvedLinkPreviewAPIRead(ResponseBase):
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    author_name: Optional[str] = None


class ProgramStatusAPIRead(ResponseBase):
    name: str
    version: Optional[str] = None
    last_update_at: Optional[datetime] = None
    last_update_error: Optional[str] = None


class CollectionDetailsSeasonAPIRead(ResponseBase):
    slug: str
    name: str


class CollectionDetailsAPIRead(ResponseBase):
    """A collection at a Source with listed episodes, shaped like the fields of a new collection."""

    source_key: str
    slug: str
    title: str
    description: Optional[str] = None
    sharing_url: str
    author_name: str
    author_slug: str
    thumbnail_landscape_path: Optional[str] = None
    probable_collection_type: CollectionType
    music_reason: Optional[str] = None
    """Why the collection was taken for music, when it was."""
    # The collection's own seasons, oldest first; empty for a Source that has none.
    seasons: list[CollectionDetailsSeasonAPIRead] = Field(default_factory=list)
    audio_only: bool = False
    """The collection's Site has sound only, such as SoundCloud: a Music collection there holds tracks."""
    kind: CollectionKind
    """What the link is: a channel, or one list, such as a playlist or an album, which is the collection's one
    season, its episodes in the list's order."""
    list_type: Optional[str] = None
    """Which of its Site's types of list the link is, such as an album or a playlist on SoundCloud, where its link
    doesn't tell."""
    seasons_plans: dict[str, str] = Field(default_factory=dict)
    """What the collection's seasons will be once it is added as each type, in words, as its Site's defaults make
    them: each list a season, what goes in the channel season, or a season per upload year."""


class CookiesStatusAPIRead(ResponseBase):
    label: str
    ok: bool
    detail: Optional[str] = None


class ApiFieldAPIRead(ResponseBase):
    key: str
    label: str
    secret: bool


class GuideStepAPIRead(ResponseBase):
    text: str
    button: Optional[str] = None
    url: Optional[str] = None


class SiteApiAPIRead(ResponseBase):
    """A Site's own free API that the user can register VODLoft with, such as Twitch's."""

    name: str
    fields: list[ApiFieldAPIRead]
    benefits: str
    steps: list[GuideStepAPIRead]
    searches: bool
    """The Site's search goes through the API, so Add Media only searches the Site once it is set up."""


class SiteApiStatusAPIRead(ResponseBase):
    hints: dict[str, str]
    """The values that are set, by their field's key: a secret by its last few characters."""
    problem: Optional[str] = None
    set_up: bool


class SiteApiValuesAPIUpdate(RequestBase):
    values: dict[str, str] = Field(max_length=8)
    """The values by their field's key. A secret left empty keeps the one stored."""


class SiteAuthenticationAPIRead(ResponseBase):
    """A Site, and how VODLoft signs in on it or gets at its API: a Source's own sign-in, the Site's cookies
    file, or a Source's API key."""

    key: str
    name: str
    domains: list[str]
    sign_in_source_key: Optional[str] = None
    """The Source made for the Site with a sign-in of its own, such as The Daily Wire's."""
    cookie_source_names: list[str]
    """The Sources that sign in on the Site with its cookies file; none when nothing uses one there."""
    cookies_help: Optional[str] = None
    has_cookies: bool
    cookie_count: int
    cookies_status: Optional[CookiesStatusAPIRead] = None
    api_key_source_key: Optional[str] = None
    """The Source whose API key is for the Site, such as yt-dlp's YouTube Data API key."""
    site_api: Optional[SiteApiAPIRead] = None
    """The Site's own API, on a Site that has one a Source uses."""
    site_api_status: Optional[SiteApiStatusAPIRead] = None
    removable: bool
    """The user can remove the Site: VODLoft has nothing from it and no Source is made for it."""


class MediaLinksAPIRequest(RequestBase):
    """Links found in a description, to tell which of them are on a Site VODLoft knows for media."""

    urls: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(max_length=100)


class MediaLinksAPIRead(ResponseBase):
    urls: list[str]
    """The links of the request that are on a Site VODLoft knows, which the user can look up to add."""


class SiteAddAPIRequest(RequestBase):
    url: str = Field(min_length=1, max_length=2048)
    """A link to a page on the Site, or only its address, such as ``twitch.tv``."""

    @field_validator("url")
    @classmethod
    def _with_scheme(cls, value: str) -> str:
        """An address typed without ``https://`` is the Site's https address."""
        value = value.strip()
        return value if not value or "://" in value else f"https://{value}"


class SiteAddedAPIRead(ResponseBase):
    """A Site added by a link to it."""

    key: str
    name: str


class SitesPickAPIRequest(RequestBase):
    keys: list[str] = Field(max_length=200)
    """The Sites the user uses, by key: suggested ones, or ones added by their address. At least one."""


def checked_ytdlp_options(value: str) -> str:
    """Your own yt-dlp options, refused with the first line that can not be used."""
    try:
        ytdlp_option_arguments(value)
    except OptionsRefused as exc:
        # Without "Value error, " in front, so the form shows the reason as it is.
        raise PydanticCustomError("ytdlp_options", "{reason}", {"reason": str(exc)}) from None
    return value.strip("\n")


class YtdlpOptionsAPIRead(ResponseBase):
    """The yt-dlp options a Source gives every download."""
    text: str


class YtdlpOptionsAPIUpdate(RequestBase):
    text: str = Field(max_length=MAX_OPTIONS_LENGTH)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return checked_ytdlp_options(value)


class YtdlpOptionsCheckAPIRequest(RequestBase):
    """Your own yt-dlp options, as typed so far."""

    text: str = Field(max_length=MAX_OPTIONS_LENGTH)


class YtdlpOptionLineAPIRead(ResponseBase):
    """One line of your own yt-dlp options and what VODLoft makes of it."""

    line: int
    text: str
    status: Literal["valid", "blocked", "has_setting", "invalid"]
    message: str
    setting: Optional[str] = None


class SiteOptionsAPIRead(ResponseBase):
    """What the site of one collection offers beyond its Source's usual choices."""

    site_key: str
    site_name: str
    settings: list[SiteSetting]
    """The download profile settings the site shows, such as auto-generated subtitles or downloading with the countdown."""
    profile_defaults: DownloadProfileDefaultsAPIRead
    """What a new Download Profile for the collection starts with."""
    profile_seasons: ProfileSeasons
    """Which seasons a new Download Profile of a seasonal collection picks, beside the upcoming ones."""
    upgrade_checks: UpgradeChecksAPIRead
    stream_methods: list[StreamMethod] = []
    """How RSS feeds can stream the collection's episodes without downloading them first; none for downloads only."""
    stream_video_heights: list[int] = []
    stream_file_height: Optional[int] = None
    """The one resolution the Site streams as an MP4 file with sound; a feed plays the others once VODLoft has joined
    them into one."""
    stream_proxy_choice: bool = False
    """A feed can send podcast apps straight to the Site's video, or pass it through VODLoft."""
    video_output_help: dict[str, str] = {}
    """What a feed's video output does on the Site, by output, where it differs from the usual explanation."""
    downloads: DownloadOptionsAPIRead

    @field_validator("stream_methods", mode="before")
    @classmethod
    def _sorted_stream_methods(cls, methods: Iterable[StreamMethod]) -> list[StreamMethod]:
        return sorted(methods)


class EpisodeTagAPIRead(ResponseBase):
    key: str
    label: str
    help: str
    names: NamesAPIRead
    """What a count of them is called, such as 1 livestream or 726 livestreams."""
    selected_by_default: bool
    rss_episode_type: Literal["full", "trailer", "bonus"]
    main: bool


class PublishStatusLabelAPIRead(ResponseBase):
    status: str
    label: str
    help: str


class ApiQuotaShareAPIRead(ResponseBase):
    name: str
    used: int
    limit: int


class QuickCheckCostAPIRead(ResponseBase):
    units: int
    least_minutes: int
    feeds: int


class ApiKeyNoteAPIRead(ResponseBase):
    """A Source whose API key would speed up collections or creators in the Library, while it has none."""

    source_key: str
    site_name: str
    """The Site the key is for, such as YouTube."""


class ApiKeyNoteAPIIn(RequestBase):
    """Put the note off for a week (``later``), or never show it again (``never``)."""

    action: Literal["later", "never"]


class ApiStatusAPIRead(ResponseBase):
    key_hint: Optional[str] = None
    shares: list[ApiQuotaShareAPIRead]
    daily_quota: int
    exhausted: bool
    resets_at: datetime
    problem: Optional[str] = None
    problem_fix_url: Optional[str] = None
    # The collections the key speeds up, and the units one full re-scan of them costs,
    # so the settings can say how often each collection gets checked.
    collection_count: int
    rescan_units: int
    # What one quick check of each of those collections costs, so the settings can say how often each is checked.
    check_costs: list[QuickCheckCostAPIRead]


class ApiKeyAPIUpdate(RequestBase):
    key: str = Field(min_length=1, max_length=200)


class SourceProblemAPIRead(ResponseBase):
    source_key: str
    source_name: str
    title: str
    detail: str
    fix_url: Optional[str] = None


class CookiesAPIUpdate(RequestBase):
    content: str = Field(min_length=1, max_length=4 * 1024 * 1024)


class ResolvedLinkAPIRead(ResponseBase):
    source: SourceAPIRead
    kind: Literal["collection", "movie", "episode", "video", "creator"]
    slug: str
    url: str
    collection_slug: Optional[str] = None
    collection_url: Optional[str] = None
    site: Optional[str] = None
    drm_protected: bool = False
    access: Optional[str] = None
    """The key of the access the video needs."""
    access_label: Optional[str] = None
    """What the link's Site calls that access, such as Members only."""
    access_description: Optional[str] = None
    """One sentence from the link's Site on who can watch the video."""
    access_locked: bool = False
    """VODLoft does not have that access, so it cannot download the video."""
    preview: ResolvedLinkPreviewAPIRead
    collection_kind: Optional[CollectionKind] = None
    """For a collection: whether it is a channel or one list."""
    creator_names: Optional[NamesAPIRead] = None
    """For a collection on a Site with creators, which can be in one: what its Site calls the creator behind it, such
    as host on The Daily Wire."""
    # Every Source that claims the link's domain, preferred first, to look the link up with another one.
    candidates: list[SourceAPIRead] = Field(default_factory=list)


class SearchResultAPIRead(ResponseBase):
    kind: Literal["collection", "movie", "episode", "video"]
    slug: str
    url: str
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    author_name: Optional[str] = None
    collection_slug: Optional[str] = None
    collection_url: Optional[str] = None
    kind_label: Optional[str] = None
    facts: list[str] = []
    access: Optional[str] = None
    access_label: Optional[str] = None
    """What the result's Site calls the access it needs, such as Members only."""


class SearchNoticeAPIRead(ResponseBase):
    badge: str
    text: str
    tone: Literal["neutral", "warning"] = "neutral"
    link_label: Optional[str] = None
    link_path: Optional[str] = None


class SearchResultsAPIRead(ResponseBase):
    results: list[SearchResultAPIRead]
    notice: Optional[SearchNoticeAPIRead] = None


class SectionTypeAPIRead(ResponseBase):
    """One type of section a Site's creators have, such as a feed, or an album or a playlist on SoundCloud, and what
    the Site calls it, in lower case."""

    key: str
    kind: Literal["feed", "list", "show", "item"]
    names: NamesAPIRead


class ListKindAPIRead(ResponseBase):
    """One kind of list a Site's channels have, such as a SoundCloud account's albums or its playlists, with its own
    setting for what happens with a new one."""

    key: str = Field(validation_alias=AliasPath("kind", "key"))
    names: NamesAPIRead = Field(validation_alias=AliasPath("kind", "names"))
    """What the Sites call the lists, such as album and albums."""
    albums: bool = Field(default=False, validation_alias=AliasPath("kind", "albums"))
    """The kind best describes an artist's albums."""


class SiteChoiceAPIRead(ResponseBase):
    """A Site the user can pick as one they use: a popular one VODLoft suggests, or one already added."""

    key: str
    name: str
    pitch: str | None
    """What VODLoft adds from the Site, in a few words, such as "Channels, playlists, Shorts and live streams"."""
    added: bool
    """VODLoft knows the Site already."""

    @computed_field
    @property
    def icon(self) -> str | None:
        """The Site's Font Awesome icon as ``prefix:name``, such as ``fab:youtube``."""
        return site_of(self.key).icon

    @computed_field
    @property
    def initials(self) -> str:
        """The Site's name in at most two letters, such as YT, shown beside a globe where it has no icon."""
        return site_of(self.key).initials


class SiteAPIRead(ResponseBase):
    """The website a collection or video is on, such as YouTube, whichever Source fetches it."""

    key: str
    name: str

    @computed_field
    @property
    def icon(self) -> str | None:
        """The Site's Font Awesome icon as ``prefix:name``, such as ``fab:youtube``, shown where its name does not fit."""
        return site_of(self.key).icon

    @computed_field
    @property
    def initials(self) -> str:
        """The Site's name in at most two letters, such as YT, shown beside a globe where it has no icon."""
        return site_of(self.key).initials

    @computed_field
    @property
    def shows_locked(self) -> bool:
        """A collection on the Site shows what VODLoft has no access to until the user hides it."""
        return site_of(self.key).shows_locked

    @computed_field
    @property
    def media_names(self) -> NamesAPIRead:
        """What the Site calls one of its videos: a video, or a track on a Site with sound only."""
        return NamesAPIRead.model_validate(site_of(self.key).media_names)

    @computed_field
    @property
    def audio_only(self) -> bool:
        """The Site has sound only, such as Bandcamp: a Music collection on it holds tracks, not music videos."""
        return site_of(self.key).audio_only

    @computed_field
    @property
    def creator_names(self) -> NamesAPIRead:
        """What the Site calls a creator, such as host on The Daily Wire."""
        return NamesAPIRead.model_validate(site_of(self.key).creator_names)

    @computed_field
    @property
    def section_types(self) -> list[SectionTypeAPIRead]:
        """Every type of section the Site's creators have and what the Site calls it, such as YouTube's feeds and
        playlists."""
        return [SectionTypeAPIRead.model_validate(type_) for type_ in site_of(self.key).section_types]

    @computed_field
    @property
    def section_list_names(self) -> NamesAPIRead:
        """What the Site calls its lists, all its types of list together, such as albums and playlists."""
        return NamesAPIRead.model_validate(site_of(self.key).section_list_names)

    @computed_field
    @property
    def channel_collection_names(self) -> NamesAPIRead:
        """What the Site calls a collection of a channel's uploads, such as a YouTube channel."""
        return NamesAPIRead.model_validate(site_of(self.key).channel_collection_names)

    @computed_field
    @property
    def list_collection_names(self) -> NamesAPIRead:
        """What the Site calls a collection of one list, such as a YouTube playlist."""
        return NamesAPIRead.model_validate(site_of(self.key).list_collection_names)

    @computed_field
    @property
    def link_seasons(self) -> bool:
        """A channel's playlists or albums at the Site can be seasons of its collection."""
        return site_of(self.key).link_seasons


class SourceSiteAPIRead(ResponseBase):
    key: str
    name: str
    domains: list[str]
    # The Sources that can handle links on this Site, in the order VODLoft asks them by default.
    source_keys: list[str]
    default_source_key: str
    preferred_source_key: Optional[str] = None


class SourceSiteAPIUpdate(RequestBase):
    # None goes back to the default order.
    preferred_source_key: Optional[str] = None
