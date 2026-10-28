from __future__ import annotations


class DownloadError(Exception):
    """Base error for everything raised by this package."""


class MediaUnavailableError(DownloadError):
    """The media URL cannot be used (404/403/410 or an expired signed URL).

    Callers should treat this as "get a fresh URL and try again", not as a
    transient network problem.
    """


class EncryptedMediaError(DownloadError):
    """The HLS stream is encrypted; this downloader does not support DRM."""


class SubscriptionRequiredError(DownloadError):
    """The Source only gives the media to a paying account, which VODLoft does not have."""


class FileTooLargeError(DownloadError):
    """The file is larger than the caller allows, so the download stopped."""


class DownloadCancelled(DownloadError):
    """The download was cancelled through the should_cancel callback."""


class FfmpegNotFoundError(DownloadError):
    """The ffmpeg binary required for remuxing could not be found on PATH."""
