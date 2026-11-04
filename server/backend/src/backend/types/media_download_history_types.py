from enum import StrEnum


class MediaDownloadHistoryAction(StrEnum):
    """Durable user-meaningful events in one MediaDownload's lifetime."""

    CREATED = "created"
    QUEUED = "queued"
    PRIORITIZED = "prioritized"
    RETRY_REQUESTED = "retry_requested"
    RESTARTED = "restarted"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"
    ARTIFACT_REMOVED = "artifact_removed"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_CORRUPTED = "artifact_corrupted"
    ARTIFACT_RESTORED = "artifact_restored"
    ARTIFACT_RENAMED = "artifact_renamed"
    IMPORTED = "imported"
    MOVED = "moved"
    """The download moved over to another Local Media Profile."""
    UPGRADE_CHECKED = "upgrade_checked"
    """The upgrade check compared the download with what the site offers now."""
