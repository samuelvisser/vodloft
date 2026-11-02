from fastapi import APIRouter, Query, status

from .service import *
from ...models.episode import *
from ...models.media_download import EpisodeDownloadAPICreate
from ...models.operations import EpisodeMetadataOperationAccepted, MediaDownloadOperationAccepted, TaskOperationAccepted
from ..media_downloads.service import create_episode_download
from backend.app import db_session
from backend.db.models import Episode
from backend.services.episode_download_delay import episode_download_delay_ready_at
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.media_download_operations import (
    create_media_download_operation,
    dispatch_queued_media_download_operations,
)
from backend.security.access import Area, Level
from backend.security.deps import may_delete_files, requires

router = APIRouter(prefix="/episodes", tags=["Episodes"])


@router.post(
    "/{episode_slug}/downloads",
    dependencies=[requires(Area.MANAGED_DOWNLOADS, Level.MANAGE)],
    response_model=MediaDownloadOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def episode_download_create(episode_slug: str, body: EpisodeDownloadAPICreate):
    """Start now or schedule an episode download through the canonical operation path."""
    with db_session() as s:
        try:
            download = create_episode_download(s, episode_slug, body)
            scheduled_ready_at = None
            if body.schedule_for_delay:
                episode = download.media
                if not isinstance(episode, Episode):
                    raise RuntimeError("Episode download does not reference an episode")
                scheduled_ready_at = episode_download_delay_ready_at(episode)
            operation = create_media_download_operation(
                s,
                download,
                source=(
                    OperationSource.SYSTEM
                    if body.schedule_for_delay
                    else OperationSource.UI
                ),
                not_before=scheduled_ready_at,
            )
            dispatch_queued_media_download_operations(s)
            result = {
                "queued": True,
                "operation_id": operation.id,
                "media_download_id": download.id,
            }
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.get("/by-collection-slug/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[EpisodeAPIRead])
def episodes_by_collection_list(collection_slug: str, limit: int | None = None):
    """List complete episode records for callers that need episode detail fields."""
    with db_session() as s:
        return get_episodes_by_collection_list(s, collection_slug, limit)


@router.get("/as-view/by-collection-slug/{collection_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[EpisodeAPIReadView])
def episode_views_by_collection_list(collection_slug: str, limit: int | None = None):
    """List compact episode fields."""
    with db_session() as s:
        return get_episode_views_by_collection_list(s, collection_slug, limit)


@router.get("/as-view/by-collection-slug/{collection_slug}/page", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=EpisodeAPIReadViewPage)
def episode_views_by_collection_page(
        collection_slug: str,
        cursor: str | None = Query(default=None, max_length=2048),
        limit: int = Query(default=25, ge=1, le=100),
        season_id: int | None = Query(default=None, ge=1),
):
    """Return one compact episode page for a collection grid or browser cache preview."""
    with db_session() as s:
        return get_episode_views_by_collection_page(
            s,
            collection_slug,
            cursor=cursor,
            limit=limit,
            season_id=season_id,
        )


@router.get("/as-view/recently-indexed", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=list[EpisodeIndexedActivityAPIRead])
def recently_indexed_episode_views(
        limit: int = Query(default=7, ge=1, le=50),
):
    """Return the most recently indexed episodes for activity surfaces."""
    with db_session() as s:
        return get_recently_indexed_episodes(s, limit=limit)


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=EpisodeAPIRead, status_code=status.HTTP_201_CREATED)
def episode_create(body: EpisodeAPICreate):
    """
    Create a new episode for a collection.

    Creates a new episode with the provided metadata and associates it with a collection.
    Returns the created episode with a generated slug identifier.
    """
    with db_session() as s:
        try:
            result = create_episode(s, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{episode_slug}/refresh-metadata",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    response_model=EpisodeMetadataOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def episode_metadata_refresh(episode_slug: str):
    """Queue an immediate metadata refresh for one episode."""
    with db_session() as s:
        try:
            result = request_episode_metadata_refresh(s, episode_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.post(
    "/{episode_slug}/early-delete",
    dependencies=[requires(Area.LIBRARY, Level.MANAGE), may_delete_files()],
    response_model=TaskOperationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def episode_early_delete(episode_slug: str):
    """Immediately remove one episode that is currently stuck in dw_processing."""
    with db_session() as s:
        try:
            result = request_episode_early_delete(s, episode_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.get("/{episode_slug}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=EpisodeAPIRead)
def episode_detail(episode_slug: str):
    with db_session() as s:
        return get_episode(s, episode_slug)


@router.patch("/{episode_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=EpisodeAPIRead)
def episode_update(episode_slug: str, body: EpisodeAPIUpdate):
    with db_session() as s:
        try:
            result = update_episode(s, episode_slug, body)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise


@router.delete("/{episode_slug}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=EpisodeAPIRead)
def episode_delete(episode_slug: str):
    with db_session() as s:
        try:
            result = delete_episode(s, episode_slug)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
