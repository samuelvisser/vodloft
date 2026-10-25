from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from backend.api.models.local_media_profile import (
    LocalMediaProfileAPIBaseIn,
    LocalMediaProfileAPIBaseOut,
)
from backend.types.local_media_profile_types import LocalMediaProfileType, PreferredFormat
from backend.utils.output_template import (
    VIDEO_OUTPUT_TEMPLATE_FIELDS,
    output_template_custom_index_keys,
    validate_output_template_path_requirements,
)


class _VideoLocalMediaProfileAPIBaseIn(LocalMediaProfileAPIBaseIn):
    type: Literal["video"] = LocalMediaProfileType.VIDEO.value

    @field_validator("preferred_format")
    @classmethod
    def _reject_hls(cls, value: PreferredFormat) -> PreferredFormat:
        if value == PreferredFormat.FORMAT_HLS:
            raise ValueError("Video Local Media Profiles cannot keep an HLS bundle")
        return value

    @field_validator("output_template")
    @classmethod
    def _validate_output_template(cls, value: str) -> str:
        validate_output_template_path_requirements(value, allowed_fields=VIDEO_OUTPUT_TEMPLATE_FIELDS)
        if output_template_custom_index_keys(value):
            raise ValueError("custom_index is only available to Show Local Media Profiles")
        return value


class VideoLocalMediaProfileAPICreate(_VideoLocalMediaProfileAPIBaseIn):
    """Create a Video Local Media Profile."""


class VideoLocalMediaProfileAPIUpdate(_VideoLocalMediaProfileAPIBaseIn):
    """Update a Video Local Media Profile."""


class VideoLocalMediaProfileAPIRead(LocalMediaProfileAPIBaseOut):
    """Read a Video Local Media Profile."""

    type: Literal["video"] = LocalMediaProfileType.VIDEO.value
