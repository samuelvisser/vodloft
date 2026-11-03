from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field

from .base import RequestBase, ResponseBase


class ExistingFilesScanAPIRequest(RequestBase):
    local_media_profile_id: int = Field(gt=0)
    folder: str = Field(min_length=1, description="A /downloads/ folder")
    template: Optional[str] = Field(default=None, description="The old layout, to read names with")


class ExistingFilesSetup(RequestBase):
    """Set up while adding a Collection: scan this folder once the episodes are indexed."""

    folder: str = Field(min_length=1)
    template: Optional[str] = None


class ExistingFileAdoption(RequestBase):
    path: str
    episode_id: int = Field(gt=0)


class ExistingFilesAdoptAPIRequest(RequestBase):
    local_media_profile_id: int = Field(gt=0)
    matches: list[ExistingFileAdoption] = Field(max_length=500)


class ExistingFilesFinishAPIRequest(RequestBase):
    local_media_profile_id: int = Field(gt=0)


class ExistingFileEpisodeAPIRead(ResponseBase):
    id: int
    slug: str
    title: str
    date: Optional[str] = None
    collection_slug: str
    collection_title: str


class ExistingFileAPIRead(ResponseBase):
    path: str
    size: int
    episode: Optional[ExistingFileEpisodeAPIRead] = None
    matched_by: Optional[str] = None
    confidence: Optional[Literal["certain", "likely", "review"]] = None
    candidates: list[ExistingFileEpisodeAPIRead] = Field(default_factory=list)
    note: Optional[str] = None
    adopted: bool = False


class ExistingFilesCountsAPIRead(ResponseBase):
    certain: int
    likely: int
    review: int
    unmatched: int
    adopted: int


class ExistingFilesScanAPIRead(ResponseBase):
    status: Literal["none", "waiting", "scanning", "ready", "failed", "finished"]
    error: Optional[str] = None
    folder: Optional[str] = None
    template: Optional[str] = None
    default_folder: str
    local_media_profile_id: int
    held_download_profiles: int = 0
    counts: Optional[ExistingFilesCountsAPIRead] = None
    episodes_without_file: int = 0
    files: list[ExistingFileAPIRead] = Field(default_factory=list)


class ExistingFilesScanSummaryAPIRead(ResponseBase):
    status: Literal["waiting", "scanning", "ready", "failed", "finished"]
    local_media_profile_id: int
    held_download_profiles: int = 0
    counts: ExistingFilesCountsAPIRead


class ExistingFilesOpenScanAPIRead(ExistingFilesScanSummaryAPIRead):
    """A scan of any Collection that still needs a person, for the page that reviews them all."""

    collection_slug: str
    collection_title: str
    local_media_profile_name: str
    folder: str
    error: Optional[str] = None


class ExistingFilesProfileCollectionAPIRead(ResponseBase):
    collection_slug: str
    collection_title: str
    status: Literal["waiting", "scanning", "ready", "failed", "finished"]


class ExistingFilesProfileReviewAPIRead(ResponseBase):
    """Every open scan of one Local Media Profile, as one review of its whole folder."""

    status: Literal["waiting", "scanning", "ready", "failed", "finished"]
    folder: str
    local_media_profile_id: int
    held_download_profiles: int = 0
    counts: ExistingFilesCountsAPIRead
    episodes_without_file: int = 0
    files: list[ExistingFileAPIRead] = Field(default_factory=list)
    collections: list[ExistingFilesProfileCollectionAPIRead] = Field(default_factory=list)


class ExistingFilesProfileScanAPIResult(ResponseBase):
    collections: int


class ExistingFilesAdoptAPIResult(ResponseBase):
    adopted: int
    errors: list[dict[str, str]] = Field(default_factory=list)


class ExistingFilesFinishAPIResult(ResponseBase):
    download_profiles_enabled: int


class FolderListAPIRead(ResponseBase):
    folder: str
    parent: Optional[str] = None
    folders: list[str]
