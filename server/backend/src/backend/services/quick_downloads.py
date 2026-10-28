"""Quick downloads: files fetched for one browser download, never part of the library.

A quick download has no media row and no MediaDownload. While it runs it is a
TaskOperation; once ready, the manifest in its folder inside the temporary root
describes it. Nothing here is read by the file watcher or by verification.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from backend.services import quick_download_history
from backend.utils.output_template import sanitize_path_component
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode
from downloader import DownloadError, EncryptedMediaError, MediaUnavailableError, SubscriptionRequiredError
from downloader.lifecycle import DownloadTracker
from downloader.metadata import MediaServerMetadata
from downloader.plan import DownloadPlan, ResolvedDownloadSource, SidecarSpec, build_download_plan
from downloader.source import FORMAT_HEIGHTS, resolve_download_source
from downloader.storage.quick import (
    QuickFolder,
    QuickManifest,
    QuickSweep,
    ensure_free_space,
    open_quick_folder,
    quick_folder_path,
    remove_quick_folder,
    sweep_quick_folders,
    write_manifest,
)
from downloader.ytdlp import resolve_ytdlp_quick_source, resolve_ytdlp_source
from sources import Feature, LinkKind, PlaybackKind, Source, VideoFormat, VideoFormats, get_source

logger = logging.getLogger(__name__)

_GIGABYTE = 1024 ** 3
_BEST_VIDEO = "format_4k"
"""Without Feature.FORMAT_CHOICES, Best is the highest resolution the Source has (4K or less)."""
_MAX_FILE_STEM = 150


QUALITY_STEPS = (2160, 1440, 1080, 720, 480)
"""The heights offered besides Best, highest first."""
MP3_BITRATES = (320, 192, 128)
CODEC_NAMES = {"h264": "H.264", "h265": "H.265", "vp9": "VP9", "av1": "AV1"}
_CODEC_PREFERENCE = ("av1", "vp9", "h265", "h264")
"""The order yt-dlp prefers codecs in by default, best first, for Best's size estimate."""


@dataclass(frozen=True)
class QuickChoice:
    """What the file should be: video in a quality, container and codec, or audio in a format.

    ``quality`` None is Best and ``codec`` None is Auto: yt-dlp's own choice
    for a Source with Feature.FORMAT_CHOICES, the highest resolution otherwise.
    """

    kind: Literal["video", "audio"] = "video"
    quality: int | None = None
    container: Literal["mp4", "mkv"] = "mp4"
    codec: Literal["h264", "h265", "vp9", "av1"] | None = None
    audio_format: Literal["m4a", "mp3"] = "m4a"
    audio_bitrate: int | None = None
    """MP3 only, in kbps. None is 320."""
    embed_metadata: bool = True
    embed_artwork: bool = True

    def __post_init__(self) -> None:
        if self.quality is not None and self.quality not in QUALITY_STEPS:
            raise ValueError(f"Quality must be Best or one of {', '.join(f'{h}p' for h in QUALITY_STEPS)}")
        if self.audio_bitrate is not None and self.audio_bitrate not in MP3_BITRATES:
            raise ValueError(f"MP3 bitrate must be one of {', '.join(f'{b} kbps' for b in MP3_BITRATES)}")

    @property
    def mp3_bitrate(self) -> int:
        return self.audio_bitrate or MP3_BITRATES[0]

    @property
    def is_basic(self) -> bool:
        """Best MP4 video or M4A audio: the choices every Source offers."""
        if self.kind == "audio":
            return self.audio_format == "m4a"
        return self.quality is None and self.container == "mp4" and self.codec is None

    @property
    def label(self) -> str:
        if self.kind == "audio":
            if self.audio_format == "mp3":
                return f"Audio · MP3 {self.mp3_bitrate} kbps"
            return f"Audio · {self.audio_format.upper()}"
        quality = f"{self.quality}p" if self.quality else "Best"
        codec = f" · {CODEC_NAMES[self.codec]}" if self.codec else ""
        return f"Video · {quality} {self.container.upper()}{codec}"


@dataclass(frozen=True)
class QuickDownloadRequest:
    """A resolved link and the choice made for it, as the worker receives it."""

    id: str
    source_key: str
    kind: LinkKind
    slug: str
    url: str
    title: str
    choice: QuickChoice = field(default_factory=QuickChoice)
    description: str | None = None
    image_url: str | None = None
    author_name: str | None = None

    def task_input(self) -> dict[str, Any]:
        return {**asdict(self), "kind": self.kind.value}

    @classmethod
    def from_task_input(cls, data: dict[str, Any]) -> QuickDownloadRequest:
        return cls(**{**data, "kind": LinkKind(data["kind"]), "choice": QuickChoice(**data.get("choice") or {})})


