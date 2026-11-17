from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_validator

from backend.api.models.stream_profile_fields import StreamProfileFieldsIn, StreamProfileFieldsOut
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.stream_profile_types import (
    RSS_HLS_OUTPUT_MODES,
    RssVideoOutputMode,
    StreamProfileType,
)


# ---------- Strict input (create/update) ----------
class _RssStreamProfileAPIBaseIn(StreamProfileFieldsIn):
    video_output_mode: Optional[RssVideoOutputMode] = Field(
        default_factory=lambda data: (
            None
            if data.get("preferred_format") == PreferredFormat.FORMAT_AUDIO_ONLY.value
            else RssVideoOutputMode.AUDIO_HLS
        )
    )

    @model_validator(mode="after")
    def _validate_video_output(self):
        if self.audio_only and self.video_output_mode is not None:
            raise ValueError(
                "Audio-only Stream Profiles cannot have a video output mode"
            )
        if not self.audio_only and self.video_output_mode is None:
            raise ValueError(
                "Video Stream Profiles require a video output mode"
            )

        if self.stream_live_episodes and self.audio_only:
            raise ValueError(
                "Live episode streaming requires a video preferred format"
            )
        if (
            self.stream_live_episodes
            and self.video_output_mode not in RSS_HLS_OUTPUT_MODES
        ):
            raise ValueError(
                "Live episode streaming requires an HLS video podcast output mode"
            )
        return self


class RssStreamProfileAPICreate(_RssStreamProfileAPIBaseIn):
    """Request body for creating an RSS stream profile.

    ``feed_url`` is optional: leave it unset (or blank) to have VODLoft
    generate one automatically from the request host and the profile's
    secret token. It can always be edited afterwards.
    """

    collection_id: int
    feed_url: Optional[str] = None


class RssStreamProfileAPIUpdate(_RssStreamProfileAPIBaseIn):
    """Request body for updating an RSS stream profile."""

    feed_url: str = Field(min_length=1)


# ---------- Lenient output (read) ----------
class RssStreamProfileAPIRead(StreamProfileFieldsOut):
    """Response body for an RSS stream profile."""

    type: Literal["rss"] = StreamProfileType.RSS.value
    video_output_mode: Optional[str]
    feed_url: str
