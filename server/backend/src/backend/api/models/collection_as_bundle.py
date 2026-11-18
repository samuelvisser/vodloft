from __future__ import annotations
from typing import Literal, Union, Optional
from pydantic import Field

from backend.api.models.base import RequestBase
from backend.api.models.download_profile import DownloadProfileAPICreateBundle
from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate
from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate
from backend.api.models.existing_files import ExistingFilesSetup
from backend.api.models.season import SeasonAPIRequestDetached
from backend.api.models.collection import CollectionAPICreate


class CollectionLocalMediaProfileCreateNew(CollectionLocalMediaProfileAPICreate):
    op: Literal["create_new"] = "create_new"


class CollectionLocalMediaProfileUseExisting(RequestBase):
    """Use an existing profile as it is: the wizard never changes a profile other collections share."""
    op: Literal["use_existing"] = "use_existing"
    slug: str


CollectionLocalMediaProfileAPIChoice = Union[
    CollectionLocalMediaProfileCreateNew,
    CollectionLocalMediaProfileUseExisting,
]


class RssStreamProfileCreateInBundle(RssStreamProfileAPICreate):
    collection_id: Optional[int] = None


class CollectionAPICreateBundle(RequestBase):
    collection: CollectionAPICreate
    seasons: list[SeasonAPIRequestDetached]
    local_media_profile: Optional[CollectionLocalMediaProfileAPIChoice] = Field(default=None, discriminator="op")
    download_profile: Optional[DownloadProfileAPICreateBundle] = None
    stream_profile: Optional[RssStreamProfileCreateInBundle] = None
    existing_files: Optional[ExistingFilesSetup] = None
    """Match the files in this folder once the episodes are indexed; the Download Profile waits for it."""
