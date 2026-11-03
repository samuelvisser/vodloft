from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import Field

from .base import RequestBase, ResponseBase


class ImportUploadFileAPIRequest(RequestBase):
    path: str = Field(min_length=1, max_length=1024, description="The file's path inside the picked folder")
    size: int = Field(ge=0)


class ImportUploadAPIRequest(RequestBase):
    """Start an upload: the files the browser picked, before it sends them."""

    files: list[ImportUploadFileAPIRequest] = Field(min_length=1, max_length=5000)
    include_secrets: bool = Field(default=False, description="Also take sign-ins such as cookies.txt")


class ImportFolderAPIRequest(RequestBase):
    folder: str = Field(min_length=1, description="A /downloads/ folder that holds the config folder")
    include_secrets: bool = False


class ImportUploadedFileAPIRead(ResponseBase):
    path: str
    size: int
    secret: bool = False
    received: Optional[int] = None


class ImportUploadInfoAPIRead(ResponseBase):
    uploaded_at: datetime
    files: list[ImportUploadedFileAPIRead]


class ImportIncomingAPIRead(ResponseBase):
    started_at: datetime
    files: list[ImportUploadedFileAPIRead]


class ImportSendAPIRead(ResponseBase):
    source: str = Field(description="The path the browser picked")
    path: str = Field(description="Where the server keeps it: the path to send its chunks to")


class ImportUploadStatusAPIRead(ResponseBase):
    upload: Optional[ImportUploadInfoAPIRead] = None
    incoming: Optional[ImportIncomingAPIRead] = None
    skipped: list[str] = Field(default_factory=list)
    send: list[ImportSendAPIRead] = Field(default_factory=list)


class ImportChunkAPIRead(ResponseBase):
    received: int


class ImportOptionsAPIRequest(RequestBase):
    """What to import, as chosen in the preview."""

    path_map: Optional[tuple[str, str]] = Field(
        default=None, description="The other program's download folder, and the /downloads/ folder that is it",
    )
    collections: Optional[list[str]] = Field(default=None, description="External ids; leave out for all")
    settings: Optional[list[str]] = Field(default=None, description="Setting keys; leave out for the recommended ones")
    enable_download_profiles: bool = False
    match_existing_files: bool = Field(default=False, description="Look for other files of each Collection after the import")
    templates: dict[str, str] = Field(default_factory=dict, description="Edited output templates by profile")


class ImportWarningAPIRead(ResponseBase):
    subject: str
    message: str
    support: Literal["exact", "close", "unsupported"]


class ImportPathMapAPIRead(ResponseBase):
    source: str
    target: str
    sampled: int
    found: int


class ImportCollectionAPIRead(ResponseBase):
    external_id: str
    title: str
    url: str
    profile_external_id: Optional[str] = None
    profile_name: Optional[str] = None
    becomes: Literal["new", "linked", "in_library"]
    collection_slug: Optional[str] = None
    files: int
    files_on_disk: int
    files_adopted: int
    suppressed: int
    missing: int
    download_profile_on: bool
    warnings: list[ImportWarningAPIRead]


class ImportPathDifferenceAPIRead(ResponseBase):
    path: str
    rendered: str


class ImportPathProofAPIRead(ResponseBase):
    identical: int
    total: int
    differences: list[ImportPathDifferenceAPIRead]
    error: Optional[str] = None


class ImportChangesAPIRead(ResponseBase):
    updated: list[str]
    kept: list[str]
    newly_mapped: list[str]


class ImportCustomIndexAPIRead(ResponseBase):
    key: str
    name: str
    keep_numbers: bool
    start: int
    step: int


class ImportProfileAPIRead(ResponseBase):
    external_id: str
    name: str
    becomes: Literal["new", "linked", "reused"]
    local_media_profile_name: Optional[str] = None
    original_template: Optional[str] = None
    output_template: Optional[str] = None
    support: Literal["exact", "close", "unsupported"]
    report: list[str]
    settings: dict[str, Any]
    custom_indexes: list[ImportCustomIndexAPIRead]
    warnings: list[ImportWarningAPIRead]
    path_proof: ImportPathProofAPIRead
    changes: Optional[ImportChangesAPIRead] = None


class ImportSettingAPIRead(ResponseBase):
    key: str
    value: Any = None
    support: Literal["exact", "close", "unsupported"]
    note: Optional[str] = None
    secret: bool
    selected: bool


class ImportRunSummaryAPIRead(ResponseBase):
    id: int
    status: Literal["running", "waiting", "finished", "failed"]
    created_at: datetime
    finished_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    counts: dict[str, int]
    error: Optional[str] = None


class ImportCountsAPIRead(ResponseBase):
    collections: int
    files: int


class ImportRecordCollectionAPIRead(ResponseBase):
    external_id: str
    title: Optional[str] = None
    url: Optional[str] = None
    becomes: str


class ImportRecordsAPIRead(ResponseBase):
    """Records an importer hands over as they are (WireLoft's): per kind, how many are new or linked."""

    kinds: dict[str, dict[str, int]]
    collections: list[ImportRecordCollectionAPIRead]


class ImportPreviewAPIRead(ResponseBase):
    importer: str
    version: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    path_map: ImportPathMapAPIRead
    collections: list[ImportCollectionAPIRead]
    profiles: list[ImportProfileAPIRead]
    settings: list[ImportSettingAPIRead]
    warnings: list[ImportWarningAPIRead]
    records: Optional[ImportRecordsAPIRead] = None
    last_run: Optional[ImportRunSummaryAPIRead] = None
    counts: ImportCountsAPIRead


class ImportReportEntryAPIRead(ResponseBase):
    kind: str
    subject: str
    message: str
    support: Optional[str] = None
    warnings: list[ImportWarningAPIRead] = Field(default_factory=list)


class ImportProblemAPIRead(ResponseBase):
    path: Optional[str] = None
    error: str


class ImportStepMatchingAPIRead(ResponseBase):
    status: Literal["waiting", "scanning", "ready", "failed", "finished"]
    found: int


class ImportStepAPIRead(ResponseBase):
    collection_slug: Optional[str] = None
    collection_title: Optional[str] = None
    status: Literal["waiting", "done", "failed"]
    files: int
    counts: dict[str, int]
    problems: list[ImportProblemAPIRead]
    download_profile_on: bool
    matching: Optional[ImportStepMatchingAPIRead] = None


class ImportRunAPIRead(ImportRunSummaryAPIRead):
    options: dict[str, Any]
    version: Optional[str] = None
    report: list[ImportReportEntryAPIRead]
    steps: list[ImportStepAPIRead]


class ImporterAPIRead(ResponseBase):
    key: str
    name: str
    files: list[str] = Field(description="The files an upload of the config folder takes, as patterns")
    secret_files: list[str] = Field(description="Sign-ins and keys among them, only sent when asked for")
    upload: ImportUploadStatusAPIRead
    last_run: Optional[ImportRunSummaryAPIRead] = None