class QuickDownloadRefused(ValueError):
    """The link cannot be quick downloaded; the message says why."""


def check_quick_downloadable(source: Source, kind: LinkKind, *, drm_protected: bool, needs_subscription: bool) -> None:
    """Refuse a link before anything starts, with the same rules the download enforces later."""
    if drm_protected:
        raise QuickDownloadRefused(f"{source.name} protects this video with DRM, so VODLoft cannot download it")
    if needs_subscription:
        raise QuickDownloadRefused(
            f"{source.name} only gives this video to {source.subscription_name or 'paying'} subscribers"
        )
    if kind is LinkKind.SHOW:
        raise QuickDownloadRefused("Quick download takes one video, episode or movie, not a whole show or channel")


def check_quick_choice(source: Source, choice: QuickChoice) -> None:
    """Refuse a format the Source does not offer."""
    if not choice.is_basic and not source.has(Feature.FORMAT_CHOICES):
        raise QuickDownloadRefused(f"{source.name} downloads only as Best MP4 video or M4A audio")


@dataclass(frozen=True)
class QuickRules:
    """The limits in Settings › Quick download on what anyone may choose. None is no limit."""

    max_quality: int | None = None
    allowed_formats: frozenset[str] = frozenset({"mp4", "mkv", "m4a", "mp3"})
    fixed_codec: str | None = None
    max_bytes: int | None = None
    max_duration: float | None = None
    """In seconds."""
    allowed_sources: frozenset[str] | None = None
    lock_to_defaults: bool = False

    @classmethod
    def from_settings(cls) -> QuickRules:
        quick = get_settings().quick_download
        formats = {name for name, allowed in (
            ("mp4", quick.allow_mp4), ("mkv", quick.allow_mkv), ("m4a", quick.allow_m4a), ("mp3", quick.allow_mp3),
        ) if allowed}
        sources = frozenset(key.strip() for key in quick.allowed_sources.split(",") if key.strip())
        return cls(
            max_quality=None if quick.max_quality == "best" else int(str(quick.max_quality).removesuffix("p")),
            allowed_formats=frozenset(formats),
            fixed_codec=None if quick.fixed_codec == "auto" else str(quick.fixed_codec),
            max_bytes=int(quick.max_file_gigabytes * _GIGABYTE) or None,
            max_duration=quick.max_duration_minutes * 60 or None,
            allowed_sources=sources or None,
            lock_to_defaults=quick.lock_to_defaults,
        )


def default_choice() -> QuickChoice:
    """The choice Settings › Quick download starts the page with."""
    quick = get_settings().quick_download
    return QuickChoice(
        kind=str(quick.default_kind),
        quality=None if quick.default_quality == "best" else int(str(quick.default_quality).removesuffix("p")),
        container=str(quick.default_container),
        codec=None if quick.default_codec == "auto" else str(quick.default_codec),
        audio_format=str(quick.default_audio_format),
        audio_bitrate=quick.default_mp3_bitrate,
        embed_metadata=quick.embed_metadata,
        embed_artwork=quick.embed_artwork,
    )


def apply_quick_rules(source: Source, choice: QuickChoice, rules: QuickRules) -> QuickChoice:
    """The choice as the rules make it: the defaults when they are locked, and the fixed codec."""
    if rules.lock_to_defaults:
        choice = default_choice()
        if not source.has(Feature.FORMAT_CHOICES):
            choice = replace(choice, quality=None, container="mp4", codec=None, audio_format="m4a")
    if rules.fixed_codec and choice.kind == "video" and source.has(Feature.FORMAT_CHOICES):
        choice = replace(choice, codec=rules.fixed_codec)
    return choice


