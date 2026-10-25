"""Downloads that yt-dlp performs from a web page.

The caller supplies the yt-dlp command (program and options); this module adds
the format selection, runs it into a private directory and reports progress.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from .errors import DownloadCancelled, DownloadError, EncryptedMediaError, MediaUnavailableError
from .models import CancelCheck, DownloadProgress, DownloadResult, ProgressCallback
from .plan import ResolvedDownloadSource
from .source import FORMAT_HEIGHTS

_PROGRESS = "[vodloft-progress]"
_FILE = "[vodloft-file]"
_UNAVAILABLE_MARKERS = ("video unavailable", "private video", "has been removed", "not available", "http error 404")


def ytdlp_format_options(preferred_format: str, *, audio_only: bool) -> tuple[str, ...]:
    """yt-dlp options for a Local Media Profile's format, always ending in MP4 or M4A."""
    if audio_only:
        return ("-f", "bestaudio[ext=m4a]/bestaudio/best", "-x", "--audio-format", "m4a")
    height = FORMAT_HEIGHTS.get(preferred_format)
    if height is None:
        raise DownloadError(f"Unsupported preferred format '{preferred_format}'")
    # Prefer the requested height and MP4-friendly codecs, but take whatever
    # exists over failing: a 720p-only video still downloads for a 1080p profile.
    return (
        "-f", "bv*+ba/b", "-S", f"res:{height},vcodec:h264,acodec:m4a",
        "--merge-output-format", "mp4", "--remux-video", "mp4",
    )


def resolve_ytdlp_source(
    url: str,
    *,
    command: tuple[str, ...],
    preferred_format: str,
    audio_only: bool,
    ffmpeg_path: str = "ffmpeg",
) -> ResolvedDownloadSource:
    if not command:
        raise DownloadError("A yt-dlp download needs the yt-dlp command")
    if preferred_format == "format_hls":
        raise DownloadError("yt-dlp downloads cannot be kept as an HLS bundle")
    options = ytdlp_format_options(preferred_format, audio_only=audio_only)
    if os.sep in ffmpeg_path:
        options += ("--ffmpeg-location", ffmpeg_path)
    height = FORMAT_HEIGHTS.get(preferred_format)
    return ResolvedDownloadSource(
        url=url,
        format_downloaded="audio" if audio_only else f"up to {height}p",
        use_hls=False,
        remux_to_mp4=False,
        extension="m4a" if audio_only else "mp4",
        audio_only=audio_only,
        ytdlp_command=(*command, *options),
    )


def _error(output: list[str]) -> DownloadError:
    errors = [line.removeprefix("ERROR:").strip() for line in output if line.startswith("ERROR:")]
    message = errors[-1] if errors else (output[-1] if output else "yt-dlp failed without a message")
    lowered = message.lower()
    if "drm" in lowered:
        return EncryptedMediaError(f"This video is protected by DRM and cannot be downloaded ({message})")
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return MediaUnavailableError(message)
    return DownloadError(f"yt-dlp: {message}")


def _number(value: str) -> int | None:
    try:
        return int(float(value))
    except ValueError:
        return None


def download_ytdlp(
        url: str,
        dest_path: str,
        *,
        command: tuple[str, ...],
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[CancelCheck] = None,
) -> DownloadResult:
    """Run yt-dlp for ``url`` and move the file it produces to ``dest_path``."""
    if should_cancel and should_cancel():
        raise DownloadCancelled("Download cancelled")
    work = Path(dest_path + ".ytdlp")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    argv = [
        *command,
        "--no-playlist", "--newline", "--progress", "--no-mtime",
        "--progress-template",
        f"download:{_PROGRESS} %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s",
        "--print", f"after_move:{_FILE} %(filepath)s",
        "-P", str(work), "-o", "media.%(ext)s",
        "--", url,
    ]
    lines: queue.Queue[str | None] = queue.Queue()
    output: list[str] = []
    produced: str | None = None
    finished = 0
    current = 0
    current_total: int | None = None

    def read(stream) -> None:
        for line in stream:
            lines.put(line.rstrip("\n"))
        lines.put(None)

    try:
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        )
    except OSError as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise DownloadError(f"Could not start yt-dlp: {exc}") from exc
    reader = threading.Thread(target=read, args=(process.stdout,), daemon=True)
    reader.start()
    try:
        while True:
            if should_cancel and should_cancel():
                raise DownloadCancelled("Download cancelled")
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
            elif line.startswith(_FILE):
                produced = line.removeprefix(_FILE).strip()
            else:
                output.append(line)
                del output[:-50]
        if process.wait() != 0:
            raise _error(output)
        if not produced or not Path(produced).is_file():
            raise DownloadError("yt-dlp finished without producing a file")
        size = Path(produced).stat().st_size
        os.replace(produced, dest_path)
        if progress:
            progress(DownloadProgress(bytes_downloaded=size, total_bytes=size))
        return DownloadResult(path=dest_path, bytes_downloaded=size)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        shutil.rmtree(work, ignore_errors=True)
