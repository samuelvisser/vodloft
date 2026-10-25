from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal, Optional

from pydantic import Field, computed_field, model_serializer
from pydantic.alias_generators import to_camel

from backend.api.models.base import RequestBase, ResponseBase
from sources import DAILYWIRE, Feature, UnknownSourceError, get_source


def source_features(source_key: str) -> list[str]:
    try:
        source = get_source(source_key)
    except UnknownSourceError:
        return []
    return sorted(feature.value for feature in source.features)


class SourcedResponse(ResponseBase):
    """A response for something that comes from a Source.

    It names the Source and its Features, and leaves out every field in
    ``source_feature_fields`` whose Feature that Source does not have, so a
    generic endpoint never sends one Source's fields for another Source's items.
    """

    source_feature_fields: ClassVar[dict[str, Feature]] = {}

    source_key: str = DAILYWIRE

    @computed_field
    @property
    def source_features(self) -> list[str]:
        return source_features(self.source_key)

    @model_serializer(mode="wrap")
    def _drop_unsupported_fields(self, handler):
        data = handler(self)
        if not self.source_feature_fields or not isinstance(data, dict):
            return data
        features = set(self.source_features)
        for field, feature in self.source_feature_fields.items():
            if feature.value not in features:
                data.pop(field, None)
                data.pop(to_camel(field), None)
        return data


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
