from __future__ import annotations

from collections.abc import Sequence

from backend.db.models import Episode, Collection
from task_manager.scheduler.operation_factory import OperationDefinition
from task_manager.scheduler.operations import OperationTargetSpec


_FETCH_EPISODES_TASK_KEY = "fetch_new_episodes"
_REFRESH_METADATA_TASK_KEY = "refresh_episode_metadata"
_RENAME_FILE_TASK_KEY = "rename_collection_profile_files"
_DELETE_DOWNLOADS_TASK_KEY = "delete_collection_downloads_worker"
_SCAN_EXISTING_FILES_TASK_KEY = "scan_existing_files"


class _CollectionOperation(OperationDefinition[Collection]):
    resource_type = "collection"

    def context(self) -> dict[str, object]:
        return {
            "collection_slug": self.resource.slug,
            "collection_title": self.resource.title,
        }


class CollectionIndexOperation(_CollectionOperation):
    kind = "collection.index"
    task = _FETCH_EPISODES_TASK_KEY

    def task_kwargs(self) -> dict[str, object]:
        return {"initial_index": True}


class CollectionSyncOperation(_CollectionOperation):
    kind = "collection.sync"
    task = _FETCH_EPISODES_TASK_KEY


class CollectionDownloadAllOperation(_CollectionOperation):
    kind = "collection.download_all"

    def __init__(self, collection: Collection, *, local_media_profile_id: int, download_count: int) -> None:
        super().__init__(collection)
        self.local_media_profile_id = local_media_profile_id
        self.download_count = download_count

    def context(self) -> dict[str, object]:
        return {
            **super().context(),
            "local_media_profile_id": self.local_media_profile_id,
            "downloads_requested": self.download_count,
        }


class CollectionMetadataRefreshOperation(_CollectionOperation):
    kind = "collection.refresh_metadata"

    def __init__(self, collection: Collection, episodes: Sequence[Episode]) -> None:
        super().__init__(collection)
        self.episodes = tuple(episodes)

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return tuple(
            OperationTargetSpec(
                task_key=_REFRESH_METADATA_TASK_KEY,
                resource_type="episode",
                resource_id=episode.id,
                task_kwargs={"refresh": True},
                slot_key=f"episode:{episode.id}",
            )
            for episode in self.episodes
        )

    def context(self) -> dict[str, object]:
        return {
            **super().context(),
            "episodes_requested": len(self.episodes),
        }


class CollectionFileRenameOperation(_CollectionOperation):
    kind = "collection.rename_files"

    def __init__(
        self,
        collection: Collection,
        *,
        local_media_profile_ids: Sequence[int],
    ) -> None:
        super().__init__(collection)
        self.local_media_profile_ids = tuple(
            dict.fromkeys(int(profile_id) for profile_id in local_media_profile_ids)
        )

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return tuple(
            OperationTargetSpec(
                task_key=_RENAME_FILE_TASK_KEY,
                resource_type="collection",
                resource_id=self.resource.id,
                task_kwargs={"local_media_profile_id": profile_id},
                slot_key=f"profile:{profile_id}",
            )
            for profile_id in self.local_media_profile_ids
        )

    def context(self) -> dict[str, object]:
        return {
            **super().context(),
            "local_media_profiles_requested": len(self.local_media_profile_ids),
        }


class _CollectionDownloadMaintenanceOperation(_CollectionOperation):
    def __init__(
        self,
        collection: Collection,
        *,
        local_media_profile_id: int | None,
        selected_profile_count: int,
    ) -> None:
        super().__init__(collection)
        self.local_media_profile_id = local_media_profile_id
        self.selected_profile_count = selected_profile_count

    def task_kwargs(self) -> dict[str, object]:
        return {"local_media_profile_id": self.local_media_profile_id}

    def context(self) -> dict[str, object]:
        return {
            **super().context(),
            "local_media_profiles_requested": self.selected_profile_count,
        }


class CollectionDeleteDownloadsOperation(_CollectionDownloadMaintenanceOperation):
    kind = "collection.delete_downloads"
    task = _DELETE_DOWNLOADS_TASK_KEY

    def __init__(
        self,
        collection: Collection,
        *,
        local_media_profile_id: int | None,
        selected_profile_count: int,
        disabled_profile_count: int,
        selected_media_download_ids: Sequence[int] | None = None,
    ) -> None:
        super().__init__(
            collection,
            local_media_profile_id=local_media_profile_id,
            selected_profile_count=selected_profile_count,
        )
        self.disabled_profile_count = disabled_profile_count
        # None preserves the existing unfiltered collection-wide behavior. An empty
        # tuple is a valid filtered request with no matching downloads.
        self.selected_media_download_ids = (
            tuple(selected_media_download_ids)
            if selected_media_download_ids is not None else None
        )

    def task_kwargs(self) -> dict[str, object]:
        return {
            **super().task_kwargs(),
            "download_profiles_disabled": self.disabled_profile_count,
            **(
                {"selected_media_download_ids": list(self.selected_media_download_ids)}
                if self.selected_media_download_ids is not None else {}
            ),
        }


class CollectionRedownloadOperation(_CollectionDownloadMaintenanceOperation):
    kind = "collection.redownload_episodes"

    def __init__(
        self,
        collection: Collection,
        *,
        local_media_profile_id: int | None,
        selected_profile_count: int,
        download_count: int,
    ) -> None:
        super().__init__(
            collection,
            local_media_profile_id=local_media_profile_id,
            selected_profile_count=selected_profile_count,
        )
        self.download_count = int(download_count)

    def context(self) -> dict[str, object]:
        return {
            **super().context(),
            "downloads_requested": self.download_count,
        }


class CollectionExistingFilesScanOperation(_CollectionOperation):
    kind = "collection.scan_existing_files"
    task = _SCAN_EXISTING_FILES_TASK_KEY

    def __init__(self, collection: Collection, *, local_media_profile_id: int) -> None:
        super().__init__(collection)
        self.local_media_profile_id = int(local_media_profile_id)

    def task_kwargs(self) -> dict[str, object]:
        return {"local_media_profile_id": self.local_media_profile_id}

    def context(self) -> dict[str, object]:
        return {**super().context(), "local_media_profile_id": self.local_media_profile_id}
