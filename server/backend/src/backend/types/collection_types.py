from enum import Enum, StrEnum


class CollectionType(Enum):
    PODCAST = "podcast"
    SERIES = "series"

class EpisodeIdentifier(Enum):
    DATE_BASED = "date_based"
    NUMBERED = "numbered"
    SEASONAL = "seasonal"


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
