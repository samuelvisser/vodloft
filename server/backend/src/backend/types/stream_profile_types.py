from enum import Enum, StrEnum
from typing import Literal


class StreamProfileType(Enum):
    RSS = "rss"
    IPTV = "iptv"
    WEBDAV = "webdav"

    # For instances of StreamProfileBase class (parent class)
    BASE = "base"


class IptvBetweenLiveEpisodes(StrEnum):
    """What an IPTV channel shows while none of its episodes is live."""

    NEWEST_EPISODE = "newest_episode"
    OFF_AIR = "off_air"
    HIDE_CHANNEL = "hide_channel"


class WebdavSeasonFolders(StrEnum):
    """How a WebDAV share sorts a show's episodes into folders."""

    SEASON = "season"
    YEAR = "year"
    NONE = "none"


class WebdavMetadataFiles(StrEnum):
    """What a WebDAV share lists beside the episodes, for media players."""

    NFO_AND_ARTWORK = "nfo_and_artwork"
    ARTWORK = "artwork"
    NONE = "none"


# What a stream profile serves of an episode: its audio, an MP4 video file or an HLS video stream.
StreamMediaKind = Literal["audio", "mp4", "hls"]


class RssVideoOutputMode(StrEnum):
    AUDIO_HLS = "audio_hls"
    AUDIO_MP4 = "audio_mp4"
    MP4 = "mp4"
    MP4_HLS = "mp4_hls"


DEFAULT_RSS_VIDEO_OUTPUT_MODE = RssVideoOutputMode.AUDIO_HLS

RSS_HLS_OUTPUT_MODES = frozenset({
    RssVideoOutputMode.AUDIO_HLS,
    RssVideoOutputMode.MP4_HLS,
})

RSS_MP4_OUTPUT_MODES = frozenset({
    RssVideoOutputMode.AUDIO_MP4,
    RssVideoOutputMode.MP4,
    RssVideoOutputMode.MP4_HLS,
})

RSS_AUDIO_PRIMARY_OUTPUT_MODES = frozenset({
    RssVideoOutputMode.AUDIO_HLS,
    RssVideoOutputMode.AUDIO_MP4,
})

# What a video feed serves of each episode in each output mode, its main enclosure first.
RSS_OUTPUT_MODE_MEDIA_KINDS: dict[RssVideoOutputMode, tuple[StreamMediaKind, ...]] = {
    RssVideoOutputMode.AUDIO_HLS: ("audio", "hls"),
    RssVideoOutputMode.AUDIO_MP4: ("audio", "mp4"),
    RssVideoOutputMode.MP4: ("mp4",),
    RssVideoOutputMode.MP4_HLS: ("mp4", "hls"),
}
