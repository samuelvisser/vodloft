"""Downloads that yt-dlp performs from a web page.

The caller supplies the yt-dlp command (program and options); this module adds
the format selection, runs it into a private directory and reports progress.
"""
from __future__ import annotations

import json
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .hls_bundle import BundleTrack, write_hls_bundle
from .errors import DownloadCanceled, DownloadError, EncryptedMediaError, FileTooLargeError, MediaUnavailableError
from .models import CancelCheck, DownloadProgress, DownloadResult, ProgressCallback, SponsorSegment, VideoStream, WrittenSubtitle
from .plan import ResolvedDownloadSource, YtdlpSponsorBlock, YtdlpSubtitles
from .source import FORMAT_HEIGHTS
from .subtitles import srt_to_webvtt, webvtt_to_srt

logger = logging.getLogger(__name__)

_PROGRESS = "[vodloft-progress]"
_FILE = "[vodloft-file]"
_SPONSORBLOCK = "[vodloft-sponsorblock]"
_VIDEO = "[vodloft-video]"
_TRACK = "[vodloft-track]"
_MARKS = (_FILE, _SPONSORBLOCK, _VIDEO, _TRACK)
_CODECS = (("avc", "h264"), ("h264", "h264"), ("hev", "h265"), ("hvc", "h265"), ("h265", "h265"), ("vp09", "vp9"), ("vp9", "vp9"), ("av01", "av1"), ("av1", "av1"))
_SUBTITLE_FORMAT = ("--sub-format", "srt/vtt/best")
# An HLS bundle keeps its subtitles as WebVTT, so it takes a site's own WebVTT first.
_BUNDLE_SUBTITLE_FORMAT = ("--sub-format", "vtt/srt/best")
# Every language, never YouTube's live chat.
_EVERY_LANGUAGE = "all,-live_chat"
# media.<language>.<format> from the download; auto.<language>.<format> from
# the second pass that fetches auto-generated subtitles on their own.
_SUBTITLE_FILE = re.compile(r"^(?P<stem>media|auto)\.(?P<language>[A-Za-z0-9][A-Za-z0-9_-]{0,34})\.(?P<format>srt|vtt)$")
_MAX_SUBTITLE_BYTES = 32 * 1024 * 1024
_UNAVAILABLE_MARKERS = ("video unavailable", "private video", "has been removed", "not available", "http error 404")

VIDEO_CODECS = ("av1", "vp9", "h264", "h265")
# How yt-dlp names each codec in a format sort, and a filter matching it.
_SORT_NAMES = {"av1": "av01", "vp9": "vp9", "h264": "h264", "h265": "h265"}
_CODEC_PATTERNS = {"av1": "av0?1", "vp9": "vp0?9", "h264": "avc|h264", "h265": "hev|hvc|h265"}
_AUDIO_SORT_NAMES = {"aac": "aac", "opus": "opus"}
AUDIO_FORMATS = ("m4a", "opus", "mp3")


@dataclass(frozen=True)
class YtdlpQuality:
    """A Local Media Profile's quality choices, for a site yt-dlp downloads from.

    The default takes the highest resolution in any codec, preferring H.264,
    as MP4 with AAC.
    """
    video_codecs: tuple[str, ...] = ("h264", "vp9", "av1", "h265")
    """The codecs that may be used, most wanted first."""
    strict: bool = False
    """Skip a video that has none of ``video_codecs`` instead of taking the best version there is."""
    container: str = "mp4"
    audio_codec: str = "aac"
    audio_format: str = "m4a"
    """The file format of an audio only download."""
    audio_language: str | None = None
    """A dubbed audio track's language; None keeps the language the video was made in."""
    prefer_small: bool = False
    """Of two versions at the same resolution and codec, take the smaller one."""

    def __post_init__(self) -> None:
        if not self.video_codecs or any(codec not in VIDEO_CODECS for codec in self.video_codecs):
            raise DownloadError(f"Unsupported video codecs {self.video_codecs!r}")
        if len(set(self.video_codecs)) != len(self.video_codecs):
            raise DownloadError("Each video codec can be chosen once")
        if self.container not in ("mp4", "mkv"):
            raise DownloadError(f"Unsupported video container '{self.container}'")
        if self.audio_codec not in _AUDIO_SORT_NAMES:
            raise DownloadError(f"Unsupported audio codec '{self.audio_codec}'")
        if self.audio_format not in AUDIO_FORMATS:
            raise DownloadError(f"Unsupported audio format '{self.audio_format}'")
        if self.audio_language is not None and not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", self.audio_language):
            raise DownloadError(f"Unsupported audio language '{self.audio_language}'")


