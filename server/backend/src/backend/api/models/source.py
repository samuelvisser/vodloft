from __future__ import annotations

from datetime import datetime
from collections.abc import Iterable, Mapping
from typing import Literal, Optional

from pydantic import Field, computed_field, field_validator

from backend.api.models.base import RequestBase, ResponseBase
from backend.types.collection_types import CollectionType
from sources import Feature, StreamMethod, UnknownSourceError, UpgradeImprovement, get_source
from sources.ytdlp_options import MAX_OPTIONS_LENGTH, OptionsRefused, ytdlp_option_arguments


def source_features(source_key: str) -> list[str]:
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return []
    return sorted(feature.value for feature in source.features)


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


class DownloadOptionsAPIRead(ResponseBase):
    """What a Local Media Profile can download for a Site, or for any Site of a Source."""

    video_heights: list[int]
    audio_only: bool
    hls_bundle: bool
    quality_choices: bool


class UpgradeChecksAPIRead(ResponseBase):
    """What the upgrade check can find on a Site; nothing to find means no upgrade check."""

    improvements: list[UpgradeImprovement]
    checked: list[UpgradeImprovement]
    """The improvements a new Download Profile starts with."""
    on_by_default: bool


class SourceAPIRead(ResponseBase):
    id: str
    name: str
    domains: list[str]
    features: list[str]
    sites_label: Optional[str] = None
    search_label: Optional[str] = None
    kind_names: dict[str, str] = {}
    subscription_name: Optional[str] = None
    cookies_help: Optional[str] = None
    subscription_active: bool = False
    download_options: DownloadOptionsAPIRead

    @field_validator("features", mode="before")
    @classmethod
    def _sorted_feature_names(cls, features: Iterable[Feature | str]) -> list[str]:
        return sorted(str(feature) for feature in features)

    @field_validator("kind_names", mode="before")
    @classmethod
    def _kind_name_keys(cls, kind_names: Mapping[object, str]) -> dict[str, str]:
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
    # The collection's own seasons, oldest first; empty for a Source that has none.
    seasons: list[CollectionDetailsSeasonAPIRead] = Field(default_factory=list)


class CookiesStatusAPIRead(ResponseBase):
    label: str
    ok: bool
    detail: Optional[str] = None


class CookiesAPIRead(ResponseBase):
    has_cookies: bool
    status: Optional[CookiesStatusAPIRead] = None


def checked_ytdlp_options(value: str) -> str:
    """Your own yt-dlp options, refused with the first line that can not be used."""
    try:
        ytdlp_option_arguments(value)
    except OptionsRefused as exc:
        raise ValueError(str(exc)) from None
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

    site_name: str
    auto_subtitles: bool
    sponsorblock: bool
    countdown_downloads: bool
    """A Download Profile can download live episodes with their countdown, and again as the final version."""
    upgrade_checks: UpgradeChecksAPIRead
    stream_methods: list[StreamMethod] = []
    """How RSS feeds can stream the collection's episodes without downloading them first; none for downloads only."""
    stream_video_heights: list[int] = []
    stream_proxy_choice: bool = False
    """A feed can send podcast apps straight to the Site's video, or pass it through VODLoft."""
    downloads: DownloadOptionsAPIRead

    @field_validator("stream_methods", mode="before")
    @classmethod
    def _sorted_stream_methods(cls, methods: Iterable[StreamMethod]) -> list[StreamMethod]:
        return sorted(methods)


class EpisodeTagAPIRead(ResponseBase):
    key: str
    label: str
    help: str
    singular: str
    plural: str
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
    kind: Literal["collection", "movie", "episode", "video"]
    slug: str
    url: str
    collection_slug: Optional[str] = None
    collection_url: Optional[str] = None
    site: Optional[str] = None
    drm_protected: bool = False
    needs_subscription: bool = False
    preview: ResolvedLinkPreviewAPIRead
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
    needs_subscription: bool = False


class SearchNoticeAPIRead(ResponseBase):
    badge: str
    text: str
    tone: Literal["neutral", "warning"] = "neutral"
    link_label: Optional[str] = None
    link_path: Optional[str] = None


class SearchResultsAPIRead(ResponseBase):
    results: list[SearchResultAPIRead]
    notice: Optional[SearchNoticeAPIRead] = None


class SiteAPIRead(ResponseBase):
    """The website a collection or video is on, such as YouTube, whichever Source fetches it."""

    key: str
    name: str


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
