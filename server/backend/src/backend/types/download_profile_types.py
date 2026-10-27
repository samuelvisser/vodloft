from enum import Enum, StrEnum
from typing import Annotated

from pydantic import Field


class MediaDownloadArtifactStatus(StrEnum):
    """Persistent state of the file represented by a MediaDownload.

    Execution state deliberately does not live here. Queued/running/failed/canceled
    attempts are TaskRun/TaskOperation state; this enum only describes the artifact
    that currently exists (or does not exist) on disk.
    """

    ABSENT = "absent"
    AVAILABLE = "available"
    MISSING = "missing"
    CORRUPTED = "corrupted"


class MediaDownloadStatus(Enum):
    """Legacy wire values kept for migration/test compatibility only.

    Runtime code must use TaskRun/TaskOperation for execution state and
    MediaDownloadArtifactStatus for persistent file state.
    """

    PENDING = "pending"
    DOWNLOADED = "downloaded"
    DOWNLOADING = "downloading"
    REDOWNLOADED = "redownloaded"
    LOCAL_PROCESSING = "local_processing"
    CANCELLED = "cancelled"
    ERROR = "error"
    MISSING = "missing"
    CORRUPTED = "corrupted"


# The key of an episode tag a Source declares (sources.EpisodeTag), as profiles select it.
EpisodeTagKey = Annotated[str, Field(pattern=r"^[a-z][a-z-]*$", max_length=32)]


# Types for the episode identification field
class EpIdType(StrEnum):
    EP = "ep"
    EP_EXTRA = "ep-extra"
    TRAILER = "trailer"
    AUX = "aux"