def _with_language(selector: str, language: str | None) -> list[str]:
    """``selector`` in the audio language first, then in any language."""
    if language is None:
        return [selector]
    return [f"{selector}[language^={language}]", selector]


def ytdlp_format_options(
    preferred_format: str, *, audio_only: bool, quality: YtdlpQuality = YtdlpQuality(),
) -> tuple[str, ...]:
    """yt-dlp options for a Local Media Profile's resolution and quality choices.

    The resolution is a ceiling: yt-dlp takes the highest resolution up to it,
    or the lowest there is when none fits. Only the allowed codecs are taken,
    unless the profile takes the best version there is when none of them exists.
    """
    language = quality.audio_language
    if audio_only:
        preferred = {"m4a": "ba[ext=m4a]", "opus": "ba[acodec=opus]", "mp3": "ba"}[quality.audio_format]
        choices = [*_with_language(preferred, language), *_with_language("ba", language), "b"]
        return ("-f", "/".join(dict.fromkeys(choices)), "-x", "--audio-format", quality.audio_format)
    height = FORMAT_HEIGHTS.get(preferred_format)
    if height is None:
        raise DownloadError(f"Unsupported preferred format '{preferred_format}'")
    allowed = f"[vcodec~='^({'|'.join(_CODEC_PATTERNS[codec] for codec in quality.video_codecs)})']"
    choices = [f"bv*{allowed}+{audio}" for audio in _with_language("ba", language)] + [f"b{allowed}"]
    if not quality.strict:
        choices += [f"bv*+{audio}" for audio in _with_language("ba", language)] + ["b"]
    # The resolution comes first, so a higher resolution in a less wanted codec
    # beats a lower one in the first codec. The sort can only name the first
    # codec; the filter above keeps the others to the allowed ones.
    sort = [f"res:{height}", f"vcodec:{_SORT_NAMES[quality.video_codecs[0]]}", f"acodec:{_AUDIO_SORT_NAMES[quality.audio_codec]}"]
    if quality.prefer_small:
        sort += ["+size", "+br"]
    return (
        "-f", "/".join(choices), "-S", ",".join(sort),
        "--merge-output-format", quality.container, "--remux-video", quality.container,
    )


HLS_HEIGHTS = (360, 720, 1080)
"""The resolutions of an HLS download. Podcast apps can play H.264, which sites such as YouTube
only have up to 1080p."""


def ytdlp_hls_options(language: str | None) -> tuple[str, ...]:
    """yt-dlp options that download the H.264 video of each of ``HLS_HEIGHTS``, up to that height,
    and the M4A audio as separate files, just as the site has them."""
    videos = [f"bv[height<={height}][vcodec^=avc1][ext=mp4]" for height in HLS_HEIGHTS]
    audio = "/".join(dict.fromkeys([*_with_language("ba[ext=m4a]", language)]))
    # The files stay as they are: yt-dlp would otherwise rewrite the audio as a plain M4A.
    return ("-f", ",".join((*videos, audio)), "--fixup", "never")


