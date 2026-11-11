from __future__ import annotations

from datetime import datetime
from typing import Union


from pydantic import Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.services.local_media_profile_inputs import IndexingValueDefinition, LocalMediaProfileInput, VideoCodecChoice
from backend.api.models.pagination import CursorPageRead
from backend.api.models.source import DownloadOptionsAPIRead
from backend.types.download_profile_types import AutoSubtitles, SponsorBlockAction
from sources import SiteSetting
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


class SiteDownloadChoicesAPIRead(ResponseBase):
    """What a Local Media Profile does with the settings only some Sites show."""

    auto_subtitles: AutoSubtitles
    sponsorblock_enabled: bool
    sponsorblock_segments: dict[str, SponsorBlockAction]


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
    site_keys: list[str]
    include_upcoming_sites: bool
    auto_subtitles: AutoSubtitles
    sponsorblock_enabled: bool
    sponsorblock_segments: dict[str, SponsorBlockAction]
    created_at: datetime
    updated_at: datetime


class LocalMediaProfileSiteAPIRead(ResponseBase):
    """A Site VODLoft knows, with the profile types that can store media from it."""

    key: str
    name: str
    profile_types: list[LocalMediaProfileType]
    download_options: DownloadOptionsAPIRead
    settings: list[SiteSetting]
    """The settings only some Sites show that apply to this Site, such as YouTube's SponsorBlock."""


class LocalMediaProfileSitesAPIRead(ResponseBase):
    """Every Site a Local Media Profile can be offered for, and what Sites VODLoft has not seen yet bring."""

    sites: list[LocalMediaProfileSiteAPIRead]
    upcoming_profile_types: list[LocalMediaProfileType]
    """The profile types that can include upcoming Sites."""
    upcoming_download_options: DownloadOptionsAPIRead
    upcoming_settings: list[SiteSetting]
    """The settings only some Sites show that apply to a Site VODLoft has not seen yet."""
    defaults: SiteDownloadChoicesAPIRead
    """What a new profile starts with for the settings only some Sites show."""


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
