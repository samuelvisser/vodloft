from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from yt_dlp import YoutubeDL

from .models import DownloadOptions, DownloadResult, ExtractedCollection, ExtractedVideo, StreamTarget

ProgressHook = Callable[[dict[str, Any]], None]


def _parse_upload_date(value: Any):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError:
        return None


def _thumbnail(info: Mapping[str, Any]) -> str | None:
    value = info.get("thumbnail")
    if isinstance(value, str):
        return value
    thumbnails = info.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, Mapping) and isinstance(item.get("url"), str):
                return item["url"]
    return None


def _canonical_url(info: Mapping[str, Any], fallback: str) -> str:
    for key in ("webpage_url", "original_url"):
        value = info.get(key)
        if isinstance(value, str) and value:
            return value
    value = info.get("url")
    if isinstance(value, str) and value:
        return value
    return fallback


class YtDlpClient:
    """The only VodLoft component that knows yt-dlp's Python API.

    Site/extractor behavior deliberately stays here. The backend receives normalized
    resources and never calls YouTube or another provider directly.
    """

    def __init__(self, common_options: Mapping[str, Any] | None = None):
        self._common_options = dict(common_options or {})

    def _options(self, **overrides: Any) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
        }
        options.update(self._common_options)
        options.update({key: value for key, value in overrides.items() if value is not None})
        return options

    @staticmethod
    def _sanitize(ydl: YoutubeDL, info: Any) -> dict[str, Any]:
        if info is None:
            raise ValueError("yt-dlp returned no metadata")
        sanitized = ydl.sanitize_info(info)
        if not isinstance(sanitized, dict):
            raise TypeError("yt-dlp returned an unsupported metadata shape")
        return sanitized

    @staticmethod
    def _video_from_info(info: Mapping[str, Any], fallback_url: str) -> ExtractedVideo:
        extractor = str(info.get("extractor_key") or info.get("extractor") or "unknown")
        extractor_id = str(info.get("id") or _canonical_url(info, fallback_url))
        title = str(info.get("title") or info.get("fulltitle") or extractor_id)
        return ExtractedVideo(
            extractor=extractor,
            extractor_id=extractor_id,
            webpage_url=_canonical_url(info, fallback_url),
            title=title,
            description=info.get("description"),
            uploader=info.get("uploader"),
            uploader_id=info.get("uploader_id"),
            channel=info.get("channel"),
            channel_id=info.get("channel_id"),
            duration=info.get("duration"),
            upload_date=_parse_upload_date(info.get("upload_date")),
            thumbnail_url=_thumbnail(info),
            raw=dict(info),
        )

    def extract_video(self, url: str) -> ExtractedVideo:
        with YoutubeDL(self._options(noplaylist=True)) as ydl:
            info = self._sanitize(ydl, ydl.extract_info(url, download=False))
        if info.get("entries"):
            raise ValueError("URL resolved to a collection; add it as a channel or playlist")
        return self._video_from_info(info, url)

    def extract_collection(self, url: str, *, flat: bool = True) -> ExtractedCollection:
        options = self._options(
            noplaylist=False,
            extract_flat="in_playlist" if flat else False,
            skip_download=True,
        )
        with YoutubeDL(options) as ydl:
            info = self._sanitize(ydl, ydl.extract_info(url, download=False))
        raw_entries = info.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("URL resolved to a single video; add it as an individual video")

        entries = [
            self._video_from_info(entry, url)
            for entry in raw_entries
            if isinstance(entry, Mapping)
        ]
        extractor = str(info.get("extractor_key") or info.get("extractor") or "unknown")
        extractor_id = str(info.get("id") or _canonical_url(info, url))
        return ExtractedCollection(
            extractor=extractor,
            extractor_id=extractor_id,
            webpage_url=_canonical_url(info, url),
            title=str(info.get("title") or extractor_id),
            description=info.get("description"),
            uploader=info.get("uploader"),
            uploader_id=info.get("uploader_id"),
            channel=info.get("channel"),
            channel_id=info.get("channel_id"),
            playlist_id=info.get("playlist_id") or info.get("id"),
            thumbnail_url=_thumbnail(info),
            entries=entries,
            raw=info,
        )

    def download(
        self,
        url: str,
        options: DownloadOptions,
        *,
        progress_hook: ProgressHook | None = None,
    ) -> DownloadResult:
        postprocessors: list[dict[str, Any]] = []
        if options.audio_format:
            postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": options.audio_format})
        if options.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata"})
        if options.embed_thumbnail:
            postprocessors.append({"key": "EmbedThumbnail"})

        ydl_options = self._options(
            outtmpl=options.output_template,
            format=options.format_selector,
            merge_output_format=options.merge_output_format,
            writesubtitles=options.write_subtitles,
            writethumbnail=options.embed_thumbnail,
            postprocessors=postprocessors,
            progress_hooks=[progress_hook] if progress_hook else [],
            **options.additional_options,
        )
        with YoutubeDL(ydl_options) as ydl:
            info = self._sanitize(ydl, ydl.extract_info(url, download=True))
            filepath = info.get("filepath") or info.get("_filename")
            if not filepath:
                try:
                    filepath = ydl.prepare_filename(info)
                except Exception:
                    filepath = None

        return DownloadResult(
            extractor=str(info.get("extractor_key") or info.get("extractor") or "unknown"),
            extractor_id=str(info.get("id") or url),
            title=str(info.get("title") or info.get("id") or url),
            filepath=filepath,
            ext=info.get("ext"),
            format_id=info.get("format_id"),
            raw=info,
        )

    def resolve_stream(self, url: str, format_selector: str) -> StreamTarget:
        with YoutubeDL(self._options(noplaylist=True, format=format_selector)) as ydl:
            info = self._sanitize(ydl, ydl.extract_info(url, download=False))

        direct_url = info.get("url")
        if not isinstance(direct_url, str):
            requested = info.get("requested_formats") or []
            if len(requested) == 1 and isinstance(requested[0], Mapping):
                direct_url = requested[0].get("url")
                info = dict(requested[0]) | info
            else:
                raise ValueError(
                    "Stream profile selected separate audio/video formats. "
                    "Use a muxed format selector for direct streaming."
                )
        if not isinstance(direct_url, str):
            raise ValueError("yt-dlp did not resolve a direct stream URL")

        headers = info.get("http_headers") or {}
        return StreamTarget(
            url=direct_url,
            format_id=info.get("format_id"),
            ext=info.get("ext"),
            protocol=info.get("protocol"),
            vcodec=info.get("vcodec"),
            acodec=info.get("acodec"),
            http_headers={str(k): str(v) for k, v in headers.items()},
        )
