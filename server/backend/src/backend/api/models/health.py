from __future__ import annotations

from typing import Optional

from backend.api.models.base import ResponseBase
from backend.services.health import HealthStatus


class HealthCheckRead(ResponseBase):
    name: str
    status: HealthStatus
    detail: str


class DiskSpaceRead(ResponseBase):
    free_bytes: int
    total_bytes: int


class HealthRead(ResponseBase):
    status: HealthStatus
    version: str
    checks: list[HealthCheckRead]
    disk: Optional[DiskSpaceRead] = None
