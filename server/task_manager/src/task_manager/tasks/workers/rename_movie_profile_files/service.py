from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.db.models import LocalMediaProfileBase, Movie, MovieExtra, Video
from backend.db.models.media_download import MediaDownloadBase
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.media_types import MediaType
from backend.types.local_media_profile_types import LocalMediaProfileType
from backend.utils.output_template import resolve_movie_output_path, resolve_video_output_path
from backend.services.download_relocation import DownloadRelocation, plan_download_relocation, relocate_downloads
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.helpers.progress import update_progress
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


_PHYSICAL_STATUSES = (
    MediaDownloadArtifactStatus.AVAILABLE.value,
    MediaDownloadArtifactStatus.CORRUPTED.value,
)

# The media types each Local Media Profile type downloads.
_PROFILE_MEDIA_TYPES = {
    LocalMediaProfileType.MOVIE.value: (MediaType.MOVIE.value, MediaType.MOVIE_EXTRA.value),
    LocalMediaProfileType.VIDEO.value: (MediaType.VIDEO.value,),
}


def run_rename_movie_profile_files(
    session: Session,
    *,
    local_media_profile_id: int,
    progress=None,
) -> TaskResult:
    profile = session.get(LocalMediaProfileBase, local_media_profile_id)
    if profile is None:
        return TaskResult(summary="Local Media Profile no longer exists")
    media_types = _PROFILE_MEDIA_TYPES.get(profile.type)
    if media_types is None:
        raise ValueError(f"Local Media Profile {profile.name} is not a Movie or Video profile")

    downloads = list(session.scalars(
        select(MediaDownloadBase)
        .options(
            joinedload(MediaDownloadBase.media),
            joinedload(MediaDownloadBase.local_media_profile),
        )
        .where(
            MediaDownloadBase.local_media_profile_id == local_media_profile_id,
            MediaDownloadBase.type.in_(media_types),
            MediaDownloadBase.artifact_status.in_(_PHYSICAL_STATUSES),
        )
        .order_by(MediaDownloadBase.id.asc())
    ).unique())

    if not downloads:
        update_progress(progress, 100, "No existing files need renaming")
        return TaskResult(
            summary="No existing files need renaming",
            data={
                "files_considered": 0,
                "files_renamed": 0,
                "files_unchanged": 0,
            },
        )

    moves: list[DownloadRelocation] = []
    unchanged = 0
    for index, download in enumerate(downloads, start=1):
        source = resolve_media_download_file(session, download)
        if source is None:
            raise FileNotFoundError(
                f"Cannot rename media download {download.id}: "
                f"'{download.file_path}' does not exist"
            )

        media = download.media
        extension = source.suffix.removeprefix(".")
        if not extension:
            raise ValueError(
                f"Cannot determine extension for media download {download.id}"
            )
        if isinstance(media, Video):
            destination = resolve_video_output_path(
                profile.output_template,
                video=media,
                extension=extension,
            )
        elif isinstance(media, (Movie, MovieExtra)):
            destination = resolve_movie_output_path(
                profile.output_template,
                movie=media if isinstance(media, Movie) else media.movie,
                media_item=media,
                extension=extension,
            )
        else:
            raise ValueError(
                f"Media download {download.id} is not a movie, movie extra or video"
            )
        if source == destination:
            unchanged += 1
            continue

        moves.append(plan_download_relocation(download, source, destination))
        update_progress(
            progress,
            min(20, round(index / len(downloads) * 20)),
            "Planning file renames",
        )

    if not moves:
        update_progress(progress, 100, "Files already have the expected names")
        return TaskResult(
            summary="Files already have the expected names",
            data={
                "files_considered": len(downloads),
                "files_renamed": 0,
                "files_unchanged": unchanged,
            },
        )

    renamed, skipped = relocate_downloads(session, moves, progress=progress, skip_existing=False)
    summary = f"Renamed {renamed} file(s)" + (f"; skipped {skipped} existing destination(s)" if skipped else "")
    update_progress(progress, 100, summary)
    return TaskResult(summary=summary, data={
        "files_considered": len(downloads), "files_renamed": renamed,
        "files_unchanged": unchanged, "files_skipped_existing": skipped,
    })
