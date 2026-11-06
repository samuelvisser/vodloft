from __future__ import annotations

from datetime import datetime
from typing import Union


from pydantic import Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.services.local_media_profile_inputs import IndexingValueDefinition, LocalMediaProfileInput, VideoCodecChoice
from backend.api.models.pagination import CursorPageRead
from backend.types.local_media_profile_types import (
    AudioCodec,
    AudioFormat,
    CodecFallback,
    LocalMediaProfileMetadataMode,
    LocalMediaProfileStorageMode,
    LocalMediaProfileSubtitleMode,
    LocalMediaProfileThumbnailMode,
    LocalMediaProfileType,
    PreferredFormat,
    QualityGoal,
    SubtitleLanguageMode,
    VideoCodec,
    VideoContainer,
)


class VideoCodecChoiceAPIRead(ResponseBase):
    codec: Union[VideoCodec, str]
    allowed: bool


class VideoCodecChoiceAPI(RequestBase, VideoCodecChoice):
    """One codec in a Local Media Profile's order, as the UI sends it."""


class LocalMediaProfileAPIBaseIn(RequestBase, LocalMediaProfileInput):
    """Fields shared by all Local Media Profile request models."""


class LocalMediaProfileAPIBaseOut(ResponseBase):
    """Fields shared by all Local Media Profile response models."""

    id: int
    type: Union[LocalMediaProfileType, str]
    slug: str
    name: str
    output_template: str
    preferred_format: Union[PreferredFormat, str]
    download_mode: Union[LocalMediaProfileStorageMode, str] = LocalMediaProfileStorageMode.SYSTEM
    thumbnail_mode: Union[LocalMediaProfileThumbnailMode, str] = LocalMediaProfileThumbnailMode.SYSTEM
    metadata_mode: Union[LocalMediaProfileMetadataMode, str] = LocalMediaProfileMetadataMode.SYSTEM
    subtitle_mode: Union[LocalMediaProfileSubtitleMode, str] = LocalMediaProfileSubtitleMode.SIDECAR
    subtitle_languages: list[str]
    subtitle_language_mode: Union[SubtitleLanguageMode, str]
    quality_goal: Union[QualityGoal, str]
    video_codecs: list[VideoCodecChoiceAPIRead]
    codec_fallback: Union[CodecFallback, str]
    container: Union[VideoContainer, str]
    audio_codec: Union[AudioCodec, str]
    audio_format: Union[AudioFormat, str]
    audio_language: str | None = None
    append_media_type_to_filename: bool
    source_keys: list[str] | None = None
    created_at: datetime
    updated_at: datetime


class LocalMediaProfileTemplateVariable(ResponseBase):
    name: str
    description: str


class LocalMediaProfileTemplateSource(ResponseBase):
    id: str
    label: str
    values: dict[str, str]
    fallback: bool = False
    pending: list[str] = Field(default_factory=list)
    """For an example of a collection that is not saved yet: the values it shows by name, because
    VODLoft counts them from the collection's oldest episode."""


class LocalMediaProfileTemplateSourcePage(CursorPageRead[LocalMediaProfileTemplateSource]):
    revision: str


class LocalMediaProfileTemplatePreview(RequestBase):
    type: LocalMediaProfileType
    output_template: str = Field(min_length=1, max_length=4096)
    preferred_format: PreferredFormat
    values: dict[str, str] = Field(default_factory=dict)
    source_id: str | None = None
    local_media_profile_id: int | None = None
    indexing_values: list[IndexingValueDefinition] | None = None


class LocalMediaProfileTemplatePreviewResult(ResponseBase):
    output_path: str
    used_variables: list[str]
    used_indexing_values: list[str] = Field(default_factory=list)
    missing_indexing_values: list[str] = Field(default_factory=list)
    provisional_indexing_values: list[str] = Field(default_factory=list)
    # The filename mode, and the characters typed in the template that it replaces.
    filename_mode: str = ""
    replaced_typed_characters: list[str] = Field(default_factory=list)
