from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from backend.api.models.base import RequestBase
from backend.api.models.source import SourcedResponse


class VideoAPICreate(RequestBase):
    """Add a single video by its link."""

    url: str = Field(min_length=1, max_length=2048)
    # The Source that recognised the link, as POST /resolve named it.
    source_key: str = Field(min_length=1)


class VideoAPIRead(SourcedResponse):
    """A single video added on its own, outside any show."""

    id: int
    uuid: str
    slug: str
    title: str
    description: Optional[str]
    duration: float
    sharing_url: str
    author_name: Optional[str]
    author_url: Optional[str]
    published_at: Optional[datetime]
    background_image_path: Optional[str]
    thumbnail_landscape_path: Optional[str]
    thumbnail_portrait_path: Optional[str]
    thumbnail_square_path: Optional[str]
    created_at: datetime
    updated_at: datetime
