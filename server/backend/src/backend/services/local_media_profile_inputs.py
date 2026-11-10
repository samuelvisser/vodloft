"""Validated input for creating and changing Local Media Profiles.

The API's request models and the importer both hand these to the profile
services, so a profile is checked the same way wherever it comes from.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator

from backend.services.local_media_profile_sites import (
    offers_format, profile_download_options, site_offered_for_type, takes_upcoming_sites,
)
from backend.types.download_profile_types import (
    AutoSubtitles, SponsorBlockAction, SponsorBlockCategory, check_sponsorblock_segments, sponsorblock_changes_anything,
)
from backend.types.input_model import InputModel
from backend.types.local_media_profile_types import (
    GOAL_PRESETS,
    AudioCodec,
    AudioFormat,
    CodecFallback,
    CollectionLocalMediaProfileScope,
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
from backend.utils.custom_index import INDEXING_VALUE_KEY_MAX_LENGTH, is_valid_custom_index_key
from backend.utils.helpers import slugify
from backend.utils.output_template import (
    COLLECTION_OUTPUT_TEMPLATE_FIELDS,
    COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    MOVIE_OUTPUT_TEMPLATE_FIELDS,
    MOVIE_OUTPUT_TEMPLATE_METADATA_SCOPES,
    movie_template_has_media_item_field,
    output_template_custom_index_keys,
    validate_output_template_path_requirements,
)
from backend.utils.output_template_formatting import normalize_output_template_expression_spacing


_LANGUAGE_CODE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*")


def _language_code(value: str) -> str:
    if not _LANGUAGE_CODE.fullmatch(value):
        raise ValueError(f"'{value}' is not a language code such as 'en' or 'pt-BR'")
    return value


_FORMAT_NAMES = {
    PreferredFormat.FORMAT_HLS: "an HLS bundle", PreferredFormat.FORMAT_AUDIO_ONLY: "audio only",
    PreferredFormat.FORMAT_4K: "4K", PreferredFormat.FORMAT_8K: "8K",
}

class VideoCodecChoice(InputModel):
    """One codec in a Local Media Profile's order, and whether it may be used at all."""

    codec: VideoCodec
    allowed: bool

class IndexingValueDefinition(InputModel):
    key: str = Field(min_length=1, max_length=INDEXING_VALUE_KEY_MAX_LENGTH)
    name: str = Field(min_length=1, max_length=120)
    # Numbers already given out stay; new episodes take the next free number.
    keep_numbers: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not is_valid_custom_index_key(value):
            raise ValueError(
                "Indexing Value keys must use lowercase letters, numbers, underscores, and dashes, "
                "and start with a letter or underscore"
            )
        return value

class SiteDownloadChoices(InputModel):
    """What a Local Media Profile does on one Site with the settings only some Sites show."""

    auto_subtitles: AutoSubtitles
    sponsorblock_enabled: bool
    sponsorblock_segments: dict[SponsorBlockCategory, SponsorBlockAction]

    @field_validator("sponsorblock_segments")
    @classmethod
    def _every_segment_type(cls, value: dict) -> dict:
        if set(value) != {category.value for category in SponsorBlockCategory}:
            raise ValueError("Choose Keep, Chapter or Cut out for every SponsorBlock segment type")
        check_sponsorblock_segments(value)
        return value

    @model_validator(mode="after")
    def _sponsorblock_needs_a_segment_type(self):
        # Keeping every segment type does nothing: SponsorBlock is saved off, so the form opens with it collapsed.
        if not sponsorblock_changes_anything(self.sponsorblock_segments):
            self.sponsorblock_enabled = False
        return self


