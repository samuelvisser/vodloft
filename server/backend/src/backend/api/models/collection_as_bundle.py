from __future__ import annotations
from typing import Literal, Union, Optional
from pydantic import Field

from backend.api.models.base import RequestBase
from backend.api.models.download_profile import DownloadProfileAPICreateBundle
from backend.api.models.collection_local_media_profile import (
    CollectionLocalMediaProfileAPICreate,
    CollectionLocalMediaProfileAPIUpdate,
)
from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate
from backend.api.models.season import SeasonAPIRequestDetached
from backend.api.models.collection import CollectionAPICreate


class CollectionLocalMediaProfileCreateNew(CollectionLocalMediaProfileAPICreate):
    op: Literal["create_new"] = "create_new"


class CollectionLocalMediaProfileUpdateBySlug(CollectionLocalMediaProfileAPIUpdate):
    op: Literal["update_by_slug"] = "update_by_slug"
    slug_selector: str = Field(validation_alias="slug")


CollectionLocalMediaProfileAPIUpsert = Union[
    CollectionLocalMediaProfileCreateNew,
    CollectionLocalMediaProfileUpdateBySlug,
]


class RssStreamProfileCreateInBundle(RssStreamProfileAPICreate):
    collection_id: Optional[int] = None


class CollectionAPICreateBundle(RequestBase):
    collection: CollectionAPICreate
    seasons: list[SeasonAPIRequestDetached]
    local_media_profile: Optional[CollectionLocalMediaProfileAPIUpsert] = Field(default=None, discriminator="op")
    download_profile: Optional[DownloadProfileAPICreateBundle] = None
    stream_profile: Optional[RssStreamProfileCreateInBundle] = None
