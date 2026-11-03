from enum import StrEnum
from typing import NamedTuple


class LocalMediaProfileType(StrEnum):
    COLLECTION = "collection"
    MOVIE = "movie"
    VIDEO = "video"

    # Only used by the polymorphic parent mapper.
    BASE = "base"


class LocalMediaProfileStorageMode(StrEnum):
    SYSTEM = "system"
    DIRECT = "direct"
    TEMPORARY = "temporary"


class LocalMediaProfileThumbnailMode(StrEnum):
    SYSTEM = "system"
    NO_THUMBNAIL = "no_thumbnail"
    EMBED = "embed"
    SIDECAR = "sidecar"
    EMBED_AND_SIDECAR = "embed_and_sidecar"


class LocalMediaProfileMetadataMode(StrEnum):
    SYSTEM = "system"
    NO_METADATA = "no_metadata"
    EMBED = "embed"
    NFO = "nfo"
    EMBED_AND_NFO = "embed_and_nfo"


class LocalMediaProfileSubtitleMode(StrEnum):
    NO_SUBTITLES = "no_subtitles"
    EMBED = "embed"
    SIDECAR = "sidecar"
    EMBED_AND_SIDECAR = "embed_and_sidecar"


class CollectionLocalMediaProfileScope(StrEnum):
    BOTH = "both"
    PODCAST = "podcast"
    SERIES = "series"


class PreferredFormat(StrEnum):
    FORMAT_4K = 'format_4k'
    FORMAT_1080P = 'format_1080p'
    FORMAT_720P = 'format_720p'
    FORMAT_HLS = 'format_hls'
    FORMAT_AUDIO_ONLY = 'format_audio_only'
    FORMAT_360P = 'format_360p'
    FORMAT_480P = 'format_480p'
    FORMAT_1440P = 'format_1440p'
    FORMAT_8K = 'format_8k'


class QualityGoal(StrEnum):
    """What a Local Media Profile optimises for on sites yt-dlp downloads from."""
    COMPATIBILITY = "compatibility"
    QUALITY = "quality"
    SMALL = "small"
    CUSTOM = "custom"


class VideoCodec(StrEnum):
    AV1 = "av1"
    VP9 = "vp9"
    H264 = "h264"
    H265 = "h265"


class CodecFallback(StrEnum):
    """When none of the allowed codecs exists: take the best version there is, or skip the episode."""
    BEST = "best"
    SKIP = "skip"


class VideoContainer(StrEnum):
    MP4 = "mp4"
    MKV = "mkv"


class AudioCodec(StrEnum):
    AAC = "aac"
    OPUS = "opus"


class AudioFormat(StrEnum):
    """The file format of an audio only download."""
    M4A = "m4a"
    OPUS = "opus"
    MP3 = "mp3"


class SubtitleLanguageMode(StrEnum):
    """Which of a profile's subtitle languages are downloaded."""
    LISTED = "listed"
    FIRST = "first"
    SITE = "site"


class GoalPreset(NamedTuple):
    """The codec order, container and audio codec a quality goal stands for."""
    video_codecs: tuple[tuple[VideoCodec, bool], ...]
    """Each codec, most wanted first, and whether it may be used at all."""
    container: VideoContainer
    audio_codec: AudioCodec


_MODERN_CODECS = ((VideoCodec.AV1, True), (VideoCodec.VP9, True), (VideoCodec.H264, True), (VideoCodec.H265, False))
GOAL_PRESETS: dict[QualityGoal, GoalPreset] = {
    QualityGoal.COMPATIBILITY: GoalPreset(
        ((VideoCodec.H264, True), (VideoCodec.AV1, False), (VideoCodec.VP9, False), (VideoCodec.H265, False)),
        VideoContainer.MP4, AudioCodec.AAC,
    ),
    QualityGoal.QUALITY: GoalPreset(_MODERN_CODECS, VideoContainer.MKV, AudioCodec.OPUS),
    QualityGoal.SMALL: GoalPreset(_MODERN_CODECS, VideoContainer.MKV, AudioCodec.OPUS),
}


def goal_video_codecs(goal: QualityGoal) -> list[dict]:
    """A goal's codec order as stored on a Local Media Profile."""
    return [{"codec": codec.value, "allowed": allowed} for codec, allowed in GOAL_PRESETS[goal].video_codecs]
