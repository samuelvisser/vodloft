from __future__ import annotations

import math
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional, Sequence
from urllib.parse import urljoin, urlparse

from .ffmpeg import segment_as_hls
from .errors import DownloadCanceled, DownloadError, EncryptedMediaError, MediaUnavailableError
from .hls import is_master_playlist, is_playlist, parse_attribute_list, parse_master_playlist
from .http import http_get, http_get_text
from .models import CancelCheck, DownloadProgress, DownloadResult, ProgressCallback, VideoRendition


_TARGET_HEIGHTS = (480, 720, 1080)
_PROGRESS_INTERVAL_S = 1.0
_CHUNK_SIZE = 256 * 1024
_URI_ATTRIBUTE_RE = re.compile(r'URI="[^"]*"')
_HLS_BUNDLE_MARKER = ".vodloft-hls-bundle"
_SUBTITLE_GROUP = "subtitles"
# A variant's subtitles, captions and other video renditions are not downloaded, so a bundle's master
# must not name their groups: Apple's players refuse a playlist that names a group it does not define.
_GROUPS_NOT_KEPT_RE = re.compile(r',(?:SUBTITLES|CLOSED-CAPTIONS|VIDEO)="[^"]*"')


@dataclass(frozen=True)
class _PlaylistJob:
    source_url: str
    output_directory: Path
    text: str
    segment_count: int


def hls_asset_root(master_path: str | Path) -> Path:
    """Return the companion directory owned by a local HLS master playlist."""
    return Path(f"{Path(master_path)}.assets")


def hls_asset_marker(master_path: str | Path) -> Path:
    return hls_asset_root(master_path) / _HLS_BUNDLE_MARKER


def missing_hls_bundle_files(master_path: str | Path) -> list[Path]:
    """Return missing/unsafe files referenced by a VODLoft local HLS bundle."""
    root = hls_asset_root(master_path)
    missing: list[Path] = []

    if not hls_asset_marker(master_path).is_file():
        return [hls_asset_marker(master_path)]

    # Every playlist the master lists: The Daily Wire's resolutions, or the ones a video had.
    required_playlists = _listed_playlists(Path(master_path), root)
    if not required_playlists:
        return [Path(master_path)]
    for playlist in required_playlists:
        if not playlist.resolve().is_relative_to(root.resolve()) or not playlist.is_file():
            missing.append(playlist)

    for playlist in root.glob("*/playlist.m3u8"):
        if playlist.is_file():
            missing.extend(_missing_playlist_files(playlist, root=root))

    return missing


def _listed_playlists(master_path: Path, root: Path) -> list[Path]:
    """The asset playlists a bundle's master lists; none when it cannot be read or lists no video."""
    try:
        text = master_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    audio: list[str] = []
    video: list[str] = []
    after_variant = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            after_variant = True
        elif line.startswith("#EXT-X-MEDIA:"):
            uri = parse_attribute_list(line.split(":", 1)[1]).get("URI")
            if uri:
                audio.append(uri)
        elif line and not line.startswith("#") and after_variant:
            video.append(line)
            after_variant = False
    if not video:
        return []
    return [root / uri.removeprefix("hls/") for uri in (*audio, *video)]


