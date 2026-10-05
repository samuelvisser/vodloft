"""Versioned transport contracts; independent of the VodLoft application."""

from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator

PROTOCOL_VERSION = 1
METADATA_SCHEMA_VERSION = 1


class ConfigurationField(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str
    kind: Literal["text", "number", "select", "secret", "credential_file"]
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def safe_transport_name(cls, value: str) -> str:
        if value in {"operation", "url", "query", "staging", "cursor", "limit", "timeout",
                     "job_id", "source_id", "preferred_format", "max_entries", "scratch",
                     "private_state", "representation", "metadata", "reference"}:
            raise ValueError("Configuration field collides with a protocol argument")
        return value


class SourceManifest(BaseModel):
    protocol_version: int = PROTOCOL_VERSION
    metadata_schema_version: int = METADATA_SCHEMA_VERSION
    source_id: str
    display_name: str
    version: str
    capabilities: set[str]
    exhaustive_domain_catalogue: bool = False
    configuration_schema: list[ConfigurationField] = Field(default_factory=list)
    upstream_versions: dict[str, str] = Field(default_factory=dict)
    python_requirement: str = ">=3.12"
    python_version: str | None = None
    helper_versions: dict[str, str] = Field(default_factory=dict)
    native_helpers: list[str] = Field(default_factory=list)
    configuration_version: int = 1
    catalogue_revision: str = "1"


class AuthenticationChallenge(BaseModel):
    kind: Literal["device_code", "access_token", "credential_file", "login_required"]
    message: str
    verification_url: str | None = None
    user_code: str | None = None
    expires_at: datetime | None = None


class AuthenticationResult(BaseModel):
    """Only status and challenge are public; all other fields are private transport."""
    status: Literal["pending", "authorized", "denied", "expired"]
    challenge: AuthenticationChallenge | None = None
    private_state: dict = Field(default_factory=dict)
    configuration: dict[str, str | int | float] = Field(default_factory=dict)
    expires_at: float | None = None
    interval: int = Field(default=5, ge=1, le=120)


class DomainDescriptor(BaseModel):
    hostname: str
    display_name: str
    source_id: str
    support: Literal["advertised", "verified", "authentication_required", "failing"] = "advertised"
    aliases: list[str] = Field(default_factory=list)
    capabilities: set[str] | None = None


class DomainCatalogue(BaseModel):
    items: list[DomainDescriptor] = Field(default_factory=list, max_length=5000)
    next_cursor: str | None = None
    exhaustive: bool = False
    supports_url_resolution_outside_catalog: bool = True
    catalog_revision: str = "1"


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
    role: str | None = Field(default=None, max_length=32)
    reference: SourceMediaReference
    title: str
    position: int
    kind: Literal["collection", "video", "movie_extra"] = "video"
    group: str | None = None
    episode_number: str | None = None
    extra_type: str | None = None
    occurrence_id: str | None = None
    published_at: datetime | None = None
    capabilities: set[str] | None = None
    is_live: bool | None = None


class FormatDescriptor(BaseModel):
    code: str
    container: str | None = None
    height: int | None = Field(default=None, ge=0)
    audio_only: bool = False
    language: str | None = None
    description: str | None = None


class ArtworkCandidate(BaseModel):
    url: str
    role: Literal["square", "portrait", "landscape", "thumbnail"] = "thumbnail"
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class Chapter(BaseModel):
    title: str
    start: float = Field(ge=0)
    end: float | None = Field(default=None, ge=0)


class MediaTrack(BaseModel):
    kind: Literal["audio", "video", "subtitle"]
    language: str | None = None
    codec: str | None = None
    label: str | None = None


class MediaSnapshot(BaseModel):
    kind: Literal["collection", "video", "movie", "movie_extra"]
    reference: SourceMediaReference
    title: str
    description: str | None = None
    duration: float | None = None
    published_at: datetime | None = None
    capabilities: set[str] | None = None
    is_live: bool | None = None
    formats: list[FormatDescriptor] = Field(default_factory=list)
    extensions: dict[str, dict] = Field(default_factory=dict)
    artwork_url: str | None = None
    artwork: list[ArtworkCandidate] = Field(default_factory=list, max_length=50)
    chapters: list[Chapter] = Field(default_factory=list, max_length=1000)
    tracks: list[MediaTrack] = Field(default_factory=list, max_length=100)
    author: str | None = None
    movie_year: int | None = Field(default=None, ge=1880, le=2200)
    entries: list[EntrySnapshot] = Field(default_factory=list)
    extras: list[EntrySnapshot] = Field(default_factory=list)
    enumeration_complete: bool = True


class CollectionSnapshot(MediaSnapshot):
    kind: Literal["collection"] = "collection"


class VideoSnapshot(MediaSnapshot):
    kind: Literal["video"] = "video"


class MovieSnapshot(MediaSnapshot):
    kind: Literal["movie"] = "movie"


class MovieExtraSnapshot(MediaSnapshot):
    kind: Literal["movie_extra"] = "movie_extra"


NormalizedSnapshot = Annotated[
    CollectionSnapshot | VideoSnapshot | MovieSnapshot | MovieExtraSnapshot,
    Field(discriminator="kind"),
]


class CollectionPage(BaseModel):
    """An opaque, bounded enumeration checkpoint scoped to one Source runtime."""

    entries: list[EntrySnapshot]
    next_cursor: str | None = None
    complete: bool = False


class SourceSearchItem(BaseModel):
    reference: SourceMediaReference
    kind: Literal["collection", "video", "movie", "movie_extra"]
    title: str
    description: str | None = None
    artwork_url: str | None = None


class SourceSearchPage(BaseModel):
    items: list[SourceSearchItem]
    next_cursor: str | None = None


class StreamLease(BaseModel):
    """Private upstream delivery details must stay inside the VodLoft gateway."""

    transport: Literal["http", "hls", "dash"]
    url: str
    expires_at: str | None = None
    renewable: bool = False
    seekable: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    representation_id: str | None = None


class RepresentationPolicy(BaseModel):
    """Common intent, translated by each Source into its acquisition options."""
    languages: list[str] = Field(default_factory=list, max_length=10)
    subtitles: list[str] = Field(default_factory=list, max_length=10)
    language_fallback: bool = True
    chapters: bool = True
    artwork: bool = False
    container: Literal["source", "mp4", "mkv", "mp3", "m4a", "opus"] = "source"
    video_codec: Literal["source", "h264", "h265", "vp9", "av1"] = "source"
    audio_codec: Literal["source", "aac", "mp3", "opus"] = "source"
    embed_metadata: bool = True

    @field_validator("languages", "subtitles")
    @classmethod
    def language_codes(cls, values):
        import re
        if any(not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", value) for value in values):
            raise ValueError("Use language codes such as en, nl or en-US")
        return list(dict.fromkeys(values))


class DownloadResult(BaseModel):
    filename: str
    size: int


class DownloadRequest(BaseModel):
    reference: SourceMediaReference
    staging: str
    preferred_format: str = "format_1080p"
    representation: RepresentationPolicy = Field(default_factory=RepresentationPolicy)


class DownloadEvent(BaseModel):
    """A bounded, Source-reported transfer fraction; local stages remain VodLoft-owned."""
    percent: float = Field(default=0, ge=0, le=100)
    stage: Literal["downloading", "processing"] = "downloading"


class SourceError(BaseModel):
    code: Literal["unsupported_operation", "unavailable", "authentication_required", "rate_limited",
                  "invalid_url", "unsupported_format", "insufficient_disk", "extraction_failed",
                  "runtime_error"]
    message: str
    challenge: AuthenticationChallenge | None = None
