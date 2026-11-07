from __future__ import annotations

from typing import Literal

from backend.api.models.local_media_profile import (
    LocalMediaProfileAPIBaseOut,
)
from backend.api.models.base import RequestBase
from backend.services.local_media_profile_inputs import MovieLocalMediaProfileInput
from backend.types.local_media_profile_types import LocalMediaProfileType


class MovieLocalMediaProfileAPICreate(RequestBase, MovieLocalMediaProfileInput):
    """Create a Movie Local Media Profile."""


class MovieLocalMediaProfileAPIUpdate(RequestBase, MovieLocalMediaProfileInput):
    """Update a Movie Local Media Profile."""


class MovieLocalMediaProfileAPIRead(LocalMediaProfileAPIBaseOut):
    """Read a Movie Local Media Profile."""

    type: Literal["movie"] = LocalMediaProfileType.MOVIE.value
