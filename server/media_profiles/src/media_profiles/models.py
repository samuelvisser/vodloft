from enum import StrEnum


class MediaKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class CollectionKind(StrEnum):
    CHANNEL = "channel"
    PLAYLIST = "playlist"
