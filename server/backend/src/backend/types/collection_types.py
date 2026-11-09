from enum import Enum, StrEnum


class CollectionType(Enum):
    PODCAST = "podcast"
    SERIES = "series"

class EpisodeIdentifier(Enum):
    DATE_BASED = "date_based"
    NUMBERED = "numbered"
    SEASONAL = "seasonal"


class LibraryCollectionSort(StrEnum):
    """How the Library lists its Collections."""

    OFTEN_USED = "often_used"
    NAME = "name"
    RELEASE_DATE = "release_date"
    ADDED_AT = "added_at"


class EpisodeOrder(StrEnum):
    """Which way a Collection lists its episodes; a seasonal Collection orders each season."""

    NEWEST_FIRST = "newest_first"
    OLDEST_FIRST = "oldest_first"

    @classmethod
    def default_for(cls, episode_identifier: EpisodeIdentifier | str) -> "EpisodeOrder":
        """A seasonal Collection starts each season at its first episode; any other lists its newest first."""
        if EpisodeIdentifier(episode_identifier) == EpisodeIdentifier.SEASONAL:
            return cls.OLDEST_FIRST
        return cls.NEWEST_FIRST


class CookiesMode(StrEnum):
    """When a Collection's downloads use the Source's cookies file."""

    AUTOMATIC = "automatic"
    """Only after a download failed because the Source wanted someone signed in, for a week."""
    NEVER = "never"
    ALWAYS = "always"


class CheckFrequency(StrEnum):
    """How often VODLoft looks for new episodes of a Collection."""

    DEFAULT = "default"
    LESS_OFTEN = "less_often"
    """At most every few hours, for a Collection that rarely posts."""
    OWN = "own"
    """On the Collection's own schedule, in ``check_cron``."""
