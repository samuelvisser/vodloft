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


class AccessRequiredError(DownloadError):
    """The Source only gives the media with an access VODLoft does not have, such as a paid
    subscription or a channel membership. ``access`` is the Source's key for it, when known."""

    def __init__(self, message: str, access: str | None = None):
        super().__init__(message)
        self.access = access


class FileTooLargeError(DownloadError):
    """The file is larger than the caller allows, so the download stopped."""


class DownloadCanceled(DownloadError):
    """The download was canceled through the should_cancel callback."""


class FfmpegNotFoundError(DownloadError):
    """The ffmpeg binary required for remuxing could not be found on PATH."""
