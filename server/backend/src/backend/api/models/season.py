from datetime import datetime

from backend.api.models.base import RequestBase, ResponseBase


# ---------- Strict input (create/update) ----------
class _SeasonAPIBaseIn(RequestBase):
    """Fields for requests: validate here if needed."""

    name: str


class SeasonAPIRequestDetached(_SeasonAPIBaseIn):
    """Request body without external relations, allowing for dynamic insertion"""

    slug: str


class SeasonAPICreate(_SeasonAPIBaseIn):
    """Request body for creating a season."""

    collection_id: int
    index: int
    slug: str


class SeasonAPIUpdate(_SeasonAPIBaseIn):
    """Request body for updating a season."""

    index: int


# ---------- Lenient output (read) ----------
class _SeasonAPIBaseOut(ResponseBase):
    """Fields for responses: no validators, no constraints."""
    id: int
    collection_id: int
    index: int
    name: str
    slug: str
    season_type: str
    season_number: int


class SeasonAPIRead(_SeasonAPIBaseOut):
    """Response body for a season."""
    created_at: datetime
    updated_at: datetime
    newest_published_at: datetime | None = None
    """When its newest episode came out, in the list of a collection's seasons."""
    whole_channel: bool = False
    """The channel season while it holds the whole channel, such as Channel on YouTube: a collection page opens on it."""




