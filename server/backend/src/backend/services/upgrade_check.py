"""The upgrade check: an episode is downloaded again later, and only when something you care about improved.

A YouTube video can get a higher resolution hours after upload, SponsorBlock segments come in over days, and
subtitles get added later. The Daily Wire sometimes edits an episode after it is out, such as cutting a long live
stream down. The check asks the Source what the video is offered as now, compares it with what the download kept,
and only then downloads it again through the usual redownload path, which keeps the old file until the new one is
complete. What can count as better is the Site's: its contract lists the improvements it offers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from backend.db.datetime_types import utc_datetime
from backend.db.models import DownloadProfile, Episode
from backend.db.models.local_media_profile import LocalMediaProfileBase
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.download_quality import ytdlp_quality, ytdlp_subtitles
from backend.types.download_profile_types import (
    AutoSubtitles, MediaDownloadArtifactStatus, SponsorBlockAction, UpgradeImprovement, UpgradeRepeat,
)
from backend.types.local_media_profile_types import LocalMediaProfileSubtitleMode, PreferredFormat
from downloader.source import FORMAT_HEIGHTS
from sources import Site, UpgradeOffer

SECOND_CHECK_DAYS = 30
"""Twice checks once more this many days after the first check."""
_MOST_CHECKS = {UpgradeRepeat.ONCE: 1, UpgradeRepeat.TWICE: 2, UpgradeRepeat.EVERY: 3}
_SEGMENT_TOLERANCE_SECONDS = 1.0
"""SponsorBlock moves a segment's edges a little as people vote; a move this small is the same segment."""


def checked_improvements(site: Site, profile: DownloadProfile) -> frozenset[str]:
    """What the profile counts as a better version, of what its collection's Site offers."""
    return frozenset(profile.upgrade_improvements) & {improvement.value for improvement in site.upgrade_checks.improvements}


def checks_profile(site: Site, profile: DownloadProfile) -> bool:
    """Whether the profile's downloads get upgrade checks."""
    return profile.upgrade_check and bool(checked_improvements(site, profile))


def length_changed(kept: float | None, offered: float | None, profile: DownloadProfile) -> bool:
    """Whether a length differs from the downloaded file's by more than the profile's minutes. An unknown length never does."""
    if not kept or not offered:
        return False
    return abs(offered - kept) > profile.upgrade_length_minutes * 60


def schedule_first_upgrade_check(download: EpisodeMediaDownload, site: Site, now: datetime) -> None:
    """Plan the first check of a download that just completed.

    A download the upgrade check itself started keeps the schedule the check gave it.
    """
    if download.upgrade_checks:
        return
    profile = download.download_profile
    if profile is None or not checks_profile(site, profile):
        download.upgrade_check_at = None
        return
    download.upgrade_check_at = now + timedelta(days=profile.upgrade_after_days)


def check_changed_lengths_now(episode: Episode, site: Site, now: datetime) -> None:
    """Check an episode's downloads right away when the metadata refresh sees a length that differs from
    their file's. The check itself measures the stream before anything is downloaded again."""
    for download in episode.downloads:
        if not isinstance(download, EpisodeMediaDownload):
            continue
        profile = download.download_profile
        if (
            profile is None or not profile.enable_profile or not profile.upgrade_check
            or UpgradeImprovement.LENGTH.value not in checked_improvements(site, profile)
            or download.artifact_status != MediaDownloadArtifactStatus.AVAILABLE.value or download.redownload_when_final
        ):
            continue
        due = download.upgrade_check_at
        if length_changed(download.duration, episode.duration, profile) and (due is None or utc_datetime(due) > now):
            download.upgrade_check_at = now


def next_upgrade_check_at(profile: DownloadProfile, checks_done: int, now: datetime) -> datetime | None:
    """When the check looks again after ``checks_done`` checks, or None once it has looked often enough."""
    repeat = UpgradeRepeat(profile.upgrade_repeat)
    if checks_done >= _MOST_CHECKS[repeat]:
        return None
    return now + timedelta(days=SECOND_CHECK_DAYS if repeat == UpgradeRepeat.TWICE else profile.upgrade_after_days)


def sponsorblock_categories(profile: DownloadProfile) -> tuple[str, ...]:
    """The SponsorBlock segment types the profile marks or cuts, which new segments of improve a download."""
    if not profile.sponsorblock_enabled or UpgradeImprovement.SPONSORBLOCK.value not in profile.upgrade_improvements:
        return ()
    return tuple(sorted(
        category for category, action in profile.sponsorblock_segments.items() if action != SponsorBlockAction.KEEP.value
    ))


