from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, computed_field

from backend.api.models.base import RequestBase, ResponseBase
from sources import UnknownSourceError, get_source


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


class CookiesAPIRead(ResponseBase):
    has_cookies: bool


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


class SourceDomainAPIRead(ResponseBase):
    domain: str
    # The Sources that can handle links on this domain, in the order VODLoft asks them by default.
    source_keys: list[str]
    default_source_key: str
    preferred_source_key: Optional[str] = None


class SourceDomainAPIUpdate(RequestBase):
    # None goes back to the default order.
    preferred_source_key: Optional[str] = None
