from __future__ import annotations

from collections.abc import Sequence

from backend.db.models.media_item import Movie
from task_manager.scheduler.operation_factory import OperationDefinition
from task_manager.scheduler.operations import OperationTargetSpec


_REFRESH_MOVIE_EXTRAS_TASK_KEY = "refresh_movie_extras"
_BULK_DOWNLOAD_TASK_KEY = "media_download_bulk_action_worker"


class MovieExtrasRefreshOperation(OperationDefinition[Movie]):
    kind = "movie.refresh_extras"
    resource_type = "movie"
    task = _REFRESH_MOVIE_EXTRAS_TASK_KEY

    def context(self) -> dict[str, object]:
        return {
            "movie_slug": self.resource.slug,
            "movie_title": self.resource.title,
        }


class MovieRedownloadOperation(OperationDefinition[Movie]):
    kind = "movie.redownload_media"
    request_priority = "bulk"
    resource_type = "movie"

    def __init__(self, movie: Movie, *, media_download_ids: Sequence[int]) -> None:
        super().__init__(movie)
        self.media_download_ids = tuple(
            dict.fromkeys(int(download_id) for download_id in media_download_ids)
        )

    def context(self) -> dict[str, object]:
        return {
            "movie_slug": self.resource.slug,
            "movie_title": self.resource.title,
            "downloads_requested": len(self.media_download_ids),
        }


class MovieDeleteDownloadsOperation(OperationDefinition[Movie]):
    """Delete the files of a movie and its extras, one bulk-action target per download."""

    kind = "movie.delete_downloads"
    resource_type = "movie"

    def __init__(self, movie: Movie, *, media_download_ids: Sequence[int]) -> None:
        super().__init__(movie)
        self.media_download_ids = tuple(
            dict.fromkeys(int(download_id) for download_id in media_download_ids)
        )

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
            "movie_slug": self.resource.slug,
            "movie_title": self.resource.title,
            "downloads_requested": len(self.media_download_ids),
        }