@dataclass(frozen=True)
class UpgradeFindings:
    """What a check found: the improvements, and whether a later check could still find any."""

    improvements: tuple[UpgradeImprovement, ...]
    could_improve: bool
    best_height: int | None = None


def upgrade_findings(
    offer: UpgradeOffer,
    download: EpisodeMediaDownload,
    profile: DownloadProfile,
    local_media_profile: LocalMediaProfileBase,
    site: Site,
) -> UpgradeFindings:
    """Compare what the video is offered as now with what the download kept."""
    wanted = checked_improvements(site, profile)
    found: list[UpgradeImprovement] = []
    could_improve = False
    best_height: int | None = None
    is_video = local_media_profile.preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value
    target = FORMAT_HEIGHTS.get(local_media_profile.preferred_format)
    quality = ytdlp_quality(local_media_profile)
    allowed = quality.video_codecs
    videos = [video for video in offer.videos if not allowed or not quality.strict or video.codec in allowed]

    if is_video and target is not None and UpgradeImprovement.RESOLUTION.value in wanted and download.video_height:
        heights = [video.height for video in videos if video.height <= target]
        best_height = max(heights, default=None)
        if best_height is not None and best_height > download.video_height:
            found.append(UpgradeImprovement.RESOLUTION)
        elif download.video_height < target:
            could_improve = True

    if is_video and allowed and UpgradeImprovement.CODEC.value in wanted and download.video_codec and download.video_height:
        preferred = allowed[0]
        if download.video_codec != preferred:
            if any(video.codec == preferred and video.height >= download.video_height for video in offer.videos):
                found.append(UpgradeImprovement.CODEC)
            else:
                could_improve = True

    if (
        UpgradeImprovement.SUBTITLES.value in wanted
        and local_media_profile.subtitle_mode != LocalMediaProfileSubtitleMode.NO_SUBTITLES.value
        and download.subtitle_languages is not None
    ):
        new, missing = _subtitle_changes(
            offer.subtitle_languages, download.subtitle_languages, ytdlp_subtitles(local_media_profile, AutoSubtitles.NEVER),
        )
        if new:
            found.append(UpgradeImprovement.SUBTITLES)
        elif missing:
            could_improve = True

    if offer.sponsorblock is not None:
        # Segments keep arriving for days, so SponsorBlock can always improve a download later.
        could_improve = True
        kept = [segment for segment in download.sponsorblock_segments or () if isinstance(segment, dict)]
        if any(not _has_segment(kept, segment.category, segment.start, segment.end) for segment in offer.sponsorblock):
            found.append(UpgradeImprovement.SPONSORBLOCK)

    if UpgradeImprovement.LENGTH.value in wanted:
        # The site can edit an episode at any time. A countdown download is replaced by the final version anyway.
        could_improve = True
        if not download.redownload_when_final and length_changed(download.duration, offer.duration, profile):
            found.append(UpgradeImprovement.LENGTH)

    return UpgradeFindings(tuple(found), could_improve or bool(found), best_height)


def _base(language: str) -> str:
    return language.split("-", 1)[0].lower()


def _subtitle_changes(offered: frozenset[str], kept: Sequence[str], wanted) -> tuple[bool, bool]:
    """Whether a wanted subtitle the download lacks is offered now, and whether one is still missing."""
    kept_bases = {_base(language) for language in kept}
    if not wanted.languages:
        return any(_base(language) not in kept_bases for language in offered), True
    offered_bases = {_base(language) for language in offered}
    if wanted.first_only:
        # Only the first language on the list that the video has: a language earlier on the list is better.
        for language in wanted.languages:
            if _base(language) in kept_bases:
                return False, False
            if _base(language) in offered_bases:
                return True, False
        return False, True
    missing = [language for language in wanted.languages if _base(language) not in kept_bases]
    return any(_base(language) in offered_bases for language in missing), bool(missing)


def _has_segment(kept: list[dict], category: str, start: float, end: float) -> bool:
    return any(
        segment.get("category") == category
        and abs(float(segment.get("start", -1)) - start) <= _SEGMENT_TOLERANCE_SECONDS
        and abs(float(segment.get("end", -1)) - end) <= _SEGMENT_TOLERANCE_SECONDS
        for segment in kept
    )
