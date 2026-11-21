from enum import StrEnum
from typing import NamedTuple


class LocalMediaProfileType(StrEnum):
    COLLECTION = "collection"
    """The episodes of collections: podcasts, series, and music as tracks or music videos."""
    VIDEO = "video"
    """Single videos, and movies with their extras."""

    # Only used by the polymorphic parent mapper.
    BASE = "base"

    @property
    def for_collections(self) -> bool:
        """Whether profiles of this type keep collections' episodes."""
        return self is LocalMediaProfileType.COLLECTION

    @property
    def label(self) -> str:
        return self.value.title()


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


class LocalMediaProfileFilenameMode(StrEnum):
    SYSTEM = "system"
    UNRESTRICTED = "unrestricted"
    WINDOWS = "windows"
    RESTRICTED = "restricted"


class LocalMediaProfileSubtitleMode(StrEnum):
    NO_SUBTITLES = "no_subtitles"
    EMBED = "embed"
    SIDECAR = "sidecar"
    EMBED_AND_SIDECAR = "embed_and_sidecar"


class EpisodeNfo(StrEnum):
    """What an episode's NFO file and embedded metadata call it."""
    EPISODE = "episode"
    """An episode of a show."""
    MUSIC_VIDEO = "music_video"
    """A music video by the collection's artist, which media servers keep in a Music Videos library."""


class CollectionLocalMediaProfileScope(StrEnum):
    PODCAST_AND_SERIES = "podcast-and-series"
    """Podcasts and series."""
    PODCAST = "podcast"
    SERIES = "series"
    MUSIC = "music"
    """Music collections: as audio tracks with the tags music players read when the profile downloads audio only, and
    as music videos otherwise."""

    def collection_types(self) -> tuple[str, ...]:
        """The collection types a profile with this scope keeps."""
        if self is CollectionLocalMediaProfileScope.PODCAST_AND_SERIES:
            return (CollectionLocalMediaProfileScope.PODCAST.value, CollectionLocalMediaProfileScope.SERIES.value)
        return (self.value,)


def keeps_tracks(profile) -> bool:
    """Whether a Local Media Profile keeps music collections as tracks, tagged for music players: a profile for Music
    that downloads audio only. One for Music that downloads video keeps music videos."""
    return (
        getattr(profile, "collection_scope", None) == CollectionLocalMediaProfileScope.MUSIC
        and getattr(profile, "preferred_format", None) == PreferredFormat.FORMAT_AUDIO_ONLY
    )


class VideoLocalMediaProfileScope(StrEnum):
    """What a Video profile is offered for: single videos, movies with their extras, or both."""
    BOTH = "both"
    VIDEOS = "videos"
    MOVIES = "movies"

    def keeps(self, kind: "VideoLocalMediaProfileScope") -> bool:
        return self is VideoLocalMediaProfileScope.BOTH or self is kind


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


PREFERRED_FORMAT_HEIGHTS = {
    PreferredFormat.FORMAT_360P: 360,
    PreferredFormat.FORMAT_480P: 480,
    PreferredFormat.FORMAT_720P: 720,
    PreferredFormat.FORMAT_1080P: 1080,
    PreferredFormat.FORMAT_1440P: 1440,
    PreferredFormat.FORMAT_4K: 2160,
    PreferredFormat.FORMAT_8K: 4320,
}
"""The resolution each video format downloads up to."""


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
    FLAC = "flac"
    """Lossless. It keeps what the site sends without losing more, but it is no better than the site's own audio."""


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


class EpisodeMoveOutcome(StrEnum):
    """What moving one episode's download to another Local Media Profile does."""

    MOVE = "move"
    """The download moves, and its files move into the target's layout."""
    REPLACE = "replace"
    """The target has a record of the episode without a file; the download takes its place."""
    TARGET_HAS_FILE = "target_has_file"
    """The target already has the episode, so the download stays where it is."""
    PATH_TAKEN = "path_taken"
    """A file VODLoft doesn't manage already has the new path."""
    SAME_PATH = "same_path"
    """Another moved episode gets the same new path."""
    FILE_MISSING = "file_missing"
    """The download's file is missing."""
    BUSY = "busy"
    """A download is running for the episode."""

    @property
    def moves(self) -> bool:
        return self in (EpisodeMoveOutcome.MOVE, EpisodeMoveOutcome.REPLACE)
