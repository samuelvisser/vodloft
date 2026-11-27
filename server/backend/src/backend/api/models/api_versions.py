from __future__ import annotations

from backend.api.models.base import ResponseBase


class ApiVersionsRead(ResponseBase):
    """Which API versions this server answers, so a client can pick one it speaks."""
    # Oldest first.
    versions: list[str]
    # The newest, which the UI uses.
    current: str
    app_version: str


class UnknownApiVersionRead(ResponseBase):
    """The answer to an API path outside every version this server answers."""
    detail: str
    versions: list[str]
    current: str
