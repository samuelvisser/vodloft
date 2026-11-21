"""Moving downloaded episodes' files into the folders of the seasons they are in now."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection
from backend.db.models.media_download import EpisodeMediaDownload
from backend.operations.collections import CollectionFileRenameOperation
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import complete_operation, queue_operation_target_dispatch


def queue_season_folder_moves(s: Session, collection: Collection, episode_ids: list[int]) -> tuple[str, bool]:
    """Rename the files of these episodes into their seasons' folders and numbers. Returns the operation's id and
    whether any file is to move.

    ``s`` is a write transaction's session."""
    profile_ids = sorted(set(s.scalars(
        select(EpisodeMediaDownload.local_media_profile_id).where(
            EpisodeMediaDownload.media_item_id.in_(episode_ids),
            EpisodeMediaDownload.artifact_status.in_((
                MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value,
            )),
        )
    )))
    operation = create_operation(s, CollectionFileRenameOperation(
        collection, local_media_profile_ids=profile_ids, season_folders=True, episode_ids=list(episode_ids),
    ))
    if not profile_ids:
        complete_operation(s, operation.id, summary="No files to move")
    for profile_id in profile_ids:
        queue_operation_target_dispatch(s, operation.id, f"profile:{profile_id}")
    return operation.id, bool(profile_ids)
