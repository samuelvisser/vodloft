"""Typed public library envelopes over normalized ORM data."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AliasGenerator, AliasPath, BaseModel, ConfigDict, Field, field_validator
from source_contracts import Chapter, FormatDescriptor, MediaTrack

from backend.db.models.vodloft import Artifact, Domain, MediaItem, SourceReference


def _library_alias(name: str):
    if name == 'domain':
        return AliasPath('domain', 'hostname')
    if name in {'id', 'kind', 'duration', 'published_at', 'capabilities', 'is_live', 'formats', 'parent_id', 'artwork_url'}:
        return AliasPath('item', name)
    if name in {'chapters', 'tracks', 'author', 'movie_year'}:
        return AliasPath('item', 'normalized_metadata', name)
    return name


class LibraryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, alias_generator=AliasGenerator(validation_alias=_library_alias))
    id: int
    kind: Literal['collection', 'video', 'movie', 'movie_extra']
    title: str
    domain: str
    description: str | None
    artwork_url: str | None
    artwork_available: bool
    duration: float | None
    published_at: datetime | None
    capabilities: list[str] | None
    is_live: bool | None
    formats: list[FormatDescriptor] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    tracks: list[MediaTrack] = Field(default_factory=list)
    author: str | None = None
    movie_year: int | None = None
    parent_id: int | None
    parent_ids: list[int] = Field(default_factory=list)
    extra_type: str | None
    downloaded: bool
    playback_type: Literal['audio', 'video']

    @field_validator('formats', mode='before')
    @classmethod
    def empty_formats(cls, value):
        return value or []


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: str
    connection_id: int | None
    namespace: str
    upstream_id: str
    capabilities: list[str] | None = None
    formats: list[FormatDescriptor] | None = None


class LibraryDetailResponse(LibraryItemResponse):
    references: list[ReferenceResponse] = Field(default_factory=list)
    entries: list[LibraryItemResponse] = Field(default_factory=list)
    extras: list[LibraryItemResponse] = Field(default_factory=list)
    member_groups: list[str] = Field(default_factory=list)
    member_roles: list[str] = Field(default_factory=list)


class ExpansionIssueResponse(BaseModel):
    item_id: int
    reason: str


class CollectionExpansionResponse(BaseModel):
    refreshed_ids: list[int]
    skipped: list[ExpansionIssueResponse]


class LibraryRefreshResponse(LibraryItemResponse):
    model_config = ConfigDict(from_attributes=True, alias_generator=AliasGenerator(
        validation_alias=lambda name: name if name == 'nested_expansion' else AliasPath('base', name)))
    nested_expansion: CollectionExpansionResponse


@dataclass(frozen=True)
class LibraryRefreshSource:
    base: LibraryItemResponse
    nested_expansion: CollectionExpansionResponse


class ContinueResponse(LibraryItemResponse):
    seconds: float


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_id: int
    state: str


class IssueResponse(BaseModel):
    kind: Literal['acquisition', 'delivery']
    id: int
    item_id: int | None = None


class HomeResponse(BaseModel):
    continue_: list[ContinueResponse] = Field(serialization_alias='continue')
    recent: list[LibraryItemResponse]
    activity: list[ActivityResponse]
    issues: list[IssueResponse]


@dataclass(frozen=True)
class LibraryItemSource:
    item: MediaItem
    domain: Domain
    artifact: Artifact | None
    seconds: float = 0
    parent_ids: list[int] = field(default_factory=list)
    context_extra_type: str | None = None
    references: list[SourceReference] = field(default_factory=list)
    entries: list[LibraryItemResponse] = field(default_factory=list)
    extras: list[LibraryItemResponse] = field(default_factory=list)
    member_groups: list[str] = field(default_factory=list)
    member_roles: list[str] = field(default_factory=list)

    @property
    def extra_type(self) -> str | None:
        return self.context_extra_type or self.item.user_extra_type or self.item.extra_type

    @property
    def title(self) -> str:
        return self.item.user_title or self.item.title

    @property
    def description(self) -> str | None:
        return self.item.user_description if self.item.user_description is not None else self.item.description

    @property
    def downloaded(self) -> bool:
        return self.artifact is not None

    @property
    def artwork_available(self) -> bool:
        return bool(self.item.artwork_url or (self.item.normalized_metadata or {}).get('artwork'))

    @property
    def playback_type(self) -> str:
        return 'audio' if self.artifact and Path(self.artifact.path).suffix.lower() in {
            '.mp3', '.m4a', '.aac', '.opus', '.ogg', '.wav', '.flac'} else 'video'
