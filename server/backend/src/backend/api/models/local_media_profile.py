from __future__ import annotations

from datetime import datetime
from typing import Union

import re

from pydantic import Field, computed_field, field_validator, model_validator

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.custom_metadata import IndexingValueDefinitionAPI
from backend.api.models.pagination import CursorPageRead
from backend.types.local_media_profile_types import (
    GOAL_PRESETS,
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
    goal_video_codecs,
)
from backend.utils.output_template_formatting import normalize_output_template_expression_spacing
from sources.ytdlp_options import MAX_OPTIONS_LENGTH, OptionsRefused, ytdlp_option_arguments
from backend.utils.helpers import slugify


_LANGUAGE_CODE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*")


def _language_code(value: str) -> str:
    if not _LANGUAGE_CODE.fullmatch(value):
        raise ValueError(f"'{value}' is not a language code such as 'en' or 'pt-BR'")
    return value


def checked_ytdlp_options(value: str) -> str:
    """Your own yt-dlp options, refused with the first line that can not be used."""
    try:
        ytdlp_option_arguments(value)
    except OptionsRefused as exc:
        raise ValueError(str(exc)) from None
    return value.strip("\n")


class VideoCodecChoiceAPI(RequestBase):
    """One codec in a Local Media Profile's order, and whether it may be used at all."""

    codec: VideoCodec
    allowed: bool


class VideoCodecChoiceAPIRead(ResponseBase):
    codec: Union[VideoCodec, str]
    allowed: bool


class LocalMediaProfileAPIBaseIn(RequestBase):
    """Fields shared by all Local Media Profile request models."""

    name: str = Field(min_length=1)
    preferred_format: PreferredFormat
    download_mode: LocalMediaProfileStorageMode = LocalMediaProfileStorageMode.SYSTEM
    thumbnail_mode: LocalMediaProfileThumbnailMode = LocalMediaProfileThumbnailMode.SYSTEM
    metadata_mode: LocalMediaProfileMetadataMode = LocalMediaProfileMetadataMode.SYSTEM
    subtitle_mode: LocalMediaProfileSubtitleMode = LocalMediaProfileSubtitleMode.SIDECAR
    subtitle_languages: list[str] = Field(default_factory=lambda: ["en"], max_length=20)
    subtitle_language_mode: SubtitleLanguageMode = SubtitleLanguageMode.LISTED
    quality_goal: QualityGoal = QualityGoal.COMPATIBILITY
    video_codecs: list[VideoCodecChoiceAPI] = Field(
        default_factory=lambda: [VideoCodecChoiceAPI.model_validate(item) for item in goal_video_codecs(QualityGoal.COMPATIBILITY)],
    )
    codec_fallback: CodecFallback = CodecFallback.BEST
    container: VideoContainer = VideoContainer.MP4
    audio_codec: AudioCodec = AudioCodec.AAC
    audio_format: AudioFormat = AudioFormat.M4A
    audio_language: str | None = Field(default=None, max_length=16)
    ytdlp_options: str = Field(default="", max_length=MAX_OPTIONS_LENGTH)
    output_template: str = Field(min_length=16, max_length=4096)

    @field_validator("ytdlp_options")
    @classmethod
    def _validate_ytdlp_options(cls, value: str) -> str:
        return checked_ytdlp_options(value)

    @field_validator("subtitle_languages")
    @classmethod
    def _validate_subtitle_languages(cls, value: list[str]) -> list[str]:
        value = [_language_code(language.strip()) for language in value]
        if len(set(value)) != len(value):
            raise ValueError("Each language can be on the list once")
        return value

    @field_validator("audio_language")
    @classmethod
    def _validate_audio_language(cls, value: str | None) -> str | None:
        return _language_code(value.strip()) if value else None

    @field_validator("video_codecs")
    @classmethod
    def _validate_video_codecs(cls, value: list[VideoCodecChoiceAPI]) -> list[VideoCodecChoiceAPI]:
        if sorted(choice.codec for choice in value) != sorted(codec.value for codec in VideoCodec):
            raise ValueError("The codec order lists every codec once")
        if not any(choice.allowed for choice in value):
            raise ValueError("Allow at least one video codec")
        return value

    @model_validator(mode="after")
    def _goal_sets_codecs(self):
        if self.subtitle_language_mode != SubtitleLanguageMode.SITE and not self.subtitle_languages:
            raise ValueError("Add at least one subtitle language, or download every language the site offers")
        # A goal stands for its codec order, container and audio codec.
        if "quality_goal" in self.model_fields_set and self.quality_goal != QualityGoal.CUSTOM:
            preset = GOAL_PRESETS[QualityGoal(self.quality_goal)]
            self.video_codecs = [VideoCodecChoiceAPI.model_validate(item) for item in goal_video_codecs(QualityGoal(self.quality_goal))]
            self.container = preset.container.value
            self.audio_codec = preset.audio_codec.value
        return self

    @computed_field(return_type=str)
    @property
    def slug(self) -> str:
        return slugify(self.name)

    @field_validator("output_template", mode="before")
    @classmethod
    def _normalize_output_template(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_output_template_expression_spacing(value)
        return value

    def fields_kept_on_update(self) -> set[str]:
        """Choices an update leaves as they are when it does not send them, rather than resetting them to defaults."""
        return _KEPT_WHEN_UNSET - self.model_fields_set


_KEPT_WHEN_UNSET = {
    "subtitle_mode", "subtitle_languages", "subtitle_language_mode", "quality_goal", "video_codecs",
    "codec_fallback", "container", "audio_codec", "audio_format", "audio_language", "ytdlp_options",
}


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
    ytdlp_options: str = ""
    append_media_type_to_filename: bool
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


class LocalMediaProfileTemplateSourcePage(CursorPageRead[LocalMediaProfileTemplateSource]):
    revision: str


class LocalMediaProfileTemplatePreview(RequestBase):
    type: LocalMediaProfileType
    output_template: str = Field(min_length=1, max_length=4096)
    preferred_format: PreferredFormat
    values: dict[str, str] = Field(default_factory=dict)
    source_id: str | None = None
    local_media_profile_id: int | None = None
    indexing_values: list[IndexingValueDefinitionAPI] | None = None


class LocalMediaProfileTemplatePreviewResult(ResponseBase):
    output_path: str
    used_variables: list[str]
    used_indexing_values: list[str] = Field(default_factory=list)
    missing_indexing_values: list[str] = Field(default_factory=list)
    provisional_indexing_values: list[str] = Field(default_factory=list)
    # The filename mode, and the characters typed in the template that it replaces.
    filename_mode: str = ""
    replaced_typed_characters: list[str] = Field(default_factory=list)
