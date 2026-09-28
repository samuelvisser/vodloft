"""Versioned transport contracts; independent of the VodLoft application."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


class SourceManifest(BaseModel):
    protocol_version: int = PROTOCOL_VERSION
    source_id: str
    display_name: str
    version: str
    capabilities: set[str]
    exhaustive_domain_catalogue: bool = False
    configuration_schema: list[dict] = Field(default_factory=list)


class DomainDescriptor(BaseModel):
    hostname: str
    display_name: str
    source_id: str
    support: Literal["advertised", "verified"] = "advertised"
    aliases: list[str] = Field(default_factory=list)


class SourceMediaReference(BaseModel):
    source_id: str
    domain: str
    namespace: str
    upstream_id: str
    url: str


class SourceMatch(BaseModel):
    source_id: str
    confidence: int = Field(ge=0, le=100)
    reason: str = ""


class EntrySnapshot(BaseModel):
    reference: SourceMediaReference
    title: str
    position: int
    kind: Literal["collection", "video", "movie_extra"] = "video"
    group: str | None = None
    episode_number: str | None = None
    extra_type: str | None = None
    occurrence_id: str | None = None
    published_at: datetime | None = None


class MediaSnapshot(BaseModel):
    kind: Literal["collection", "video", "movie", "movie_extra"]
    reference: SourceMediaReference
    title: str
    description: str | None = None
    duration: float | None = None
    published_at: datetime | None = None
    artwork_url: str | None = None
    entries: list[EntrySnapshot] = Field(default_factory=list)
    extras: list[EntrySnapshot] = Field(default_factory=list)
    enumeration_complete: bool = True


class CollectionPage(BaseModel):
    """An opaque, bounded enumeration checkpoint scoped to one Source runtime."""

    entries: list[EntrySnapshot]
    next_cursor: str | None = None
    complete: bool = False


class StreamLease(BaseModel):
    """Private upstream delivery details must stay inside the VodLoft gateway."""

    transport: Literal["http", "hls", "dash"]
    url: str
    expires_at: str | None = None
    renewable: bool = False
    seekable: bool = False
    headers: dict[str, str] = Field(default_factory=dict)


class DownloadResult(BaseModel):
    filename: str
    size: int


class SourceError(BaseModel):
    code: Literal["unsupported_operation", "unavailable", "authentication_required", "rate_limited", "invalid_url", "runtime_error"]
    message: str