def check_quick_rules(
    source: Source, choice: QuickChoice, rules: QuickRules, *,
    size_bytes: int | None = None, duration: float | None = None, codecs: Iterable[str] | None = None,
) -> None:
    """Refuse what the rules do not allow. Sizes, durations and codecs are checked when they are known."""
    if rules.allowed_sources is not None and source.id not in rules.allowed_sources:
        raise QuickDownloadRefused(f"Quick download from {source.name} is turned off in Settings")
    picked = choice.audio_format if choice.kind == "audio" else choice.container
    if picked not in rules.allowed_formats:
        raise QuickDownloadRefused(f"{picked.upper()} is not allowed by the rules in Settings")
    if choice.kind == "video" and rules.max_quality and choice.quality and choice.quality > rules.max_quality:
        raise QuickDownloadRefused(f"{choice.quality}p is above the {rules.max_quality}p limit in Settings")
    if choice.kind == "video" and rules.fixed_codec and source.has(Feature.FORMAT_CHOICES):
        if choice.codec != rules.fixed_codec:
            raise QuickDownloadRefused(f"The rules in Settings allow only {CODEC_NAMES[rules.fixed_codec]} video")
        if codecs is not None and rules.fixed_codec not in set(codecs):
            raise QuickDownloadRefused(f"This video is not offered in {CODEC_NAMES[rules.fixed_codec]}, which the rules in Settings require")
    if rules.max_bytes and size_bytes and size_bytes > rules.max_bytes:
        raise QuickDownloadRefused(
            f"This file would be about {size_bytes / _GIGABYTE:.1f} GB, more than the {rules.max_bytes / _GIGABYTE:g} GB the rules in Settings allow"
        )
    if rules.max_duration and duration and duration > rules.max_duration:
        raise QuickDownloadRefused(
            f"This video is {round(duration / 60)} minutes long, longer than the {round(rules.max_duration / 60)} minutes the rules in Settings allow"
        )


def _best_format(rules: QuickRules) -> str:
    """Best without format choices: the highest resolution, held to the quality limit."""
    if rules.max_quality is None:
        return _BEST_VIDEO
    fitting = [name for name, height in FORMAT_HEIGHTS.items() if height <= rules.max_quality]
    return max(fitting, key=FORMAT_HEIGHTS.__getitem__) if fitting else min(FORMAT_HEIGHTS, key=FORMAT_HEIGHTS.__getitem__)


def quick_file_name(title: str, extension: str) -> str:
    """The title as a file name, made safe by the same rules as library files."""
    mode = FilenameRestrictionMode(get_settings().download_settings.filename_restriction_mode)
    stem = (title.strip() or "Quick download")[:_MAX_FILE_STEM]
    return sanitize_path_component(f"{stem}.{extension}", mode=mode)


def _video_details(source: Source, request: QuickDownloadRequest):
    """A listed video's date, duration and channel, for its tags; the preview has the rest."""
    if not (source.has(Feature.VIDEOS) or source.has(Feature.EPISODE_LISTS)):
        return None
    try:
        return source.video_details(request.url)
    except Exception:
        logger.info("Could not look up details of '%s' for its tags", request.url, exc_info=True)
        return None


def _metadata(source: Source, request: QuickDownloadRequest, details) -> MediaServerMetadata:
    author = (details.author_name if details is not None else None) or request.author_name
    published = details.published_at if details is not None else None
    return MediaServerMetadata(
        kind="movie" if request.kind is LinkKind.MOVIE else "video",
        title=request.title,
        description=request.description,
        source_url=request.url,
        show_title=author,
        aired=published.date() if isinstance(published, datetime) else published if isinstance(published, date) else None,
        duration_seconds=details.duration if details is not None else None,
        authors=(author,) if author else (),
        studios=() if source.has(Feature.EPISODE_LISTS) else (source.name,),
        media_type="movie" if request.kind is LinkKind.MOVIE else "video",
    )