def download_hls_bundle(
        master_url: str,
        master_path: str,
        *,
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[CancelCheck] = None,
) -> DownloadResult:
    """Store 480p, 720p and 1080p as a compact adaptive HLS bundle.

    Each rendition is stored as one byte-range-addressed media file instead of
    hundreds of loose segment files. The master and media playlists remain
    normal HLS and use paths served by VODLoft's stable RSS endpoint.
    """
    _ensure_not_canceled(should_cancel)
    master_text = http_get_text(master_url)
    if not is_playlist(master_text) or not is_master_playlist(master_text):
        raise DownloadError("HLS output requires a master playlist")

    renditions = parse_master_playlist(master_text, base_url=master_url)
    selected = _select_required_renditions(renditions)
    selected_urls = {rendition.url for rendition in selected.values()}

    asset_root = hls_asset_root(master_path)
    staging_asset_root = Path(f"{asset_root}.part")
    part_path = Path(f"{master_path}.part")
    try:
        _start_staging(master_path)

        master_lines, jobs = _build_master_and_jobs(
            master_text,
            master_url=master_url,
            selected_urls=selected_urls,
            selected=selected,
            asset_root=staging_asset_root,
        )
        segments_total = sum(job.segment_count for job in jobs)
        bytes_downloaded = 0
        segments_done = 0
        last_report = 0.0

        def report(*, force: bool = False) -> None:
            nonlocal last_report
            now = time.monotonic()
            if progress and (force or now - last_report >= _PROGRESS_INTERVAL_S):
                last_report = now
                progress(DownloadProgress(
                    bytes_downloaded=bytes_downloaded,
                    segments_done=segments_done,
                    segments_total=segments_total,
                ))

        def add_bytes(amount: int) -> None:
            nonlocal bytes_downloaded
            bytes_downloaded += amount
            report()

        def complete_segment() -> None:
            nonlocal segments_done
            segments_done += 1
            report()

        for job in jobs:
            _ensure_not_canceled(should_cancel)
            playlist_lines = _mirror_media_playlist(
                job,
                should_cancel=should_cancel,
                on_bytes=add_bytes,
                on_segment=complete_segment,
            )
            playlist_path = job.output_directory / "playlist.m3u8"
            playlist_path.write_text(
                "\n".join(playlist_lines).rstrip() + "\n",
                encoding="utf-8",
            )

        part_path.write_text(
            "\n".join(master_lines).rstrip() + "\n",
            encoding="utf-8",
        )
        _ensure_not_canceled(should_cancel)
        os.replace(staging_asset_root, asset_root)
        os.replace(part_path, master_path)
        report(force=True)
        return DownloadResult(
            path=str(master_path),
            bytes_downloaded=bytes_downloaded,
            segments_downloaded=segments_total,
        )
    except BaseException:
        _discard_staging(master_path)
        raise


def _start_staging(master_path: str | Path) -> None:
    """Make an empty staging directory for the bundle's assets, removing an earlier bundle of VODLoft's."""
    asset_root = hls_asset_root(master_path)
    staging_asset_root = Path(f"{asset_root}.part")
    shutil.rmtree(staging_asset_root, ignore_errors=True)
    if asset_root.exists():
        marker = asset_root / _HLS_BUNDLE_MARKER
        if marker.is_file():
            shutil.rmtree(asset_root)
        else:
            raise DownloadError(
                f"HLS asset destination already exists and is not owned by VODLoft: {asset_root}"
            )
    staging_asset_root.mkdir(parents=True, exist_ok=False)
    (staging_asset_root / _HLS_BUNDLE_MARKER).write_text(
        "VODLoft local HLS bundle\n",
        encoding="utf-8",
    )
    Path(master_path).parent.mkdir(parents=True, exist_ok=True)


def _discard_staging(master_path: str | Path) -> None:
    asset_root = hls_asset_root(master_path)
    try:
        Path(f"{master_path}.part").unlink(missing_ok=True)
    except OSError:
        pass
    shutil.rmtree(Path(f"{asset_root}.part"), ignore_errors=True)

    # Direct-mode downloads reserve the final master path as a zero-byte
    # placeholder. If publication failed after the asset directory moved,
    # remove that owned directory as part of the failed attempt.
    try:
        master_published = (
            Path(master_path).is_file()
            and Path(master_path).stat().st_size > 0
        )
    except OSError:
        master_published = False
    if not master_published and (asset_root / _HLS_BUNDLE_MARKER).is_file():
        shutil.rmtree(asset_root, ignore_errors=True)


@dataclass(frozen=True)
class BundleTrack:
    """A downloaded file with one video or audio track, to be kept in an HLS bundle."""

    path: Path
    codecs: str | None = None
    """As HLS names them, such as ``avc1.640028`` or ``mp4a.40.2``."""
    bitrate: int | None = None
    """Bits per second, on average."""
    width: int | None = None
    height: int | None = None


