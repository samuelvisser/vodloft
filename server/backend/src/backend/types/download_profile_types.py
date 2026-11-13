from enum import StrEnum
from typing import Annotated

from pydantic import Field

from config.settings.site_settings import (  # noqa: F401  (the Download Profile's options, defined with its defaults)
    DEFAULT_SPONSORBLOCK_SEGMENTS, DEFAULT_UPGRADE_IMPROVEMENTS, AutoSubtitles, SponsorBlockAction, SponsorBlockCategory,
    UpgradeImprovement, UpgradeRepeat, check_sponsorblock_segments, sponsorblock_changes_anything,
)


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


# The key of an episode tag a Source declares (sources.EpisodeTag), as profiles select it.
EpisodeTagKey = Annotated[str, Field(pattern=r"^[a-z][a-z-]*$", max_length=32)]


# Types for the episode identification field
class EpIdType(StrEnum):
    EP = "ep"
    EP_EXTRA = "ep-extra"
    TRAILER = "trailer"
    AUX = "aux"


class EpisodeFilterAction(StrEnum):
    """What a Which episodes filter does with the episodes it matches."""

    SKIP = "skip"
    ONLY = "only"
    """Only download matching episodes: an episode that does not match is skipped."""
    KEEP = "keep"
    """Never stops a download; protects matching downloads from retention."""


class EpisodeFilterField(StrEnum):
    """What a Which episodes filter looks at."""

    TITLE = "title"
    DESCRIPTION = "description"
    DURATION = "duration"
    TYPES = "types"
    SEASONS = "seasons"
    PUBLISHED = "published"
    """A date line: the last N days, the latest N episodes, or since a date."""
    DOWNLOADED = "downloaded"
    """A date line: published in the last N days, deleted N days after downloading."""


DATE_FIELDS = (EpisodeFilterField.PUBLISHED, EpisodeFilterField.DOWNLOADED)


class DownloadKeptBy(StrEnum):
    """What keeps a download safe from deletion."""
    HAND = "hand"
    """Someone marked it to keep."""
    KEEP_FILTER = "keep_filter"
    """A Keep filter of its Download Profile."""
    KEEP_QUESTION = "keep_question"
    """Its episode left the Source, and the Home page still asks whether to keep it."""


class DurationOperator(StrEnum):
    SHORTER = "shorter"
    LONGER = "longer"


class UpgradeResult(StrEnum):
    """What the last upgrade check of a download found."""
    UPGRADED = "upgraded"
    CHECKED = "checked"
