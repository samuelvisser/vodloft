"""Moving downloaded episodes' files into the folders of the seasons they are in now."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection
from backend.db.models.media_download import EpisodeMediaDownload
from backend.operations.collections import CollectionFileRenameOperation
from backend.services.download_options import effective_filename_mode
from backend.services.no_ascii_names import settle_no_ascii_name
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.utils.output_template import resolve_episode_output_path
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


def queue_metadata_rewrite(s: Session, collection: Collection, episode_ids: list[int]) -> None:
    """Write the metadata of these episodes' downloads again, such as after they changed season while their files
    stayed where they are. Their files are renamed too, should their names have changed after all.

    ``s`` is a write transaction's session."""
    profile_ids = sorted(set(s.scalars(
        select(EpisodeMediaDownload.local_media_profile_id).where(
            EpisodeMediaDownload.media_item_id.in_(episode_ids),
            EpisodeMediaDownload.artifact_status.in_((
                MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value,
            )),
        )
    )))
    if not profile_ids:
        return
    operation = create_operation(s, CollectionFileRenameOperation(
        collection, local_media_profile_ids=profile_ids, season_folders=True, episode_ids=list(episode_ids),
        rewrite_metadata=True,
    ))
    for profile_id in profile_ids:
        queue_operation_target_dispatch(s, operation.id, f"profile:{profile_id}")


def follow_new_place(s: Session, download: EpisodeMediaDownload) -> bool:
    """A download that was running when its episode moved, such as to another season, finishes under the name and with
    the metadata the episode had when it started. Rename it into its new place and write its metadata again, as the
    move did for the files that were there already. Returns whether it had to.

    ``s`` is a write transaction's session, in which the finished download is recorded."""
    profile = download.local_media_profile
    path = Path(download.file_path)
    destination = settle_no_ascii_name(download, resolve_episode_output_path(
        profile.output_template, episode=download.media, local_media_profile=profile, media_download=download,
        filename_mode=effective_filename_mode(profile), extension=path.suffix.removeprefix("."),
    ), session=s)
    if destination == path:
        return False
    operation = create_operation(s, CollectionFileRenameOperation(
        download.media.collection, local_media_profile_ids=[profile.id], season_folders=True,
        episode_ids=[download.media_item_id], rewrite_metadata=True,
    ))
    queue_operation_target_dispatch(s, operation.id, f"profile:{profile.id}")
    return True