def ytdlp_sponsorblock_options(sponsorblock: YtdlpSponsorBlock) -> tuple[str, ...]:
    """yt-dlp options that mark SponsorBlock segments as chapters and cut others out."""
    if not sponsorblock.enabled:
        return ()
    options: tuple[str, ...] = ()
    if sponsorblock.chapter:
        options += ("--sponsorblock-mark", ",".join(sponsorblock.chapter))
    if sponsorblock.cut:
        options += ("--sponsorblock-remove", ",".join(sponsorblock.cut))
    return options


def resolve_ytdlp_source(
    url: str,
    *,
    command: tuple[str, ...],
    preferred_format: str,
    audio_only: bool,
    quality: YtdlpQuality = YtdlpQuality(),
    subtitles: YtdlpSubtitles = YtdlpSubtitles(),
    sponsorblock: YtdlpSponsorBlock = YtdlpSponsorBlock(),
    custom_options: tuple[str, ...] = (),
    ffmpeg_path: str = "ffmpeg",
) -> ResolvedDownloadSource:
    """``custom_options`` are the user's own yt-dlp options; VODLoft's own come after them and win."""
    if not command:
        raise DownloadError("A yt-dlp download needs the yt-dlp command")
    hls = preferred_format == "format_hls"
    if hls and audio_only:
        raise DownloadError("HLS media format cannot be used for an audio-only download")
    if hls:
        # Parts cut from separate video and audio files would no longer line up, so an HLS bundle only marks them.
        sponsorblock = YtdlpSponsorBlock(chapter=(*sponsorblock.chapter, *sponsorblock.cut))
    options = (
        *custom_options,
        *(ytdlp_hls_options(quality.audio_language) if hls else ytdlp_format_options(preferred_format, audio_only=audio_only, quality=quality)),
        *ytdlp_sponsorblock_options(sponsorblock),
    )
    if os.sep in ffmpeg_path:
        options += ("--ffmpeg-location", ffmpeg_path)
    height = FORMAT_HEIGHTS.get(preferred_format)
    return ResolvedDownloadSource(
        url=url,
        format_downloaded="HLS " + "/".join(f"{height}p" for height in HLS_HEIGHTS) if hls
        else f"audio {quality.audio_format}" if audio_only else f"up to {height}p",
        use_hls=False,
        remux_to_mp4=False,
        extension="m3u8" if hls else quality.audio_format if audio_only else quality.container,
        audio_only=audio_only,
        hls_bundle=hls,
        ytdlp_command=(*command, *options),
        ytdlp_subtitles=subtitles,
        ytdlp_sponsorblock=sponsorblock,
    )


def _language_patterns(subtitles: YtdlpSubtitles) -> str:
    """yt-dlp's --sub-langs: each listed language with its regional variants, such as en and en-US."""
    if not subtitles.languages:
        return _EVERY_LANGUAGE
    return ",".join(f"{re.escape(language)}(-[A-Za-z0-9]+)*" for language in subtitles.languages)


def ytdlp_subtitle_options(subtitles: YtdlpSubtitles, *, webvtt: bool = False) -> tuple[str, ...]:
    """Options for the subtitles written during the download.

    With both real and auto-generated subtitles asked for, yt-dlp uses the
    real one of a language when there is one, so ``fallback`` is just that.
    --ignore-errors turns a subtitle that fails to download into a warning;
    any other error still ends yt-dlp with a non-zero exit status. With
    ``webvtt``, for an HLS bundle, a site's WebVTT is taken before its SRT.
    """
    auto = ("--write-auto-subs",) if subtitles.auto_generated == "fallback" else ()
    subtitle_format = _BUNDLE_SUBTITLE_FORMAT if webvtt else _SUBTITLE_FORMAT
    return ("--write-subs", *auto, "--sub-langs", _language_patterns(subtitles), *subtitle_format, "--ignore-errors")


