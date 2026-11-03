"""A Local Media Profile's quality and subtitle choices, in the downloader's terms."""
from __future__ import annotations

from typing import Sequence, TypeVar

from backend.db.models.local_media_profile import LocalMediaProfileBase
from backend.types.download_profile_types import AutoSubtitles
from backend.types.local_media_profile_types import CodecFallback, QualityGoal, SubtitleLanguageMode
from downloader.models import SubtitleRendition
from downloader.plan import YtdlpSubtitles
from downloader.ytdlp import YtdlpQuality

Track = TypeVar("Track", bound=SubtitleRendition)


def ytdlp_quality(profile: LocalMediaProfileBase) -> YtdlpQuality:
    """How yt-dlp should pick the version of a video for this profile."""
    return YtdlpQuality(
        video_codecs=tuple(choice["codec"] for choice in profile.video_codecs if choice["allowed"]),
        strict=profile.codec_fallback == CodecFallback.SKIP.value,
        container=profile.container,
        audio_codec=profile.audio_codec,
        audio_format=profile.audio_format,
        audio_language=profile.audio_language,
        prefer_small=profile.quality_goal == QualityGoal.SMALL.value,
    )


def ytdlp_subtitles(profile: LocalMediaProfileBase, auto_subtitles: AutoSubtitles | str) -> YtdlpSubtitles:
    """Which subtitles yt-dlp writes for this profile. ``auto_subtitles`` comes from the Download Profile."""
    every_language = profile.subtitle_language_mode == SubtitleLanguageMode.SITE.value
    return YtdlpSubtitles(
        languages=() if every_language else tuple(profile.subtitle_languages),
        first_only=profile.subtitle_language_mode == SubtitleLanguageMode.FIRST.value,
        auto_generated=AutoSubtitles(auto_subtitles).value,
    )


def chosen_subtitle_tracks(subtitles: YtdlpSubtitles, tracks: Sequence[Track]) -> list[Track]:
    """The subtitle tracks of a stream that the profile's languages ask for, in order of preference."""
    if not subtitles.languages:
        return list(tracks)
    chosen: list[Track] = []
    for wanted in subtitles.languages:
        base = wanted.split("-", 1)[0].lower()
        matching = [
            track for track in tracks
            if track.language and (track.language.lower() == wanted.lower() or track.language.split("-", 1)[0].lower() == base)
        ]
        if matching:
            chosen.extend(track for track in matching if track not in chosen)
            if subtitles.first_only:
                break
    return chosen


def first_subtitle_is_default(profile: LocalMediaProfileBase) -> bool:
    """The first language on the profile's list is the subtitle track players pick by default."""
    return profile.subtitle_language_mode != SubtitleLanguageMode.SITE.value
