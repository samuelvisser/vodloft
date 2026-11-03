from __future__ import annotations

from collections.abc import Sequence

from backend.db.models import LocalMediaProfileBase
from task_manager.scheduler.operation_factory import OperationDefinition
from task_manager.scheduler.operations import OperationTargetSpec


_RENAME_COLLECTION_FILES_TASK_KEY = "rename_collection_profile_files"
_RENAME_MOVIE_FILES_TASK_KEY = "rename_movie_profile_files"
_BULK_DOWNLOAD_TASK_KEY = "media_download_bulk_action_worker"
_MOVE_EPISODES_TASK_KEY = "move_collection_profile_episodes"


class LocalMediaProfileFileRenameOperation(OperationDefinition[LocalMediaProfileBase]):
    kind = "local_media_profile.rename_files"
    resource_type = "local_media_profile"

    def __init__(
        self,
        local_media_profile: LocalMediaProfileBase,
        *,
        collection_ids: Sequence[int] = (),
        movie_profile: bool = False,
    ) -> None:
        super().__init__(local_media_profile)
        self.collection_ids = tuple(dict.fromkeys(int(collection_id) for collection_id in collection_ids))
        self.movie_profile = bool(movie_profile)

    @property
    def title(self) -> str:
        return self.resource.name

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        if self.movie_profile:
            return (
                OperationTargetSpec(
                    task_key=_RENAME_MOVIE_FILES_TASK_KEY,
                    resource_type="local_media_profile",
                    resource_id=self.resource.id,
                    slot_key=f"profile:{self.resource.id}",
                ),
            )
        return tuple(
            OperationTargetSpec(
                task_key=_RENAME_COLLECTION_FILES_TASK_KEY,
                resource_type="collection",
                resource_id=collection_id,
                task_kwargs={"local_media_profile_id": self.resource.id},
                slot_key=f"collection:{collection_id}",
            )
            for collection_id in self.collection_ids
        )

    def context(self) -> dict[str, object]:
        return {
            "local_media_profile_slug": self.resource.slug,
            "local_media_profile_name": self.resource.name,
            "collections_requested": len(self.collection_ids),
        }


class LocalMediaProfileDeleteDownloadsOperation(OperationDefinition[LocalMediaProfileBase]):
    kind = "local_media_profile.delete_downloads"
    resource_type = "local_media_profile"

    def __init__(
        self,
        local_media_profile: LocalMediaProfileBase,
        *,
        media_download_ids: Sequence[int],
        disabled_download_profiles: int,
    ) -> None:
        super().__init__(local_media_profile)
        self.media_download_ids = tuple(
            dict.fromkeys(int(download_id) for download_id in media_download_ids)
        )
        self.disabled_download_profiles = int(disabled_download_profiles)

    @property
    def title(self) -> str:
        return self.resource.name

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return tuple(
            OperationTargetSpec(
                task_key=_BULK_DOWNLOAD_TASK_KEY,
                resource_type="media_download",
                resource_id=download_id,
                task_kwargs={
                    "media_download_id": download_id,
                    "action": "delete_artifact",
                },
                slot_key=f"media_download:{download_id}",
            )
            for download_id in self.media_download_ids
        )

    def context(self) -> dict[str, object]:
        return {
            "local_media_profile_slug": self.resource.slug,
            "local_media_profile_name": self.resource.name,
            "downloads_requested": len(self.media_download_ids),
            "download_profiles_disabled": self.disabled_download_profiles,
        }


class LocalMediaProfileRedownloadOperation(OperationDefinition[LocalMediaProfileBase]):
    kind = "local_media_profile.redownload_media"
    resource_type = "local_media_profile"

    def __init__(
        self,
        local_media_profile: LocalMediaProfileBase,
        *,
        media_download_ids: Sequence[int],
    ) -> None:
        super().__init__(local_media_profile)
        self.media_download_ids = tuple(
            dict.fromkeys(int(download_id) for download_id in media_download_ids)
        )

    @property
    def title(self) -> str:
        return self.resource.name

    def context(self) -> dict[str, object]:
        return {
            "local_media_profile_slug": self.resource.slug,
            "local_media_profile_name": self.resource.name,
            "downloads_requested": len(self.media_download_ids),
        }


class LocalMediaProfileMoveEpisodesOperation(OperationDefinition[LocalMediaProfileBase]):
    """Move a Collection Local Media Profile's downloads to another profile, one task per Collection."""

    kind = "local_media_profile.move_episodes"
    resource_type = "local_media_profile"

    def __init__(
        self,
        local_media_profile: LocalMediaProfileBase,
        *,
        target: LocalMediaProfileBase,
        collections: Sequence[tuple[int, bool, Sequence[int]]],
        episodes_requested: int,
    ) -> None:
        """``collections`` holds, per Collection: its id, whether its Download Profile moves along,
        and the Download Profiles switched off while it moves."""
        super().__init__(local_media_profile)
        self.target = target
        self.collections = tuple(
            (int(collection_id), bool(move_download_profile), tuple(int(value) for value in held))
            for collection_id, move_download_profile, held in collections
        )
        self.episodes_requested = int(episodes_requested)

    @property
    def title(self) -> str:
        return self.resource.name

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return tuple(
            OperationTargetSpec(
                task_key=_MOVE_EPISODES_TASK_KEY,
                resource_type="collection",
                resource_id=collection_id,
                task_kwargs={
                    "source_local_media_profile_id": self.resource.id,
                    "target_local_media_profile_id": self.target.id,
                    "move_download_profile": move_download_profile,
                    "held_download_profile_ids": list(held),
                },
                slot_key=f"collection:{collection_id}",
            )
            for collection_id, move_download_profile, held in self.collections
        )

    def context(self) -> dict[str, object]:
        return {
            "local_media_profile_slug": self.resource.slug,
            "local_media_profile_name": self.resource.name,
            "target_local_media_profile_slug": self.target.slug,
            "target_local_media_profile_name": self.target.name,
            "target_local_media_profile_id": self.target.id,
            "collections_requested": len(self.collections),
            "episodes_requested": self.episodes_requested,
        }