QUICK_VIDEO_CODECS = ("h264", "h265", "vp9", "av1")
QUICK_AUDIO_FORMATS = ("m4a", "mp3")
_CODEC_FILTERS = {
    "h264": "vcodec~='^(avc|h264)'",
    "h265": "vcodec~='^(hev|hvc|h265)'",
    "vp9": "vcodec~='^(vp0?9)'",
    "av1": "vcodec~='^(av01|av1)'",
}


def ytdlp_quick_options(
    *,
    audio_only: bool,
    container: str = "mp4",
    height: int | None = None,
    codec: str | None = None,
    audio_format: str = "m4a",
    audio_bitrate: int | None = None,
    strict_codec: bool = False,
    max_bytes: int | None = None,
) -> tuple[str, ...]:
    """yt-dlp options for a quick download.

    With no height and no codec this is yt-dlp's own default selection, with
    no preferences of VODLoft's. A height or codec only steers yt-dlp's sort,
    so a video without that exact stream still downloads in the nearest one,
    unless ``strict_codec`` takes only streams in the codec. ``max_bytes``
    makes yt-dlp stop a file that turns out larger.
    """
    limit = ("--max-filesize", str(max_bytes)) if max_bytes else ()
    if audio_only:
        if audio_format == "m4a":
            return ("-f", "bestaudio[ext=m4a]/bestaudio/best", "-x", "--audio-format", "m4a", *limit)
        if audio_format != "mp3":
            raise DownloadError(f"Unsupported audio format '{audio_format}'")
        options: tuple[str, ...] = ("-f", "bestaudio/best", "-x", "--audio-format", "mp3")
        quality = ("--audio-quality", f"{audio_bitrate}K") if audio_bitrate else ()
        return (*options, *quality, *limit)
    if container not in ("mp4", "mkv"):
        raise DownloadError(f"Unsupported video container '{container}'")
    if codec is not None and codec not in QUICK_VIDEO_CODECS:
        raise DownloadError(f"Unsupported video codec '{codec}'")
    if strict_codec and codec is None:
        raise DownloadError("A strict codec needs a codec")
    sort = [part for part in (f"res:{height}" if height else None, f"vcodec:{codec}" if codec else None) if part]
    options = ("-S", ",".join(sort)) if sort else ()
    if strict_codec:
        only = _CODEC_FILTERS[codec]
        options = ("-f", f"bv*[{only}]+ba/b[{only}]", *options)
    return (*options, "--merge-output-format", container, "--remux-video", container, *limit)


def resolve_ytdlp_quick_source(
    url: str,
    *,
    command: tuple[str, ...],
    audio_only: bool,
    container: str = "mp4",
    height: int | None = None,
    codec: str | None = None,
    audio_format: str = "m4a",
    audio_bitrate: int | None = None,
    strict_codec: bool = False,
    max_bytes: int | None = None,
    ffmpeg_path: str = "ffmpeg",
) -> ResolvedDownloadSource:
    """A quick download in the format chosen for it; see ``ytdlp_quick_options``."""
    if not command:
        raise DownloadError("A yt-dlp download needs the yt-dlp command")
    options = ytdlp_quick_options(
        audio_only=audio_only, container=container, height=height, codec=codec,
        audio_format=audio_format, audio_bitrate=audio_bitrate, strict_codec=strict_codec, max_bytes=max_bytes,
    )
    if os.sep in ffmpeg_path:
        options += ("--ffmpeg-location", ffmpeg_path)
    if audio_only:
        downloaded = f"audio {audio_format}" + (f" {audio_bitrate} kbps" if audio_format == "mp3" and audio_bitrate else "")
    else:
        downloaded = f"up to {height}p" if height else "best"
    return ResolvedDownloadSource(
        url=url,
        format_downloaded=downloaded,
        use_hls=False,
        remux_to_mp4=False,
        extension=audio_format if audio_only else container,
        audio_only=audio_only,
        ytdlp_command=(*command, *options),
    )