def _resolve_source(
    source: Source, request: QuickDownloadRequest, tracker: DownloadTracker, rules: QuickRules,
) -> ResolvedDownloadSource:
    settings = get_settings().download_settings
    choice = request.choice
    check_quick_choice(source, choice)
    check_quick_rules(source, choice, rules)
    best = _best_format(rules)
    audio_only = choice.kind == "audio"
    if request.kind is LinkKind.SHOW:
        raise DownloadError("Quick download takes one video, episode or movie, not a whole show")
    if request.kind is LinkKind.MOVIE:
        tracker.preparing("resolve_playback")
        playback = source.movie_playback(movie_slug=request.slug, title=request.title, duration=None)
        tracker.ensure_active()
        tracker.preparing("inspect_stream")
        return resolve_download_source(
            playback.url, preferred_format=best, audio_only=audio_only, remux_video_to_mp4=True,
            video_fallback_for_audio=audio_only, cancellation=tracker.is_canceled,
        )
    if request.kind is LinkKind.VIDEO or source.has(Feature.EPISODE_LISTS):
        tracker.preparing("resolve_playback")
        playback = source.video_playback(slug=request.slug, url=request.url)
        tracker.ensure_active()
        if playback.drm_protected:
            raise EncryptedMediaError(f"{source.name} protects '{request.title}' with DRM")
        if playback.needs_subscription:
            raise SubscriptionRequiredError(
                f"{source.name} only gives '{request.title}' to {source.subscription_name or 'paying'} subscribers"
            )
        if playback.kind is PlaybackKind.YTDLP:
            if source.has(Feature.FORMAT_CHOICES):
                return resolve_ytdlp_quick_source(
                    playback.url, command=playback.command, audio_only=audio_only,
                    container=choice.container, height=choice.quality or rules.max_quality, codec=choice.codec,
                    audio_format=choice.audio_format,
                    audio_bitrate=choice.mp3_bitrate if choice.audio_format == "mp3" else None,
                    strict_codec=choice.kind == "video" and rules.fixed_codec is not None,
                    max_bytes=rules.max_bytes, ffmpeg_path=settings.ffmpeg_path,
                )
            return resolve_ytdlp_source(
                playback.url, command=playback.command, preferred_format=best,
                audio_only=audio_only, ffmpeg_path=settings.ffmpeg_path,
            )
        tracker.preparing("inspect_stream")
        return resolve_download_source(
            playback.url, preferred_format=best, audio_only=audio_only, remux_video_to_mp4=True,
            video_fallback_for_audio=audio_only, cancellation=tracker.is_canceled,
        )

    # An episode of a show the Source does not list, such as The Daily Wire's.
    # Free episodes play without an account; members-only ones need the
    # signed-in account, so only those are asked for with it.
    tracker.preparing("resolve_playback")
    media = source.episode_media(slug=request.slug, members_only=False, interactive=True)
    if not (media.video_url or media.audio_url):
        tracker.ensure_active()
        media = source.episode_media(slug=request.slug, members_only=True, interactive=True)
    tracker.ensure_active()
    if media.drm_protected:
        raise EncryptedMediaError(f"{source.name} protects '{request.title}' with DRM")
    url = media.audio_url if audio_only and media.audio_url else media.video_url
    if not url:
        raise MediaUnavailableError(f"{source.name} provides no playable media for '{request.title}'")
    tracker.preparing("inspect_stream")
    return resolve_download_source(
        url, preferred_format=best, audio_only=audio_only, remux_video_to_mp4=True,
        video_fallback_for_audio=audio_only and url == media.video_url, cancellation=tracker.is_canceled,
    )


def prepare_quick_download_plan(request: QuickDownloadRequest, folder: Path, tracker: DownloadTracker) -> DownloadPlan:
    """Look up the link at its Source and plan a download into the quick download's own folder."""
    settings = get_settings()
    download_settings, quick_settings = settings.download_settings, settings.quick_download
    source = get_source(request.source_key)
    rules = QuickRules.from_settings()
    resolved = _resolve_source(source, request, tracker, rules)
    tracker.ensure_active()
    check_quick_rules(source, request.choice, rules, size_bytes=resolved.expected_bytes)
    ensure_free_space(
        download_settings.temporary_download_root, expected_bytes=resolved.expected_bytes,
        keep_free_bytes=int(quick_settings.keep_free_gigabytes * _GIGABYTE),
    )
    tracker.preparing("plan_outputs")
    details = _video_details(source, request) if request.choice.embed_metadata or rules.max_duration else None
    check_quick_rules(source, request.choice, rules, duration=details.duration if details is not None else None)
    assets: tuple[SidecarSpec, ...] = ()
    artwork_id = None
    if request.choice.embed_artwork and request.image_url:
        assets = (SidecarSpec(
            "artwork", "thumbnail", url=request.image_url, extension="jpg", publish=False, required=False,
            allowed_extensions=("jpg", "jpeg", "png", "webp"),
        ),)
        artwork_id = "artwork"
    tags = tuple(_metadata(source, request, details).ffmpeg_tags().items()) if request.choice.embed_metadata else ()
    return build_download_plan(
        source=resolved, requested_destination=folder / quick_file_name(request.title, resolved.extension),
        download_mode="temporary", temporary_root=download_settings.temporary_download_root,
        ffmpeg_path=download_settings.ffmpeg_path, assets=assets, metadata_tags=tags,
        artwork_asset_id=artwork_id, attempt_id=tracker.attempt_id,
        media_lane=(f"source:{source.id}", streams) if (streams := source.download_streams) else None,
    )


@dataclass(frozen=True)
class CodecOption:
    codec: str
    size_bytes: int | None = None


