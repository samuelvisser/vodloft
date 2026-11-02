from enum import Enum


class CollectionType(Enum):
    PODCAST = "podcast"
    SERIES = "series"

class EpisodeIdentifier(Enum):
    DATE_BASED = "date_based"
    NUMBERED = "numbered"
    SEASONAL = "seasonal"