def error_message(output: str | list[str]) -> str:
    """yt-dlp's last ERROR line, without the prefix, or its last line."""
    lines = [line.strip() for line in (output.splitlines() if isinstance(output, str) else output) if line.strip()]
    errors = [line.removeprefix("ERROR:").strip() for line in lines if line.startswith("ERROR:")]
    if errors:
        return errors[-1]
    return lines[-1] if lines else "yt-dlp failed without a message"


def is_drm_message(message: str) -> bool:
    """yt-dlp refused the media because it is protected by DRM."""
    return "drm" in message.lower()


def is_unsupported_url_message(message: str) -> bool:
    """No yt-dlp extractor recognises the link."""
    return "unsupported url" in message.lower()


def _error(output: list[str]) -> DownloadError:
    message = error_message(output)
    if "requested format is not available" in message.lower():
        # Only a profile that skips videos without an allowed codec asks for a format that may not exist.
        return DownloadError("This video has none of the allowed video codecs, so it was skipped")
    if is_drm_message(message):
        return EncryptedMediaError(f"This video is protected by DRM and cannot be downloaded ({message})")
    if any(marker in message.lower() for marker in _UNAVAILABLE_MARKERS):
        return MediaUnavailableError(message)
    return DownloadError(f"yt-dlp: {message}")