@dataclass(frozen=True)
class VideoOption:
    """One row of the option list: Best, or one quality step the video has."""

    quality: int | None
    size_bytes: int | None = None
    """For Auto: the stream yt-dlp would most likely pick, plus audio."""
    codec: str | None = None
    """For Auto: the codec of that stream."""
    codecs: tuple[CodecOption, ...] = ()


@dataclass(frozen=True)
class AudioOption:
    audio_format: Literal["m4a", "mp3"]
    bitrate: int | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class QuickOptions:
    """What a link can be quick downloaded as, with sizes where the Source reports them."""

    format_choices: bool
    containers: tuple[str, ...]
    videos: tuple[VideoOption, ...]
    audio: tuple[AudioOption, ...]
    duration: float | None = None


def _step(height: int) -> int:
    """The quality step a stream counts as: the lowest step it fits, give or take a few lines, 4K and up as 2160p.

    Some encodes are a few lines taller than their step, such as 1088 for 1080p.
    """
    for step in reversed(QUALITY_STEPS):
        if height <= step * 1.05:
            return step
    return QUALITY_STEPS[0]


def _likely(formats: list[VideoFormat]) -> VideoFormat:
    """The stream yt-dlp's default sort most likely takes: highest, then by codec, then largest."""
    def rank(entry: VideoFormat):
        codec = _CODEC_PREFERENCE.index(entry.codec) if entry.codec in _CODEC_PREFERENCE else len(_CODEC_PREFERENCE)
        return (-entry.height, codec, -(entry.size_bytes or 0))
    return min(formats, key=rank)


def _plus(size: int | None, audio: int | None) -> int | None:
    return size + (audio or 0) if size else None


def quick_options(source: Source, url: str) -> QuickOptions:
    """The choices for a link: every quality and codec for a Source with Feature.FORMAT_CHOICES, Best and M4A otherwise."""
    if not source.has(Feature.FORMAT_CHOICES):
        return QuickOptions(
            format_choices=False, containers=("mp4",),
            videos=(VideoOption(quality=None),), audio=(AudioOption("m4a"),),
        )
    formats: VideoFormats = source.video_formats(url)
    audio_size = formats.audio_size_bytes
    by_step: dict[int, list[VideoFormat]] = {}
    for entry in formats.videos:
        by_step.setdefault(_step(entry.height), []).append(entry)

    def option(quality: int | None, entries: list[VideoFormat]) -> VideoOption:
        codecs = []
        for codec in CODEC_NAMES:
            matching = [entry for entry in entries if entry.codec == codec]
            if matching:
                codecs.append(CodecOption(codec, _plus(_likely(matching).size_bytes, audio_size)))
        if not entries:
            return VideoOption(quality)
        likely = _likely(entries)
        return VideoOption(quality, _plus(likely.size_bytes, audio_size), likely.codec, tuple(codecs))

    videos = [option(None, list(formats.videos))]
    videos += [option(step, by_step[step]) for step in QUALITY_STEPS if step in by_step]
    mp3 = tuple(
        AudioOption("mp3", bitrate, int(formats.duration * bitrate * 1000 / 8) if formats.duration else None)
        for bitrate in MP3_BITRATES
    )
    return QuickOptions(
        format_choices=True, containers=("mp4", "mkv"), videos=tuple(videos),
        audio=(AudioOption("m4a", size_bytes=audio_size), *mp3), duration=formats.duration,
    )


@dataclass(frozen=True)
class ChoiceEstimate:
    size_bytes: int | None
    codecs: tuple[str, ...]
    """The codecs offered at the chosen quality."""


def estimate_choice(options: QuickOptions, choice: QuickChoice) -> ChoiceEstimate:
    """How big a choice would be, from the option list, for the rules checked before it starts."""
    if choice.kind == "audio":
        wanted = ("mp3", choice.mp3_bitrate) if choice.audio_format == "mp3" else ("m4a", None)
        audio = next((a for a in options.audio if (a.audio_format, a.bitrate) == wanted), None)
        return ChoiceEstimate(audio.size_bytes if audio else None, ())
    row = next((v for v in options.videos if v.quality == choice.quality), None)
    if row is None:
        return ChoiceEstimate(None, ())
    codecs = tuple(c.codec for c in row.codecs)
    if choice.codec is None:
        return ChoiceEstimate(row.size_bytes, codecs)
    match = next((c for c in row.codecs if c.codec == choice.codec), None)
    return ChoiceEstimate(match.size_bytes if match else None, codecs)


