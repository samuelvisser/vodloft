"""A Local Media Profile's quality and subtitle choices, and a Download Profile's SponsorBlock choices, in the downloader's terms."""
from __future__ import annotations

from typing import Sequence, TypeVar

from backend.db.models.local_media_profile import LocalMediaProfileBase
from backend.types.download_profile_types import AutoSubtitles, SponsorBlockAction
from backend.types.local_media_profile_types import CodecFallback, QualityGoal, SubtitleLanguageMode
from downloader.models import SubtitleRendition
from downloader.errors import DownloadError
from downloader.plan import YtdlpSponsorBlock, YtdlpSubtitles
from downloader.ytdlp import YtdlpQuality
from sources.ytdlp_options import OptionsRefused, ytdlp_option_arguments

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


def ytdlp_sponsorblock(enabled: bool, segments: dict[str, str]) -> YtdlpSponsorBlock:
    """Which SponsorBlock segment types a Download Profile marks as chapters and cuts out."""
    if not enabled:
        return YtdlpSponsorBlock()
    return YtdlpSponsorBlock(
        chapter=tuple(category for category, action in segments.items() if action == SponsorBlockAction.CHAPTER.value),
        cut=tuple(category for category, action in segments.items() if action == SponsorBlockAction.CUT.value),
    )


def custom_ytdlp_options(*texts: tuple[str, str]) -> tuple[str, ...]:
    """Your own yt-dlp options, as ``(where they are set, text)``, in the order yt-dlp gets them."""
    arguments: list[str] = []
    for where, text in texts:
        try:
            arguments.extend(ytdlp_option_arguments(text))
        except OptionsRefused as exc:
            raise DownloadError(f"The yt-dlp options of {where} can no longer be used. {exc}") from None
    return tuple(arguments)


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


def default_subtitle_languages(profile: LocalMediaProfileBase) -> tuple[str, ...]:
    """The languages whose subtitle players pick by default, the first one there is.

    With every language the site offers, only the first language on the list counts.
    """
    if profile.subtitle_language_mode == SubtitleLanguageMode.SITE.value:
        return tuple(profile.subtitle_languages[:1])
    return tuple(profile.subtitle_languages)