def write_hls_bundle(
        master_path: str,
        *,
        videos: list[BundleTrack],
        audio: BundleTrack,
        ffmpeg_path: str = "ffmpeg",
        should_cancel: Optional[CancelCheck] = None,
) -> None:
    """Keep separate video tracks, one per resolution, and their audio as an HLS bundle.

    Each track is split into parts without encoding it again, as byte ranges of one file, just
    like the bundles made from a Site's own HLS stream.
    """
    if not videos:
        raise DownloadError("An HLS bundle needs video")
    asset_root = hls_asset_root(master_path)
    staging_asset_root = Path(f"{asset_root}.part")
    part_path = Path(f"{master_path}.part")
    try:
        _start_staging(master_path)
        directory = staging_asset_root / "audio-0"
        directory.mkdir()
        segment_as_hls(str(audio.path), directory, ffmpeg_path=ffmpeg_path, should_cancel=should_cancel)
        master = [
            "#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-INDEPENDENT-SEGMENTS",
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,'
            'URI="hls/audio-0/playlist.m3u8"',
        ]
        for video in sorted(videos, key=lambda track: track.height or 0):
            _ensure_not_canceled(should_cancel)
            directory = staging_asset_root / f"{video.height}p"
            directory.mkdir()
            segment_as_hls(str(video.path), directory, ffmpeg_path=ffmpeg_path, should_cancel=should_cancel)
            attributes = [f"BANDWIDTH={(video.bitrate or 0) + (audio.bitrate or 0) or 1}"]
            if video.codecs and audio.codecs:
                attributes.append(f'CODECS="{video.codecs},{audio.codecs}"')
            if video.width and video.height:
                attributes.append(f"RESOLUTION={video.width}x{video.height}")
            attributes.append('AUDIO="audio"')
            master += [f"#EXT-X-STREAM-INF:{','.join(attributes)}", f"hls/{video.height}p/playlist.m3u8"]
        part_path.write_text("\n".join(master) + "\n", encoding="utf-8")
        _ensure_not_canceled(should_cancel)
        os.replace(staging_asset_root, asset_root)
        os.replace(part_path, master_path)
    except BaseException:
        _discard_staging(master_path)
        raise


@dataclass(frozen=True)
class BundleSubtitle:
    """A WebVTT subtitle to keep in an HLS bundle."""

    path: Path
    language: str
    name: str
    """What players list it as; unique within the bundle."""
    default: bool = False
    forced: bool = False
    parts: Path | None = None
    """The source's own WebVTT parts and their playlist, kept as they are in place of ``path``."""


def add_hls_subtitles(master_path: str | Path, subtitles: list[BundleSubtitle]) -> None:
    """Keep each subtitle in the bundle as one WebVTT file with a playlist of its own, and list them
    in the master, so players offer them with the video.

    The bundle then needs these files, just like its video: a bundle that misses one is incomplete.
    """
    if not subtitles:
        return
    master = Path(master_path)
    root = hls_asset_root(master)
    text = master.read_text(encoding="utf-8")
    playlists = _listed_playlists(master, root)
    duration = _playlist_duration(playlists[-1]) if playlists else 0.0
    if duration <= 0:
        raise DownloadError("The HLS bundle has no length to give its subtitles")

    segment_seconds = _playlist_target_duration(playlists[-1])
    media_lines = []
    for index, subtitle in enumerate(subtitles):
        directory = root / f"subtitles-{index}"
        shutil.rmtree(directory, ignore_errors=True)
        if subtitle.parts is not None:
            shutil.copytree(subtitle.parts, directory)
        else:
            directory.mkdir()
            write_hls_subtitle_segments(
                subtitle.path.read_text(encoding="utf-8-sig"), directory, duration=duration, segment_seconds=segment_seconds,
            )
        name = subtitle.name.replace('"', "'")
        media_lines.append(
            f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="{_SUBTITLE_GROUP}",NAME="{name}",LANGUAGE="{subtitle.language}",'
            f'DEFAULT={"YES" if subtitle.default else "NO"},AUTOSELECT=YES,FORCED={"YES" if subtitle.forced else "NO"},'
            f'URI="hls/subtitles-{index}/playlist.m3u8"'
        )

    lines = text.splitlines()
    first_variant = next(index for index, line in enumerate(lines) if line.startswith("#EXT-X-STREAM-INF:"))
    lines = [
        *lines[:first_variant], *media_lines,
        *(f'{line},SUBTITLES="{_SUBTITLE_GROUP}"' if line.startswith("#EXT-X-STREAM-INF:") else line for line in lines[first_variant:]),
    ]
    part_path = Path(f"{master}.part")
    part_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(part_path, master)


