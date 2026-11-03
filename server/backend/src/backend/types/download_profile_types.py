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


class EpisodeRuleAction(StrEnum):
    """What a Which episodes rule does with the episodes it matches."""

    SKIP = "skip"
    ONLY = "only"
    """Only download matching episodes: an episode that does not match is skipped."""
    KEEP = "keep"
    """Never stops a download; protects matching downloads from retention."""


class EpisodeRuleField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"
    DURATION = "duration"
    TYPES = "types"


class DurationOperator(StrEnum):
    SHORTER = "shorter"
    LONGER = "longer"


class RetentionFrom(StrEnum):
    """What the date window's retention counts from."""

    PUBLISHED = "published"
    DOWNLOADED = "downloaded"


class AutoSubtitles(StrEnum):
    """Whether a YouTube Download Profile downloads auto-generated subtitles."""
    NEVER = "never"
    FALLBACK = "fallback"
    ALWAYS = "always"


class SponsorBlockAction(StrEnum):
    """What a download does with one type of SponsorBlock segment."""

    KEEP = "keep"
    CHAPTER = "chapter"
    """A named chapter a player can skip."""
    CUT = "cut"
    """Removed from the file for good."""


class SponsorBlockCategory(StrEnum):
    """SponsorBlock's segment types, in the order they are shown."""

    SPONSOR = "sponsor"
    SELFPROMO = "selfpromo"
    INTERACTION = "interaction"
    INTRO = "intro"
    OUTRO = "outro"
    PREVIEW = "preview"
    FILLER = "filler"
    MUSIC_OFFTOPIC = "music_offtopic"


DEFAULT_SPONSORBLOCK_SEGMENTS: dict[str, str] = {
    SponsorBlockCategory.SPONSOR.value: SponsorBlockAction.CUT.value,
    SponsorBlockCategory.SELFPROMO.value: SponsorBlockAction.CUT.value,
    SponsorBlockCategory.INTERACTION.value: SponsorBlockAction.CUT.value,
    SponsorBlockCategory.INTRO.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.OUTRO.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.PREVIEW.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.FILLER.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.MUSIC_OFFTOPIC.value: SponsorBlockAction.KEEP.value,
}
"""A new YouTube Download Profile cuts out ads and reminders and marks intros, outros and recaps as chapters."""
