"""Acquisition helpers shared by Sources; never imported by the application."""

from pathlib import Path
import base64
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor
from source_contracts import DownloadResult, RepresentationPolicy
from source_contracts.progress import download_progress_hook


class UnsupportedRepresentation(ValueError):
    pass


_VIDEO = {"h264": "^(avc|h264)", "h265": "^(hev|hvc|h265)", "vp9": "^vp0?9", "av1": "^av0?1"}
_AUDIO = {"aac": "^(mp4a|aac)", "mp3": "^mp3", "opus": "^opus"}
_MEDIA = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".mov"}
_PROTOCOLS = {"http", "https", "m3u8", "m3u8_native", "http_dash_segments", "http_dash_segments_generator"}


def lease_expiry(url: str) -> str | None:
    """A signed URL's expiry is advisory; the Source still verifies renewal."""
    query = parse_qs(urlsplit(url).query)
    for name in ("expire", "expires", "exp"):
        value = query.get(name, [""])[0]
        if value.isdecimal() and len(value) <= 12:
            try:
                return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
            except (ValueError, OSError, OverflowError):
                pass
    token = query.get("token", [""])[0]
    if len(token) < 8192 and token.count(".") == 2:
        try:
            payload = token.split(".")[1]
            expiry = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("exp")
            if isinstance(expiry, (int, float)):
                return datetime.fromtimestamp(expiry, timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    return None


def options(preferred_format: str, policy: RepresentationPolicy) -> dict:
    audio_only = preferred_format == "format_audio_only"
    heights = {"format_720p": 720, "format_1080p": 1080, "format_4k": 2160}
    if not audio_only and preferred_format not in heights:
        raise UnsupportedRepresentation("This media format is unsupported")
    height_filter = f"[height<=?{heights[preferred_format]}]" if not audio_only else ""
    video_filter = f"[vcodec~='{_VIDEO[policy.video_codec]}']" if policy.video_codec != "source" else ""
    audio_filter = f"[acodec~='{_AUDIO[policy.audio_codec]}']" if not audio_only and policy.audio_codec != "source" else ""
    languages = list(policy.languages)
    if not languages or policy.language_fallback:
        languages.append("")
    selectors = []
    for language in languages:
        language_filter = f"[language={language}]" if language else ""
        audio = "bestaudio" + audio_filter + language_filter
        combined = "best" + height_filter + video_filter + audio_filter + language_filter
        selectors.append(audio + "/" + combined if audio_only else
                         "bestvideo*" + height_filter + video_filter + "+" + audio + "/" + combined)
    processors = []
    container = policy.container
    if audio_only:
        codec = {"m4a": "m4a", "opus": "opus", "mp3": "mp3"}.get(container,
            {"aac": "m4a", "opus": "opus"}.get(policy.audio_codec, "mp3"))
        processors.append({"key": "FFmpegExtractAudio", "preferredcodec": codec})
    elif container != "source" or policy.subtitles:
        container = "mkv" if container == "source" else container
        if container not in {"mp4", "mkv"}:
            raise UnsupportedRepresentation("The requested container cannot carry video")
        processors.append({"key": "FFmpegVideoRemuxer", "preferedformat": container})
    if policy.subtitles:
        processors.append({"key": "FFmpegEmbedSubtitle"})
    if policy.artwork:
        processors.extend([{"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
                           {"key": "EmbedThumbnail"}])
    if policy.embed_metadata or policy.chapters:
        processors.append({"key": "FFmpegMetadata", "add_metadata": policy.embed_metadata,
            "add_chapters": policy.chapters, "add_infojson": False})
    return {"format": "/".join(selectors), "postprocessors": processors,
        "merge_output_format": container if container in {"mp4", "mkv"} else None,
        "writesubtitles": bool(policy.subtitles), "writeautomaticsub": bool(policy.subtitles),
        "subtitleslangs": policy.subtitles, "subtitlesformat": "srt/vtt/best",
        "writethumbnail": policy.artwork, "hls_prefer_native": True}


class _EffectiveMetadata(PostProcessor):
    def __init__(self, downloader, values: dict):
        super().__init__(downloader)
        self.values = values

    def run(self, info):
        for key in ("title", "description", "series", "episode", "upload_date"):
            if key in self.values:
                info[key] = self.values[key]
        return [], info


def download(url: str, staging: str, preferred_format: str,
             representation: dict | None = None, metadata: dict | None = None,
             authentication: dict | None = None) -> DownloadResult:
    destination = Path(staging).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    policy = RepresentationPolicy.model_validate(representation or {})
    config = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "outtmpl": str(destination / "media.%(ext)s"), "restrictfilenames": True,
        "progress_hooks": [download_progress_hook()], **options(preferred_format, policy),
        "postprocessor_args": {"ffmpeg_i": ["-protocol_whitelist", "file,pipe,crypto,data"]},
        **(authentication or {})}
    try:
        with yt_dlp.YoutubeDL(config) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or info.get("_type") in {"playlist", "multi_video"}:
                raise UnsupportedRepresentation("Choose one playable media item")
            formats = info.get("requested_formats") or [info]
            if any(fmt.get("protocol") not in _PROTOCOLS for fmt in formats):
                # Native helpers only process local files. They never receive
                # an upstream URL that can bypass the public-network guard.
                raise UnsupportedRepresentation("This transport needs a different Source")
            ydl.add_post_processor(_EffectiveMetadata(ydl, metadata or {}), when="before_dl")
            ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as exc:
        if "Requested format is not available" in str(exc):
            raise UnsupportedRepresentation("The requested tracks or codec are unavailable") from exc
        raise
    files = [path for path in destination.iterdir() if path.is_file() and path.suffix.lower() in _MEDIA]
    if len(files) != 1:
        raise RuntimeError("Source did not produce one completed media file")
    return DownloadResult(filename=files[0].name, size=files[0].stat().st_size)
