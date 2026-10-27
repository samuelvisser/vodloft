from __future__ import annotations

from datetime import datetime
from collections.abc import Iterable
from typing import Literal, Optional

from pydantic import Field, computed_field, field_validator

from backend.api.models.base import RequestBase, ResponseBase
from sources import Feature, UnknownSourceError, get_source


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


class SourceAPIRead(ResponseBase):
    id: str
    name: str
    domains: list[str]
    features: list[str]
    search_label: Optional[str] = None
    subscription_name: Optional[str] = None
    cookies_help: Optional[str] = None
    subscription_active: bool = False

    @field_validator("features", mode="before")
    @classmethod
    def _sorted_feature_names(cls, features: Iterable[Feature | str]) -> list[str]:
        return sorted(str(feature) for feature in features)


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


class ShowDetailsSeasonAPIRead(ResponseBase):
    slug: str
    name: str


class ShowDetailsAPIRead(ResponseBase):
    """A show at a Source with listed episodes, shaped like the fields of a new show."""

    source_key: str
    slug: str
    title: str
    description: Optional[str] = None
    sharing_url: str
    author_name: str
    author_slug: str
    thumbnail_landscape_path: Optional[str] = None
    # The show's own seasons, oldest first; empty for a Source that has none.
    seasons: list[ShowDetailsSeasonAPIRead] = Field(default_factory=list)


class CookiesStatusAPIRead(ResponseBase):
    label: str
    ok: bool
    detail: Optional[str] = None


class CookiesAPIRead(ResponseBase):
    has_cookies: bool
    status: Optional[CookiesStatusAPIRead] = None


class EpisodeTagAPIRead(ResponseBase):
    key: str
    label: str
    help: str
    selected_by_default: bool
    rss_episode_type: Literal["full", "trailer", "bonus"]
    main: bool


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
    # The shows the key speeds up, and the units one full re-scan of them costs,
    # so the settings can say how often each show gets checked.
    show_count: int
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
    kind: Literal["show", "movie", "episode", "video"]
    slug: str
    url: str
    show_slug: Optional[str] = None
    show_url: Optional[str] = None
    site: Optional[str] = None
    drm_protected: bool = False
    needs_subscription: bool = False
    preview: ResolvedLinkPreviewAPIRead
    # Every Source that claims the link's domain, preferred first, to look the link up with another one.
    candidates: list[SourceAPIRead] = Field(default_factory=list)


class SearchResultAPIRead(ResponseBase):
    kind: Literal["show", "movie", "episode", "video"]
    slug: str
    url: str
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    author_name: Optional[str] = None
    show_slug: Optional[str] = None
    show_url: Optional[str] = None
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


class SourceDomainAPIRead(ResponseBase):
    domain: str
    # The Sources that can handle links on this domain, in the order VODLoft asks them by default.
    source_keys: list[str]
    default_source_key: str
    preferred_source_key: Optional[str] = None


class SourceDomainAPIUpdate(RequestBase):
    # None goes back to the default order.
    preferred_source_key: Optional[str] = None
