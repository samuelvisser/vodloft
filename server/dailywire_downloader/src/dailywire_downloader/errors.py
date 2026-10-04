from __future__ import annotations


from source_contracts.errors import DownloadError, DownloadCancelled, MediaUnavailableError


class EncryptedMediaError(DownloadError):
    """The HLS stream is encrypted; this downloader does not support DRM."""


class FfmpegNotFoundError(DownloadError):
    """The ffmpeg binary required for remuxing could not be found on PATH."""
