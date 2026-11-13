from __future__ import annotations

from collections.abc import Sequence

from backend.db.models import DownloadProfile
from task_manager.scheduler.operation_factory import OperationDefinition
from task_manager.scheduler.operations import OperationTargetSpec


_BULK_DOWNLOAD_TASK_KEY = "media_download_bulk_action_worker"


class DownloadProfileDeleteOutOfScopeOperation(OperationDefinition[DownloadProfile]):
    """Delete downloads of a Download Profile that its filters no longer cover, one target per download."""

    kind = "download_profile.delete_out_of_scope"
    resource_type = "download_profile"

    def __init__(self, download_profile: DownloadProfile, *, media_download_ids: Sequence[int]) -> None:
        super().__init__(download_profile)
        self.media_download_ids = tuple(dict.fromkeys(int(download_id) for download_id in media_download_ids))

    @property
    def title(self) -> str:
        return f"{self.resource.collection.title} ({self.resource.local_media_profile.name})"

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return tuple(
            OperationTargetSpec(
                task_key=_BULK_DOWNLOAD_TASK_KEY,
                resource_type="media_download",
                # The target deletes the download, so it must not own the row it removes.
                resource_id=None,
                task_kwargs={"media_download_id": download_id, "action": "delete_out_of_scope"},
                slot_key=f"media_download:{download_id}",
            )
            for download_id in self.media_download_ids
        )

    def context(self) -> dict[str, object]:
        return {
            "collection_title": self.resource.collection.title,
            "local_media_profile_name": self.resource.local_media_profile.name,
            "downloads_requested": len(self.media_download_ids),
        }
