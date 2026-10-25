from __future__ import annotations

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


class ResolvedLinkPreviewAPIRead(ResponseBase):
    title: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    author_name: Optional[str] = None


class ResolvedLinkAPIRead(ResponseBase):
    source: SourceAPIRead
    kind: Literal["show", "movie", "episode"]
    slug: str
    url: str
    show_slug: Optional[str] = None
    show_url: Optional[str] = None
    preview: ResolvedLinkPreviewAPIRead
