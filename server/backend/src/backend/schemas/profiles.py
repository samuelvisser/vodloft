from __future__ import annotations

from media_profiles import LocalMediaScope, MediaKind
from pydantic import BaseModel, ConfigDict, model_validator


class LocalMediaProfileCreate(BaseModel):
    name: str
    scope: LocalMediaScope = LocalMediaScope.VIDEO
    media_kind: MediaKind = MediaKind.VIDEO
    output_template: str = "/downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s"
    preferred_format: str = "bestvideo*+bestaudio/best"
    merge_output_format: str | None = None
    audio_format: str | None = None
    write_subtitles: bool = False
    embed_metadata: bool = True
    embed_thumbnail: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == LocalMediaScope.VIDEO and self.media_kind != MediaKind.VIDEO:
            raise ValueError("Standalone-video local media profiles must use video media kind")
        return self


class LocalMediaProfileUpdate(BaseModel):
    name: str | None = None
    scope: LocalMediaScope | None = None
    media_kind: MediaKind | None = None
    output_template: str | None = None
    preferred_format: str | None = None
    merge_output_format: str | None = None
    audio_format: str | None = None
    write_subtitles: bool | None = None
    embed_metadata: bool | None = None
    embed_thumbnail: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        required = {"name", "scope", "media_kind", "output_template", "preferred_format", "write_subtitles", "embed_metadata", "embed_thumbnail"}
        for field in self.model_fields_set & required:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class LocalMediaProfileRead(LocalMediaProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str | None


class OutputTemplatePreviewRequest(BaseModel):
    output_template: str


class OutputTemplatePreviewRead(BaseModel):
    valid: bool
    normalized_template: str | None = None
    example_output: str | None = None
    error: str | None = None


class DownloadProfileCreate(BaseModel):
    name: str
    collection_id: int
    local_media_profile_id: int
    enable_profile: bool = True


class DownloadProfileUpdate(BaseModel):
    name: str | None = None
    local_media_profile_id: int | None = None
    enable_profile: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DownloadProfileRead(DownloadProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class StreamProfileCreate(BaseModel):
    name: str
    collection_id: int
    enable_profile: bool = True
    use_downloads: bool = False
    format_selector: str = "best[protocol^=http][vcodec!=none][acodec!=none]/best"


class StreamProfileUpdate(BaseModel):
    name: str | None = None
    enable_profile: bool | None = None
    use_downloads: bool | None = None
    format_selector: str | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class StreamProfileRead(StreamProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