def write_hls_subtitle_segments(webvtt: str, directory: Path, *, duration: float, segment_seconds: int) -> None:
    """Write a WebVTT subtitle as parts of ``segment_seconds`` each, numbered ``0.vtt``, ``1.vtt`` and so
    on, and the ``playlist.m3u8`` that lists them.

    Apple's players stopped playing a few minutes in when a bundle's subtitles were one part as long as
    the video, so they are split like the video is. Every part starts with the subtitle's own header,
    with its ``X-TIMESTAMP-MAP`` and styles, and holds each cue that shows during it: a cue that
    crosses from one part into the next is in both, as HLS asks.
    """
    header, cues = _split_webvtt(webvtt)
    count = max(1, math.ceil(duration / segment_seconds - 1e-6))
    parts = []
    for number in range(count):
        start = number * segment_seconds
        end = duration if number == count - 1 else start + segment_seconds
        shown = [text for cue_start, cue_end, text in cues if cue_start < end and cue_end > start]
        parts.append((end - start, ("\n\n".join((header, *shown)) + "\n").encode("utf-8")))
    write_hls_subtitle_parts(parts, directory)


def write_hls_subtitle_parts(parts: Sequence[tuple[float, bytes]], directory: Path) -> None:
    """Write WebVTT parts, each with its length in seconds, as ``0.vtt``, ``1.vtt`` and so on in
    ``directory``, and the ``playlist.m3u8`` that lists them."""
    playlist = [
        "#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{max(1, math.ceil(max(seconds for seconds, _ in parts) - 1e-6))}",
        "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    for number, (seconds, data) in enumerate(parts):
        (directory / f"{number}.vtt").write_bytes(data)
        playlist += [f"#EXTINF:{seconds:.3f},", f"{number}.vtt"]
    playlist.append("#EXT-X-ENDLIST")
    # Written last and replaced at once, so a player never gets a playlist that names a missing part.
    part_path = directory / "playlist.m3u8.part"
    part_path.write_text("\n".join(playlist) + "\n", encoding="utf-8")
    os.replace(part_path, directory / "playlist.m3u8")


_CUE_TIMING_RE = re.compile(r"^\s*((?:\d+:)?\d{2}:\d{2}\.\d{3})\s+-->\s+((?:\d+:)?\d{2}:\d{2}\.\d{3})")


def _split_webvtt(webvtt: str) -> tuple[str, list[tuple[float, float, str]]]:
    """A WebVTT file's header, with its styles and regions, and its cues with their start and end."""
    blocks = [block.strip("\n") for block in re.split(r"\n[ \t]*\n", webvtt.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n"))]
    blocks = [block for block in blocks if block.strip()]
    header = [blocks[0]] if blocks else ["WEBVTT"]
    cues = []
    for block in blocks[1:]:
        lines = block.split("\n")
        timing = next((_CUE_TIMING_RE.match(line) for line in lines[:2] if _CUE_TIMING_RE.match(line)), None)
        if timing is not None:
            cues.append((_webvtt_seconds(timing.group(1)), _webvtt_seconds(timing.group(2)), block))
        elif not cues and lines[0].startswith(("STYLE", "REGION")):
            header.append(block)
    return "\n\n".join(header), cues


def _webvtt_seconds(timestamp: str) -> float:
    parts = timestamp.split(":")
    hours = int(parts[0]) if len(parts) == 3 else 0
    return hours * 3600 + int(parts[-2]) * 60 + float(parts[-1])


def _playlist_target_duration(playlist: Path) -> int:
    for line in playlist.read_text(encoding="utf-8").splitlines():
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                return max(1, int(line.split(":", 1)[1]))
            except ValueError:
                break
    return 6


def _playlist_duration(playlist: Path) -> float:
    total = 0.0
    for line in playlist.read_text(encoding="utf-8").splitlines():
        if line.startswith("#EXTINF:"):
            try:
                total += float(line.split(":", 1)[1].split(",", 1)[0])
            except ValueError:
                continue
    return total


def _select_required_renditions(
        renditions: list[VideoRendition],
) -> dict[int, VideoRendition]:
    selected: dict[int, VideoRendition] = {}
    for height in _TARGET_HEIGHTS:
        matches = [item for item in renditions if item.height == height]
        if not matches:
            raise MediaUnavailableError(
                "HLS source does not provide all required adaptive renditions "
                "(480p, 720p and 1080p)"
            )
        selected[height] = max(
            matches,
            key=lambda item: item.bandwidth or 0,
        )
    return selected


def _build_master_and_jobs(
        master_text: str,
        *,
        master_url: str,
        selected_urls: set[str],
        selected: dict[int, VideoRendition],
        asset_root: Path,
) -> tuple[list[str], list[_PlaylistJob]]:
    lines = master_text.splitlines()
    selected_audio_groups: set[str] = set()
    selected_stream_lines: list[tuple[str, str, int]] = []

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("#EXT-X-STREAM-INF:"):
            index += 1
            continue
        attrs = parse_attribute_list(line.split(":", 1)[1])
        uri_index = index + 1
        while uri_index < len(lines) and (
            not lines[uri_index].strip()
            or lines[uri_index].lstrip().startswith("#")
        ):
            uri_index += 1
        if uri_index >= len(lines):
            break

        source_url = urljoin(master_url, lines[uri_index].strip())
        if source_url in selected_urls:
            height = next(
                height
                for height, rendition in selected.items()
                if rendition.url == source_url
            )
            selected_stream_lines.append((line, source_url, height))
            audio_group = attrs.get("AUDIO")
            if audio_group:
                selected_audio_groups.add(audio_group)
        index = uri_index + 1

    if len(selected_stream_lines) != len(_TARGET_HEIGHTS):
        raise DownloadError(
            "Could not map required HLS renditions back to the master playlist"
        )

    master_out = ["#EXTM3U"]
    jobs: list[_PlaylistJob] = []

    for raw in lines[1:]:
        line = raw.strip()
        if line.startswith(("#EXT-X-VERSION:", "#EXT-X-INDEPENDENT-SEGMENTS")):
            master_out.append(line)

    audio_index = 0
    for raw in lines:
        line = raw.strip()
        if not line.startswith("#EXT-X-MEDIA:"):
            continue
        attrs = parse_attribute_list(line.split(":", 1)[1])
        if attrs.get("TYPE") != "AUDIO":
            continue
        if attrs.get("GROUP-ID") not in selected_audio_groups:
            continue

        uri = attrs.get("URI")
        if not uri:
            master_out.append(line)
            continue

        public_uri = f"hls/audio-{audio_index}/playlist.m3u8"
        output_directory = asset_root / f"audio-{audio_index}"
        source_url = urljoin(master_url, uri)
        text = http_get_text(source_url)
        _validate_vod_media_playlist(text)
        master_out.append(
            _URI_ATTRIBUTE_RE.sub(
                f'URI="{public_uri}"',
                line,
                count=1,
            )
        )
        jobs.append(_PlaylistJob(
            source_url=source_url,
            output_directory=output_directory,
            text=text,
            segment_count=_count_media_segments(text),
        ))
        audio_index += 1

    for stream_line, source_url, height in sorted(
        selected_stream_lines,
        key=lambda item: item[2],
    ):
        public_uri = f"hls/{height}p/playlist.m3u8"
        text = http_get_text(source_url)
        _validate_vod_media_playlist(text)
        master_out.append(_GROUPS_NOT_KEPT_RE.sub("", stream_line))
        master_out.append(public_uri)
        jobs.append(_PlaylistJob(
            source_url=source_url,
            output_directory=asset_root / f"{height}p",
            text=text,
            segment_count=_count_media_segments(text),
        ))

    return master_out, jobs


def _validate_vod_media_playlist(text: str) -> None:
    if not is_playlist(text) or is_master_playlist(text):
        raise DownloadError("Expected an HLS media playlist")
    if "#EXT-X-ENDLIST" not in text:
        raise DownloadError(
            "Refusing to store a live/incomplete HLS playlist as a local download"
        )
    if "#EXT-X-BYTERANGE" in text or "BYTERANGE=" in text:
        raise DownloadError(
            "Source byte-range HLS playlists are not supported for local HLS downloads"
        )

    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("#EXT-X-KEY:"):
            continue
        attrs = parse_attribute_list(line.split(":", 1)[1])
        if attrs.get("METHOD", "NONE").upper() != "NONE":
            raise EncryptedMediaError(
                f"Encrypted HLS stream (METHOD={attrs.get('METHOD')}) is not supported"
            )


def _count_media_segments(text: str) -> int:
    expect_segment = False
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            expect_segment = True
            continue
        if expect_segment and line and not line.startswith("#"):
            count += 1
            expect_segment = False
    return count


def _mirror_media_playlist(
        job: _PlaylistJob,
        *,
        should_cancel: Optional[CancelCheck],
        on_bytes,
        on_segment,
) -> list[str]:
    job.output_directory.mkdir(parents=True, exist_ok=False)
    media_filename = _compact_media_filename(job.text)
    media_path = job.output_directory / media_filename
    output: list[str] = []
    expect_segment = False

    with media_path.open("xb") as media_file:
        for raw in job.text.splitlines():
            _ensure_not_canceled(should_cancel)
            line = raw.strip()

            if line.startswith("#EXT-X-MAP:"):
                attrs = parse_attribute_list(line.split(":", 1)[1])
                uri = attrs.get("URI")
                if not uri:
                    output.append(raw)
                    continue
                offset = media_file.tell()
                amount = _download_into(
                    urljoin(job.source_url, uri),
                    media_file,
                    should_cancel=should_cancel,
                )
                on_bytes(amount)
                rewritten = _URI_ATTRIBUTE_RE.sub(
                    f'URI="{media_filename}"',
                    raw,
                    count=1,
                )
                output.append(
                    f'{rewritten},BYTERANGE="{amount}@{offset}"'
                )
                continue

            if line.startswith("#EXTINF:"):
                expect_segment = True
                output.append(raw)
                continue

            if expect_segment and line and not line.startswith("#"):
                offset = media_file.tell()
                amount = _download_into(
                    urljoin(job.source_url, line),
                    media_file,
                    should_cancel=should_cancel,
                )
                on_bytes(amount)
                on_segment()
                output.append(f"#EXT-X-BYTERANGE:{amount}@{offset}")
                output.append(media_filename)
                expect_segment = False
                continue

            output.append(raw)

    return _ensure_byterange_playlist_version(output)


def _compact_media_filename(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXT-X-MAP:"):
            return "media.mp4"

    expect_segment = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            expect_segment = True
            continue
        if expect_segment and line and not line.startswith("#"):
            return f"media{_safe_suffix(line, default='.ts')}"

    raise DownloadError("HLS media playlist contains no segments")


def _ensure_byterange_playlist_version(lines: list[str]) -> list[str]:
    required_version = 6 if any(
        raw.strip().startswith("#EXT-X-MAP:")
        for raw in lines
    ) else 4
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line.startswith("#EXT-X-VERSION:"):
            continue
        try:
            version = int(line.split(":", 1)[1])
        except ValueError:
            version = required_version
        lines[index] = f"#EXT-X-VERSION:{max(version, required_version)}"
        return lines

    insert_at = 1 if lines and lines[0].strip() == "#EXTM3U" else 0
    lines.insert(insert_at, f"#EXT-X-VERSION:{required_version}")
    return lines


def _download_into(
        url: str,
        destination: BinaryIO,
        *,
        should_cancel: Optional[CancelCheck],
) -> int:
    written = 0
    with http_get(url) as response:
        for chunk in response.iter_chunks(_CHUNK_SIZE):
            _ensure_not_canceled(should_cancel)
            destination.write(chunk)
            written += len(chunk)
    return written


def _safe_suffix(url: str, *, default: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".ts", ".m4s", ".mp4", ".aac", ".m4a"}:
        if suffix == ".m4s":
            return ".mp4"
        return suffix
    return default


def _missing_playlist_files(playlist: Path, *, root: Path) -> list[Path]:
    try:
        text = playlist.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [playlist]

    missing: list[Path] = []
    saw_segment = False
    resolved_root = root.resolve()
    # A bundle's parts are byte ranges of one file, listed once for every part: look at each file once.
    uris: dict[str, None] = {}
    for raw in text.splitlines():
        line = raw.strip()
        uri: str | None = None
        if line.startswith("#EXT-X-MAP:"):
            uri = parse_attribute_list(line.split(":", 1)[1]).get("URI")
        elif line and not line.startswith("#"):
            uri = line
            saw_segment = True
        if uri:
            uris[uri] = None

    for uri in uris:
        candidate = (playlist.parent / uri).resolve()
        if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
            missing.append(candidate)

    if not saw_segment:
        missing.append(playlist)
    return missing


def _ensure_not_canceled(should_cancel: Optional[CancelCheck]) -> None:
    if should_cancel and should_cancel():
        raise DownloadCanceled("Download canceled")
