"""Provider-neutral work failures shared with media/task primitives."""

class DownloadError(Exception):
    pass

class MediaUnavailableError(DownloadError):
    pass

class DownloadCancelled(DownloadError):
    pass
