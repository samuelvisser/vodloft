from __future__ import annotations

from typing import Literal

from backend.api.models.base import RequestBase
from backend.api.models.local_media_profile import LocalMediaProfileAPIBaseOut
from backend.services.local_media_profile_inputs import VideoLocalMediaProfileInput
from backend.types.local_media_profile_types import LocalMediaProfileType, VideoLocalMediaProfileScope


class VideoLocalMediaProfileAPICreate(RequestBase, VideoLocalMediaProfileInput):
    """Create a Video Local Media Profile."""


class VideoLocalMediaProfileAPIUpdate(RequestBase, VideoLocalMediaProfileInput):
    """Update a Video Local Media Profile."""


class VideoLocalMediaProfileAPIRead(LocalMediaProfileAPIBaseOut):
    """Read a Video Local Media Profile: one for single videos, and movies with their extras."""

    type: Literal["video"] = LocalMediaProfileType.VIDEO.value
    video_scope: VideoLocalMediaProfileScope = VideoLocalMediaProfileScope.BOTH