class LocalMediaProfileInput(InputModel):
    """What every kind of Local Media Profile is made of, validated."""

    name: str = Field(min_length=1)
    preferred_format: PreferredFormat
    download_mode: LocalMediaProfileStorageMode = LocalMediaProfileStorageMode.SYSTEM
    thumbnail_mode: LocalMediaProfileThumbnailMode = LocalMediaProfileThumbnailMode.SYSTEM
    metadata_mode: LocalMediaProfileMetadataMode = LocalMediaProfileMetadataMode.SYSTEM
    subtitle_mode: LocalMediaProfileSubtitleMode = LocalMediaProfileSubtitleMode.SIDECAR
    subtitle_languages: list[str] = Field(default_factory=lambda: ["en"], max_length=20)
    subtitle_language_mode: SubtitleLanguageMode = SubtitleLanguageMode.LISTED
    quality_goal: QualityGoal = QualityGoal.COMPATIBILITY
    video_codecs: list[VideoCodecChoice] = Field(
        default_factory=lambda: [VideoCodecChoice.model_validate(item) for item in goal_video_codecs(QualityGoal.COMPATIBILITY)],
    )
    codec_fallback: CodecFallback = CodecFallback.BEST
    container: VideoContainer = VideoContainer.MP4
    audio_codec: AudioCodec = AudioCodec.AAC
    audio_format: AudioFormat = AudioFormat.M4A
    audio_language: str | None = Field(default=None, max_length=16)
    output_template: str = Field(min_length=16, max_length=4096)
    site_keys: list[str] | None = Field(default=None, max_length=500)
    """The Sites the profile is offered for; a new profile without them starts with every Site VODLoft knows."""
    include_upcoming_sites: bool = True
    """Sites VODLoft sees for the first time join the profile's Sites."""
    site_settings: dict[str, SiteDownloadChoices] | None = Field(default=None, max_length=500)
    """Settings only some Sites show, by Site key; a Site left out follows its own from Settings."""

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
    def _validate_video_codecs(cls, value: list[VideoCodecChoice]) -> list[VideoCodecChoice]:
        if sorted(choice.codec for choice in value) != sorted(codec.value for codec in VideoCodec):
            raise ValueError("The codec order lists every codec once")
        if not any(choice.allowed for choice in value):
            raise ValueError("Allow at least one video codec")
        return value

    @model_validator(mode="after")
    def _offered_sites(self):
        if self.site_keys is None:
            return self
        self.site_keys = list(dict.fromkeys(self.site_keys))
        refused = [key for key in self.site_keys if not site_offered_for_type(self.type, key)]
        if refused:
            raise ValueError(f"This profile cannot be offered for {', '.join(refused)}")
        if not self.site_keys and not (self.include_upcoming_sites and takes_upcoming_sites(self.type)):
            raise ValueError("Choose at least one Site")
        return self

    @model_validator(mode="after")
    def _offered_format(self):
        # A profile can download what any of its Sites offers; each Site gets the nearest it has.
        options = profile_download_options(self.type, self.site_keys, self.include_upcoming_sites)
        if not offers_format(options, self.preferred_format):
            raise ValueError(f"None of this profile's Sites can download {_FORMAT_NAMES.get(self.preferred_format, self.preferred_format.removeprefix("format_"))}")
        return self

    @model_validator(mode="after")
    def _goal_sets_codecs(self):
        if self.subtitle_language_mode != SubtitleLanguageMode.SITE and not self.subtitle_languages:
            raise ValueError("Add at least one subtitle language, or download every language the site offers")
        # A goal stands for its codec order, container and audio codec.
        if "quality_goal" in self.model_fields_set and self.quality_goal != QualityGoal.CUSTOM:
            preset = GOAL_PRESETS[QualityGoal(self.quality_goal)]
            self.video_codecs = [VideoCodecChoice.model_validate(item) for item in goal_video_codecs(QualityGoal(self.quality_goal))]
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
        kept = _KEPT_WHEN_UNSET - self.model_fields_set
        # Without Sites or their settings, an update keeps the profile's own.
        return kept | {name for name in ("site_keys", "site_settings") if getattr(self, name) is None}


_KEPT_WHEN_UNSET = {
    "site_keys", "include_upcoming_sites", "site_settings", "subtitle_mode", "subtitle_languages", "subtitle_language_mode", "quality_goal", "video_codecs",
    "codec_fallback", "container", "audio_codec", "audio_format", "audio_language",
}

class CollectionLocalMediaProfileInput(LocalMediaProfileInput):
    """A Collection Local Media Profile's fields; an update leaves the kept fields it does not send."""

    type: Literal["collection"] = LocalMediaProfileType.COLLECTION.value
    collection_scope: CollectionLocalMediaProfileScope = CollectionLocalMediaProfileScope.BOTH
    download_collection_assets: bool | None = None
    indexing_values: list[IndexingValueDefinition] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _unique_index_keys(self):
        keys = [item.key for item in self.indexing_values]
        if len(keys) != len(set(keys)):
            raise ValueError("Indexing Value keys must be unique")
        return self

    @field_validator("output_template")
    @classmethod
    def _validate_output_template(cls, value: str) -> str:
        validate_output_template_path_requirements(
            value,
            allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
            allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        )
        return value


class NewCollectionLocalMediaProfile(CollectionLocalMediaProfileInput):
    """A Collection Local Media Profile to create: defaults follow its scope."""

    @model_validator(mode="after")
    def _default_subtitles_for_scope(self):
        # Scope-dependent defaults apply only when a profile is first created.
        # Updates must never infer a new subtitle mode from changed scope.
        if "subtitle_mode" not in self.model_fields_set:
            self.subtitle_mode = (
                LocalMediaProfileSubtitleMode.NO_SUBTITLES
                if self.collection_scope == CollectionLocalMediaProfileScope.PODCAST
                else LocalMediaProfileSubtitleMode.SIDECAR
            )
        return self

_MOVIE_EXTRA_COLLISION_MESSAGE = (
    "Movie and movie-extra downloads could resolve to the same file. Include at least "
    "one variable that describes the downloaded item, such as {{ title }}, {{ slug }}, "
    "{{ duration_seconds }}, or {{ media_type }}."
)

class MovieLocalMediaProfileInput(LocalMediaProfileInput):
    type: Literal["movie"] = LocalMediaProfileType.MOVIE.value
    subtitle_mode: LocalMediaProfileSubtitleMode = LocalMediaProfileSubtitleMode.SIDECAR

    @field_validator("preferred_format")
    @classmethod
    def _require_video_format(cls, value: PreferredFormat) -> PreferredFormat:
        if value in {PreferredFormat.FORMAT_AUDIO_ONLY, PreferredFormat.FORMAT_HLS}:
            raise ValueError("Movie Local Media Profiles require a normal video format")
        return value

    @field_validator("output_template")
    @classmethod
    def _validate_output_template(cls, value: str) -> str:
        validate_output_template_path_requirements(
            value,
            allowed_fields=MOVIE_OUTPUT_TEMPLATE_FIELDS,
            allowed_metadata_scopes=MOVIE_OUTPUT_TEMPLATE_METADATA_SCOPES,
        )
        if output_template_custom_index_keys(value):
            raise ValueError("custom_index is only available to Collection Local Media Profiles")
        if not movie_template_has_media_item_field(value):
            raise ValueError(_MOVIE_EXTRA_COLLISION_MESSAGE)
        return value