def ready_manifest(request: QuickDownloadRequest, path: Path, size_bytes: int, *, now: datetime | None = None) -> QuickManifest:
    """What the folder holds once the file is ready, and how long it waits for someone to fetch it."""
    now = now or datetime.now(timezone.utc)
    source = get_source(request.source_key)
    return QuickManifest(
        id=request.id, title=request.title, file_name=path.name, size_bytes=size_bytes,
        format=request.choice.label, created_at=now,
        expires_at=now + timedelta(hours=get_settings().quick_download.keep_unclaimed_hours),
        details={"source_key": source.id, "source_name": source.name, "url": request.url, "kind": request.choice.kind},
    )


def quick_folder(quick_id: str) -> Path:
    return quick_folder_path(get_settings().download_settings.temporary_download_root, quick_id)


def ready_quick_download(quick_id: str) -> QuickFolder | None:
    """A quick download whose file is ready, or None."""
    found = open_quick_folder(get_settings().download_settings.temporary_download_root, quick_id)
    return found if found is not None and found.manifest is not None else None


def discard_quick_download(quick_id: str) -> bool:
    found = open_quick_folder(get_settings().download_settings.temporary_download_root, quick_id)
    if found is None:
        return False
    if found.manifest is not None and found.manifest.state == "ready":
        quick_download_history.record_outcome(quick_id, quick_download_history.DISCARDED, only_from=(quick_download_history.READY,))
    deliveries.forget(quick_id)
    return remove_quick_folder(found.path)


class QuickDeliveries:
    """Which bytes of each ready file have been sent, across requests and resumed ranges.

    Browsers resume with range requests and some ask for the first bytes twice,
    so a file counts as delivered once the sent ranges cover all of it, not when
    one request ends. This lives in memory: after a restart a file that was half
    sent simply waits for its next download.
    """

    def __init__(self) -> None:
        self._sent: dict[str, list[tuple[int, int]]] = {}
        self._lock = threading.Lock()

    def sent(self, quick_id: str, start: int, end: int, size: int) -> bool:
        """Record that ``[start, end)`` went out; True the first time the whole file has."""
        if end <= start:
            return False
        with self._lock:
            ranges = sorted([*self._sent.get(quick_id, []), (start, end)])
            merged: list[tuple[int, int]] = []
            for low, high in ranges:
                if merged and low <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], high))
                else:
                    merged.append((low, high))
            self._sent[quick_id] = merged
            complete = merged[0][0] <= 0 and merged[0][1] >= size
            if complete:
                self._sent.pop(quick_id, None)
            return complete

    def forget(self, quick_id: str) -> None:
        with self._lock:
            self._sent.pop(quick_id, None)


deliveries = QuickDeliveries()


def mark_delivered(quick_id: str, *, now: datetime | None = None) -> QuickManifest | None:
    """Every byte has been sent: delete the file after the grace period, or now when it is 0."""
    found = ready_quick_download(quick_id)
    if found is None or found.manifest is None:
        return None
    now = now or datetime.now(timezone.utc)
    keep_for = timedelta(minutes=get_settings().quick_download.keep_downloaded_minutes)
    manifest = found.manifest.delivered(now, keep_for=keep_for)
    if found.manifest.state != "delivered":
        quick_download_history.record_outcome(quick_id, quick_download_history.DOWNLOADED, only_from=(quick_download_history.READY,))
    if manifest.expired(now):
        remove_quick_folder(found.path)
    elif manifest != found.manifest:
        write_manifest(found.path, manifest)
    return manifest


def sweep_quick_downloads(
    temporary_root: str | Path | None = None, *, remove_unfinished: bool = False, now: datetime | None = None,
) -> QuickSweep:
    """Delete quick download files whose time is up.

    Startup recovery also removes folders that never became ready, because no
    quick download can still be running then.
    """
    sweep = sweep_quick_folders(
        temporary_root or get_settings().download_settings.temporary_download_root,
        now=now or datetime.now(timezone.utc), remove_unfinished=remove_unfinished,
    )
    for manifest in sweep.expired:
        if manifest.state == "ready":
            quick_download_history.record_outcome(
                manifest.id, quick_download_history.EXPIRED, only_from=(quick_download_history.READY,),
            )
    return sweep


def run_scheduled_quick_download_sweep() -> None:
    """The once-a-minute housekeeping job; it must never take the scheduler down."""
    try:
        sweep_quick_downloads()
        quick_download_history.forget_old_history()
    except Exception:
        logger.exception("Could not sweep expired quick downloads")