def _number(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None


def _base_language(language: str) -> str:
    return language.split("-", 1)[0].lower()


def _choose_subtitles(found: dict[str, Path], subtitles: YtdlpSubtitles) -> list[tuple[str, Path]]:
    """The subtitles to keep from what yt-dlp wrote, by language, in order of preference."""
    if not subtitles.languages:
        return list(found.items())
    chosen = []
    for wanted in subtitles.languages:
        # The language itself beats a regional variant: en before en-US.
        matches = sorted(
            (language for language in found if _base_language(language) == _base_language(wanted) or language.lower() == wanted.lower()),
            key=lambda language: (language.lower() != wanted.lower(), language),
        )
        if matches:
            chosen.append((wanted, found[matches[0]]))
            if subtitles.first_only:
                break
    return chosen


def _readable_subtitles(work: Path, stem: str, *, webvtt: bool) -> dict[str, tuple[Path, bytes, bytes | None]]:
    """Each subtitle yt-dlp wrote under ``stem``, as SRT and, with ``webvtt``, as WebVTT: the site's
    own when it gave WebVTT. One that can't be read is left out."""
    readable: dict[str, tuple[Path, bytes, bytes | None]] = {}
    for path in sorted(work.iterdir()):
        match = _SUBTITLE_FILE.match(path.name)
        if match is None or match.group("stem") != stem:
            continue
        language = match.group("language")
        if language in readable:
            continue
        try:
            if path.stat().st_size > _MAX_SUBTITLE_BYTES:
                raise DownloadError("The subtitle is larger than allowed")
            text = path.read_bytes().decode("utf-8-sig")
            is_webvtt = match.group("format") == "vtt"
            content = webvtt_to_srt(text) if is_webvtt else text.replace("\r\n", "\n").encode("utf-8")
            if not content.strip():
                raise DownloadError("The subtitle is empty")
            vtt = None
            if webvtt:
                vtt = text.encode("utf-8") if is_webvtt else srt_to_webvtt(text)
        except (DownloadError, OSError, UnicodeDecodeError) as exc:
            logger.info("Leaving out the %s subtitle yt-dlp wrote: %s", language, exc)
            continue
        readable[language] = (path, content, vtt)
    return readable


def _keep_subtitles(work: Path, target: Path, subtitles: YtdlpSubtitles, *, webvtt: bool = False) -> tuple[WrittenSubtitle, ...]:
    """The subtitles the profile wants from what yt-dlp wrote, as SRT files in ``target``, and with
    ``webvtt`` as WebVTT files beside them."""
    kept: list[WrittenSubtitle] = []
    for stem, auto_generated in (("media", False), ("auto", True)):
        readable = _readable_subtitles(work, stem, webvtt=webvtt)
        found = {language: path for language, (path, _content, _vtt) in readable.items()}
        contents = {path: (content, vtt) for path, content, vtt in readable.values()}
        for language, path in _choose_subtitles(found, subtitles):
            content, vtt = contents[path]
            name = f"ytdlp-subtitle.{language}{'.auto' if auto_generated else ''}"
            destination = target / f"{name}.srt"
            destination.write_bytes(content)
            vtt_destination = None
            if vtt is not None:
                vtt_destination = target / f"{name}.vtt"
                vtt_destination.write_bytes(vtt)
            kept.append(WrittenSubtitle(language, str(destination), auto_generated, str(vtt_destination) if vtt_destination else None))
    return tuple(kept)


def _write_auto_generated(
        url: str, work: Path, command: tuple[str, ...], subtitles: YtdlpSubtitles, *, webvtt: bool = False,
) -> None:
    """Fetch auto-generated subtitles on their own, next to the real ones the download wrote.

    yt-dlp gives one subtitle per language, preferring the real one, so the
    auto-generated tracks of ``always`` need a run of their own. It downloads
    no media, and its failure only leaves those tracks out.
    """
    argv = [
        *command, "--no-playlist", "--skip-download", "--ignore-no-formats-error",
        "-P", str(work), "-o", "auto.%(ext)s",
        "--write-auto-subs", "--sub-langs", _language_patterns(subtitles),
        *(_BUNDLE_SUBTITLE_FORMAT if webvtt else _SUBTITLE_FORMAT), "--ignore-errors",
        "--", url,
    ]
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("Could not fetch the auto-generated subtitles of %s: %s", url, exc)
        return
    if result.returncode != 0:
        logger.info("Could not fetch the auto-generated subtitles of %s: %s", url, error_message(result.stdout))


def video_codec_name(vcodec: str) -> str:
    """A codec as VODLoft names it, from yt-dlp's ``vcodec`` such as ``avc1.640028``."""
    lowered = vcodec.lower()
    for prefix, name in _CODECS:
        if lowered.startswith(prefix):
            return name
    return lowered.split(".", 1)[0]


def _video_stream(text: str) -> VideoStream | None:
    """The kept video stream from yt-dlp's ``width height vcodec`` line."""
    width, height, vcodec = (text.split() + ["NA"] * 3)[:3]
    sides = [side for side in (_number(width), _number(height)) if side]
    if not sides or vcodec in {"NA", "none"}:
        return None
    return VideoStream(min(sides), video_codec_name(vcodec))


def _sponsor_segments(text: str, sponsorblock: YtdlpSponsorBlock) -> tuple[SponsorSegment, ...]:
    """The segments yt-dlp printed, with what the download did to each."""
    try:
        found = json.loads(text)
    except ValueError:
        return ()
    segments: list[SponsorSegment] = []
    for entry in found if isinstance(found, list) else ():
        if not isinstance(entry, dict):
            continue
        category, start, end = entry.get("category"), entry.get("start_time"), entry.get("end_time")
        if not isinstance(category, str) or not all(
            isinstance(value, (int, float)) and math.isfinite(value) for value in (start, end)
        ):
            continue
        action = "cut" if category in sponsorblock.cut else "chapter"
        segments.append(SponsorSegment(category, round(float(start), 3), round(float(end), 3), action))
    return tuple(sorted(segments, key=lambda segment: (segment.start, segment.end)))


def download_ytdlp(
        url: str,
        dest_path: str,
        *,
        command: tuple[str, ...],
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[CancelCheck] = None,
        subtitles_dir: Path | None = None,
        subtitles: YtdlpSubtitles = YtdlpSubtitles(),
        sponsorblock: YtdlpSponsorBlock = YtdlpSponsorBlock(),
) -> DownloadResult:
    """Run yt-dlp for ``url`` and move the file it produces to ``dest_path``.

    With ``subtitles_dir``, yt-dlp also writes the video's subtitles that
    ``subtitles`` asks for; each one is saved there as SRT and listed in the
    result. A subtitle that fails never fails the download.
    """
    if should_cancel and should_cancel():
        raise DownloadCanceled("Download canceled")
    work = Path(dest_path + ".ytdlp")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    argv = [
        *command,
        "--no-playlist", "--newline", "--progress", "--no-mtime",
        "--progress-template",
        f"download:{_PROGRESS} %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s",
        "--print", f"after_move:{_FILE} %(filepath)s",
        *(("--print", f"after_move:{_SPONSORBLOCK} %(sponsorblock_chapters)j") if sponsorblock.enabled else ()),
        "--print", f"after_move:{_VIDEO} %(width)s %(height)s %(vcodec)s",
        "-P", str(work), "-o", "media.%(ext)s",
        *(ytdlp_subtitle_options(subtitles) if subtitles_dir is not None else ()),
        "--", url,
    ]
    produced: str | None = None
    segments: tuple[SponsorSegment, ...] | None = None
    video: VideoStream | None = None
    try:
        output, marked = _run(argv, progress=progress, should_cancel=should_cancel)
        for line in marked:
            if line.startswith(_FILE):
                produced = line.removeprefix(_FILE).strip()
            elif line.startswith(_VIDEO):
                video = _video_stream(line.removeprefix(_VIDEO).strip())
            elif line.startswith(_SPONSORBLOCK):
                segments = _sponsor_segments(line.removeprefix(_SPONSORBLOCK).strip(), sponsorblock)
        if not produced or not Path(produced).is_file():
            # --max-filesize ends without a file and without an error.
            if any("larger than max-filesize" in line for line in output):
                raise FileTooLargeError("The file is larger than the largest file allowed")
            raise DownloadError("yt-dlp finished without producing a file")
        size = Path(produced).stat().st_size
        os.replace(produced, dest_path)
        written: tuple[WrittenSubtitle, ...] = ()
        if subtitles_dir is not None:
            if subtitles.auto_generated == "always" and not (should_cancel and should_cancel()):
                _write_auto_generated(url, work, command, subtitles)
            written = _keep_subtitles(work, subtitles_dir, subtitles)
        if progress:
            progress(DownloadProgress(bytes_downloaded=size, total_bytes=size))
        return DownloadResult(path=dest_path, bytes_downloaded=size, subtitles=written, sponsorblock=segments, video=video)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def download_ytdlp_hls_bundle(
        url: str,
        master_path: str,
        *,
        command: tuple[str, ...],
        ffmpeg_path: str = "ffmpeg",
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[CancelCheck] = None,
        subtitles_dir: Path | None = None,
        subtitles: YtdlpSubtitles = YtdlpSubtitles(),
        sponsorblock: YtdlpSponsorBlock = YtdlpSponsorBlock(),
) -> DownloadResult:
    """Run yt-dlp with ``ytdlp_hls_options`` and keep the files it downloads as an HLS bundle at
    ``master_path``, with a variant for each resolution the video has. Its subtitles are written as
    SRT and WebVTT, so they can go into the bundle too."""
    if should_cancel and should_cancel():
        raise DownloadCanceled("Download canceled")
    work = Path(master_path + ".ytdlp")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    argv = [
        *command,
        "--no-playlist", "--newline", "--progress", "--no-mtime",
        "--progress-template",
        f"download:{_PROGRESS} %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s",
        "--print", f"after_move:{_TRACK} %(format_id)s %(width)s %(height)s %(vcodec)s %(acodec)s %(tbr)s %(abr)s %(filepath)s",
        *(("--print", f"after_move:{_SPONSORBLOCK} %(sponsorblock_chapters)j") if sponsorblock.enabled else ()),
        "-P", str(work), "-o", "track-%(format_id)s.%(ext)s", "-o", "subtitle:media.%(ext)s",
        *(ytdlp_subtitle_options(subtitles, webvtt=True) if subtitles_dir is not None else ()),
        "--", url,
    ]
    try:
        _output, marked = _run(argv, progress=progress, should_cancel=should_cancel)
        tracks: dict[str, BundleTrack] = {}
        audio: BundleTrack | None = None
        segments: tuple[SponsorSegment, ...] | None = None
        for line in marked:
            if line.startswith(_SPONSORBLOCK):
                segments = _sponsor_segments(line.removeprefix(_SPONSORBLOCK).strip(), sponsorblock)
            if not line.startswith(_TRACK):
                continue
            format_id, width, height, vcodec, acodec, tbr, abr, path = (line.removeprefix(_TRACK).strip().split(" ", 7) + ["NA"] * 8)[:8]
            bitrate = _number(tbr) or _number(abr)
            if vcodec in ("NA", "none"):
                audio = BundleTrack(Path(path), codecs=None if acodec == "NA" else acodec, bitrate=bitrate * 1000 if bitrate else None)
            else:
                tracks[format_id] = BundleTrack(
                    Path(path), codecs=vcodec, bitrate=bitrate * 1000 if bitrate else None,
                    width=_number(width), height=_number(height),
                )
        # A video below 1080p gets the same file for more than one of the resolutions; keep it once.
        videos = list({track.height: track for track in tracks.values()}.values())
        if audio is None or not videos or not all(track.path.is_file() for track in (*videos, audio)):
            raise DownloadError("yt-dlp did not download both the video and the audio")
        write_hls_bundle(master_path, videos=videos, audio=audio, ffmpeg_path=ffmpeg_path, should_cancel=should_cancel)
        written: tuple[WrittenSubtitle, ...] = ()
        if subtitles_dir is not None:
            if subtitles.auto_generated == "always" and not (should_cancel and should_cancel()):
                _write_auto_generated(url, work, command, subtitles, webvtt=True)
            written = _keep_subtitles(work, subtitles_dir, subtitles, webvtt=True)
        size = sum(track.path.stat().st_size for track in (*videos, audio))
        if progress:
            progress(DownloadProgress(bytes_downloaded=size, total_bytes=size))
        return DownloadResult(path=master_path, bytes_downloaded=size, subtitles=written, sponsorblock=segments)
    finally:
        shutil.rmtree(work, ignore_errors=True)

def _run(
        argv: list[str], *, progress: Optional[ProgressCallback], should_cancel: Optional[CancelCheck],
) -> tuple[list[str], list[str]]:
    """Run yt-dlp, report its progress, and return its last lines of output and the lines VODLoft's
    own ``--print`` options wrote, in order. Raises for a failure or when canceled."""
    lines: queue.Queue[str | None] = queue.Queue()
    output: list[str] = []
    marked: list[str] = []
    finished = 0
    current = 0

    def read(stream) -> None:
        for line in stream:
            lines.put(line.rstrip("\n"))
        lines.put(None)

    try:
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        )
    except OSError as exc:
        raise DownloadError(f"Could not start yt-dlp: {exc}") from exc
    reader = threading.Thread(target=read, args=(process.stdout,), daemon=True)
    reader.start()
    try:
        while True:
            if should_cancel and should_cancel():
                raise DownloadCanceled("Download canceled")
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith(_PROGRESS):
                downloaded, total, estimate = (line.removeprefix(_PROGRESS).split() + ["NA"] * 3)[:3]
                value = _number(downloaded)
                if value is None:
                    continue
                if value < current:
                    # yt-dlp fetches video and audio one after the other.
                    finished += current
                current = value
                current_total = _number(total) or _number(estimate)
                if progress:
                    progress(DownloadProgress(
                        bytes_downloaded=finished + current,
                        total_bytes=finished + current_total if current_total else None,
                    ))
            elif line.startswith(_MARKS):
                marked.append(line)
            else:
                output.append(line)
                del output[:-50]
        if process.wait() != 0:
            raise _error(output)
        return output, marked
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
