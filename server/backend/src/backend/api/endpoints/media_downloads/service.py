from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import (
    Session,
    joinedload,
    load_only,
    raiseload,
    selectinload,
    with_polymorphic,
)

from backend.api.pagination import (
    InvalidCursorError,
    cursor_key_values,
    decode_cursor,
    encode_cursor,
)
from backend.api.models.media_download import (
    DownloadedLocalMediaProfileAPIRead,
    EpisodeDownloadAPICreate,
    MediaDownloadAPIRead,
    MediaDownloadAPIReadView,
    MediaDownloadKeptAPIRequest,
    MediaDownloadAPIUpdate,
    MediaDownloadPageRead,
    MediaDownloadAPICreate,
)
from backend.db.model_mapping import update_database_fields
from backend.db.models import (
    Episode,
    LocalMediaProfileBase,
    MediaDownloadBase,
    Movie,
    MovieExtra,
    MovieExtraSource,
    Collection,
    Video,
)
from backend.db.models.media_download import (
    EpisodeMediaDownload,
    MovieExtraMediaDownload,
    MovieMediaDownload,
    VideoMediaDownload,
)
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from backend.types.episode_types import EpisodePublishStatus
from backend.services.media_access import media_access, media_locked
from backend.services.local_media_profile_sites import profile_offered_for_site
from backend.services.sites import collection_site_key, movie_site_key, video_site_key
from backend.types.local_media_profile_types import LocalMediaProfileType
from backend.types.media_types import MediaType
from downloader.storage.artifacts import remove_download_artifacts
from backend.services.episode_download_delay import episode_download_delay_passed
from backend.services.media_download_collection import (
    latest_download_runs,
    media_download_bulk_action_ids,
    media_download_queue_positions,
    read_media_download_page_window,
)
from backend.services.media_download_history import record_media_download_history
from backend.utils.output_template import (
    resolve_episode_output_path,
    resolve_movie_output_path,
    resolve_video_output_path,
)
from sources import get_source
from task_manager.scheduler.db import TaskRun
from task_manager.tasks.media_download_operations import (
    get_active_media_download_operation,
    prepare_media_download_artifact,
)
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


def _resolve_episode_download_path(
    s: Session,
    profile,
    episode: Episode,
    download: EpisodeMediaDownload,
) -> str:
    return str(resolve_episode_output_path(
        profile.output_template,
        episode=episode,
        local_media_profile=profile,
        media_download=download,
    ))


def get_media_downloads_list(s: Session) -> list[MediaDownloadAPIRead]:
    items = s.query(MediaDownloadBase).order_by(MediaDownloadBase.id).all()
    return [MediaDownloadAPIRead.model_validate(it) for it in items]


@dataclass(frozen=True)
class _MediaDownloadViewSource:
    """Typed sources consumed declaratively by MediaDownloadAPIReadView."""

    download: MediaDownloadBase
    media: Episode | Movie | MovieExtra | Video | None
    latest_run: TaskRun | None
    queue_position: int | None

    @property
    def profile(self) -> LocalMediaProfileBase:
        return self.download.local_media_profile

    @property
    def episode(self) -> Episode | None:
        return self.media if isinstance(self.media, Episode) else None

    @property
    def movie_extra(self) -> MovieExtra | None:
        return self.media if isinstance(self.media, MovieExtra) else None

    @property
    def movie(self) -> Movie | None:
        if isinstance(self.media, Movie):
            return self.media
        if isinstance(self.media, MovieExtra):
            return self.media.movie
        return None

    @property
    def collection(self) -> Collection | None:
        return self.media.collection if isinstance(self.media, Episode) else None

    @property
    def latest_task_is_redownload(self) -> Optional[bool]:
        return _run_is_redownload(self.latest_run)


def _run_is_redownload(run: TaskRun | None) -> Optional[bool]:
    if run is None:
        return None

    meta = run.meta if isinstance(run.meta, dict) else {}
    inputs = meta.get("inputs") if isinstance(meta.get("inputs"), dict) else {}
    value = inputs.get("is_redownload")
    if isinstance(value, bool):
        return value

    result = run.result if isinstance(run.result, dict) else {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    value = data.get("is_redownload")
    return value if isinstance(value, bool) else None


def _load_media_items_for_view(
        s: Session,
        downloads: list[MediaDownloadBase],
) -> dict[int, Episode | Movie | MovieExtra | Video]:
    """Load the small media context required by the view in bounded ORM queries.

    Keeping this separate from the download query avoids both a wide positional
    projection and N+1s. Relationship and column raiseload guards ensure future
    view fields cannot accidentally add hidden lazy queries.
    """
    ids_by_type: dict[str, list[int]] = {}
    for download in downloads:
        ids_by_type.setdefault(download.type, []).append(download.media_item_id)

    media_by_id: dict[int, Episode | Movie | MovieExtra | Video] = {}

    episode_ids = ids_by_type.get(MediaType.EPISODE.value, [])
    if episode_ids:
        episodes = s.scalars(
            select(Episode)
            .where(Episode.id.in_(episode_ids))
            .options(
                load_only(
                    Episode.id,
                    Episode.slug,
                    Episode.title,
                    Episode.episode_identifier,
                    Episode.source_key,
                    Episode.access,
                    Episode.access_refused_at,
                    Episode.access_check_at,
                    raiseload=True,
                ),
                joinedload(Episode.collection).load_only(
                    Collection.id,
                    Collection.slug,
                    Collection.title,
                    Collection.site_key,
                    raiseload=True,
                ),
                raiseload("*"),
            )
        )
        media_by_id.update((episode.id, episode) for episode in episodes)

    movie_ids = ids_by_type.get(MediaType.MOVIE.value, [])
    if movie_ids:
        movies = s.scalars(
            select(Movie)
            .where(Movie.id.in_(movie_ids))
            .options(
                load_only(
                    Movie.id,
                    Movie.slug,
                    Movie.title,
                    Movie.source_key,
                    Movie.access,
                    Movie.access_refused_at,
                    Movie.access_check_at,
                    raiseload=True,
                ),
                raiseload("*"),
            )
        )
        media_by_id.update((movie.id, movie) for movie in movies)

    movie_extra_ids = ids_by_type.get(MediaType.MOVIE_EXTRA.value, [])
    if movie_extra_ids:
        movie_extras = s.scalars(
            select(MovieExtra)
            .where(MovieExtra.id.in_(movie_extra_ids))
            .options(
                load_only(
                    MovieExtra.id,
                    MovieExtra.movie_id,
                    MovieExtra.source_id,
                    MovieExtra.movie_extra_type,
                    MovieExtra.source_key,
                    MovieExtra.access,
                    MovieExtra.access_refused_at,
                    MovieExtra.access_check_at,
                    raiseload=True,
                ),
                joinedload(MovieExtra.movie).load_only(
                    Movie.id,
                    Movie.slug,
                    Movie.title,
                    raiseload=True,
                ),
                joinedload(MovieExtra.source).load_only(
                    MovieExtraSource.id,
                    MovieExtraSource.slug,
                    MovieExtraSource.title,
                    raiseload=True,
                ),
                raiseload("*"),
            )
        )
        media_by_id.update((movie_extra.id, movie_extra) for movie_extra in movie_extras)

    video_ids = ids_by_type.get(MediaType.VIDEO.value, [])
    if video_ids:
        videos = s.scalars(
            select(Video)
            .where(Video.id.in_(video_ids))
            .options(
                load_only(
                    Video.id,
                    Video.slug,
                    Video.title,
                    Video.source_key,
                    Video.site_key,
                    Video.access,
                    Video.access_refused_at,
                    Video.access_check_at,
                    raiseload=True,
                ),
                raiseload("*"),
            )
        )
        media_by_id.update((video.id, video) for video in videos)

    return media_by_id


def _media_download_view_statement(
        *,
        episode_slug: Optional[str],
        movie_slug: Optional[str],
        collection_slug: Optional[str],
        statuses: Optional[list[str]],
        limit: Optional[int],
        ids: Optional[list[int]] = None,
        video_id: Optional[int] = None,
        media_types: Optional[list[MediaType]] = None,
        episode_ids: Optional[list[int]] = None,
):
    """Build the scoped download query while returning complete ORM models."""
    download = with_polymorphic(MediaDownloadBase, "*")
    stmt = (
        select(download)
        .options(
            joinedload(download.local_media_profile).load_only(
                LocalMediaProfileBase.id,
                LocalMediaProfileBase.name,
                LocalMediaProfileBase.preferred_format,
                raiseload=True,
            ),
            selectinload(download.assets),
            raiseload("*"),
        )
        .order_by(download.id.desc())
    )

    if statuses:
        stmt = stmt.where(download.artifact_status.in_(statuses))

    if ids is not None:
        stmt = stmt.where(download.id.in_(ids))

    if media_types:
        stmt = stmt.where(download.type.in_([media_type.value for media_type in media_types]))

    if episode_ids:
        stmt = stmt.where(download.type == MediaType.EPISODE.value, download.media_item_id.in_(episode_ids))

    if episode_slug is not None:
        episode_ids = select(Episode.id).where(Episode.slug == episode_slug)
        stmt = stmt.where(download.media_item_id.in_(episode_ids))

    if collection_slug is not None:
        collection_episode_ids = (
            select(Episode.id)
            .join(Collection, Collection.id == Episode.collection_id)
            .where(Collection.slug == collection_slug)
        )
        stmt = stmt.where(download.media_item_id.in_(collection_episode_ids))

    if movie_slug is not None:
        movie_ids = select(Movie.id).where(Movie.slug == movie_slug)
        movie_extra_ids = select(MovieExtra.id).where(
            MovieExtra.movie_id.in_(movie_ids)
        )
        stmt = stmt.where(or_(
            download.media_item_id.in_(movie_ids),
            download.media_item_id.in_(movie_extra_ids),
        ))

    if video_id is not None:
        stmt = stmt.where(
            download.type == MediaType.VIDEO.value,
            download.media_item_id == video_id,
        )

    if limit is not None:
        stmt = stmt.limit(limit)

    return stmt


def _build_media_download_views(
        s: Session,
        downloads: list[MediaDownloadBase],
        *,
        latest_runs: dict[int, TaskRun] | None = None,
        queue_positions: dict[int, int] | None = None,
) -> list[MediaDownloadAPIReadView]:
    media_by_id = _load_media_items_for_view(s, downloads)
    if latest_runs is None:
        latest_runs = latest_download_runs(s, [download.id for download in downloads])
    queue_positions = (
        queue_positions
        if queue_positions is not None
        else media_download_queue_positions(s,
            [download.id for download in downloads],
        )
    )
    return [
        MediaDownloadAPIReadView.model_validate(
            _MediaDownloadViewSource(
                download=download,
                media=media_by_id.get(download.media_item_id),
                latest_run=latest_runs.get(download.id),
                queue_position=queue_positions.get(download.id),
            )
        )
        for download in downloads
    ]


def get_media_downloads_view(
        s: Session,
        *,
        episode_slug: Optional[str] = None,
        movie_slug: Optional[str] = None,
        collection_slug: Optional[str] = None,
        video_id: Optional[int] = None,
        media_types: Optional[list[MediaType]] = None,
        episode_ids: Optional[list[int]] = None,
        statuses: Optional[list[str]] = None,
        limit: Optional[int] = None,
) -> list[MediaDownloadAPIReadView]:
    """Return scoped artifact state with all view context loaded in bounded queries."""
    downloads = list(s.scalars(_media_download_view_statement(
        episode_slug=episode_slug,
        movie_slug=movie_slug,
        collection_slug=collection_slug,
        video_id=video_id,
        media_types=media_types,
        episode_ids=episode_ids,
        statuses=statuses,
        limit=limit,
    )))
    return _build_media_download_views(s, downloads)


def get_downloaded_local_media_profiles(s: Session, collection_slug: str) -> list[DownloadedLocalMediaProfileAPIRead]:
    """The Local Media Profiles with an episode download of the Collection that is not absent, by name."""
    has_download = (
        select(EpisodeMediaDownload.id)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .join(Collection, Collection.id == Episode.collection_id)
        .where(
            Collection.slug == collection_slug,
            EpisodeMediaDownload.local_media_profile_id == LocalMediaProfileBase.id,
            EpisodeMediaDownload.artifact_status != MediaDownloadArtifactStatus.ABSENT.value,
        )
        .exists()
    )
    profiles = s.scalars(
        select(LocalMediaProfileBase).where(has_download).order_by(LocalMediaProfileBase.name)
    )
    return [DownloadedLocalMediaProfileAPIRead.model_validate(profile) for profile in profiles]


def get_media_downloads_page(
        s: Session,
        *,
        statuses: Optional[list[str]] = None,
        order: str = "workflow",
        cursor: str | None = None,
        limit: int = 50,
) -> MediaDownloadPageRead:
    """Return one cursor page in the requested UI ordering."""
    requested_statuses = sorted(set(statuses or []))

    after_id: int | None = None
    after_revision: str | None = None
    if cursor:
        try:
            values = decode_cursor(cursor)
            if (
                values.get("kind") != "media-download"
                or values.get("order") != order
                or values.get("statuses") != requested_statuses
            ):
                raise InvalidCursorError("Cursor does not match this download collection")
            cursor_value = cursor_key_values(values, length=1)[0]
            if not isinstance(cursor_value, int) or isinstance(cursor_value, bool):
                raise InvalidCursorError("Invalid download cursor key")
            after_id = cursor_value
            after_revision = values.get("revision")
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        window = read_media_download_page_window(
            s,
            statuses=requested_statuses,
            order=order,
            limit=limit,
            after_id=after_id,
            after_revision=after_revision,
        )
    except LookupError:
        raise HTTPException(status_code=422, detail="Invalid download cursor key")

    has_more = len(window.ids) > limit
    selected_ids = window.ids[:limit]
    revision = window.revision

    if selected_ids:
        selected_downloads_by_id = {
            download.id: download
            for download in s.scalars(
                _media_download_view_statement(
                    episode_slug=None,
                    movie_slug=None,
                    collection_slug=None,
                    statuses=None,
                    limit=None,
                    ids=selected_ids,
                )
            )
        }
        selected_downloads = [
            selected_downloads_by_id[media_download_id]
            for media_download_id in selected_ids
            if media_download_id in selected_downloads_by_id
        ]
    else:
        selected_downloads = []

    next_cursor = None
    if has_more:
        # The next page continues after this row while the order stays the same.
        cursor_key = [selected_ids[-1]]
        next_cursor = encode_cursor({
            "kind": "media-download",
            "order": order,
            "statuses": requested_statuses,
            "revision": revision,
            "key": cursor_key,
        })

    return MediaDownloadPageRead(
        items=_build_media_download_views(
            s,
            selected_downloads,
        ),
        total=window.total,
        limit=limit,
        next_cursor=next_cursor,
        revision=revision,
        facets=window.facets,
        actions=window.actions,
    )


def get_media_download_bulk_action_ids(
        s: Session,
        *,
        statuses: Optional[list[str]],
        action: str,
) -> list[int]:
    """Return every row in the filtered collection that supports one bulk action"""
    return media_download_bulk_action_ids(s, statuses=sorted(set(statuses or [])), action=action)


def get_media_download(s: Session, media_download_id: int) -> MediaDownloadAPIRead:
    item = s.query(MediaDownloadBase).filter_by(id=media_download_id).one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    return MediaDownloadAPIRead.model_validate(item)


def _assert_no_active_attempt(s: Session, download: MediaDownloadBase) -> None:
    if get_active_media_download_operation(s, download.id) is not None:
        raise HTTPException(status_code=409, detail="This download already has an active operation")


def _reconcile_existing_artifact(s: Session, download: MediaDownloadBase) -> None:
    if download.artifact_status != MediaDownloadArtifactStatus.ABSENT.value:
        resolve_media_download_file(s, download)


DRM_PROTECTED_MESSAGE = "Protected by DRM, cannot be downloaded"


def _ensure_downloadable(media) -> None:
    if media.drm_protected:
        raise HTTPException(status_code=422, detail=DRM_PROTECTED_MESSAGE)
    if media_locked(media):
        access = media_access(media)
        raise HTTPException(status_code=422, detail=f"Locked: {access.label}" if access else "Locked")


def create_new_episode_download(
    s: Session,
    episode: Episode,
    profile: LocalMediaProfileBase,
    *,
    redownload_when_final: bool = False,
    redownload_when_delay_passed: bool = False,
) -> EpisodeMediaDownload:
    """Persist an episode download for an already-selected episode and profile."""
    download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=episode.id,
        local_media_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path="",
        redownload_when_final=redownload_when_final,
        redownload_when_delay_passed=redownload_when_delay_passed,
    )
    s.add(download)
    s.flush()
    download.file_path = _resolve_episode_download_path(s, profile, episode, download)
    s.flush()
    record_media_download_history(
        s,
        download.id,
        MediaDownloadHistoryAction.CREATED,
        metadata={
            "file_path": download.file_path,
            "local_media_profile_id": profile.id,
        },
    )
    return download


def create_episode_download(s: Session, episode_slug: str, body: EpisodeDownloadAPICreate) -> EpisodeMediaDownload:
    episode: Optional[Episode] = s.query(Episode).filter(Episode.slug == episode_slug).one_or_none()
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if episode.publish_status == EpisodePublishStatus.NO_USABLE_MEDIA.value:
        raise HTTPException(status_code=422, detail="Episode has no usable media")
    if episode.publish_status == EpisodePublishStatus.SOURCE_PROCESSING.value:
        raise HTTPException(status_code=422, detail="Episode media is still processing on Daily Wire")
    _ensure_downloadable(episode)

    profile = _get_profile(s, body.local_media_profile_id, LocalMediaProfileType.COLLECTION, collection_site_key(episode.collection))
    redownload_when_final = (
        body.redownload_when_final
        and episode.publish_status == EpisodePublishStatus.PUBLISHED_PRELIMINARY.value
    )
    redownload_when_delay_passed = (
        body.redownload_when_delay_passed
        and not body.schedule_for_delay
        and episode.publish_status == EpisodePublishStatus.PUBLISHED_FINAL
        and not episode_download_delay_passed(episode)
    )
    # A manual download undoes an earlier deletion of this record.
    episode.set_download_dismissed(profile.id, False)
    existing: Optional[EpisodeMediaDownload] = (
        s.query(EpisodeMediaDownload)
        .filter(
            EpisodeMediaDownload.media_item_id == episode.id,
            EpisodeMediaDownload.local_media_profile_id == profile.id,
        )
        .one_or_none()
    )
    if existing is not None:
        _assert_no_active_attempt(s, existing)
        existing.redownload_when_final = redownload_when_final
        existing.redownload_when_delay_passed = redownload_when_delay_passed
        _reconcile_existing_artifact(s, existing)
        if existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
            raise HTTPException(status_code=409, detail=f"Episode already has a downloaded file for profile '{profile.name}'")
        prepare_media_download_artifact(s, existing)
        existing.file_path = _resolve_episode_download_path(s, profile, episode, existing)
        s.flush()
        return existing

    return create_new_episode_download(
        s,
        episode,
        profile,
        redownload_when_final=redownload_when_final,
        redownload_when_delay_passed=redownload_when_delay_passed,
    )


def create_movie_download(
    s: Session,
    movie: Movie,
    body: MediaDownloadAPICreate,
) -> MovieMediaDownload:
    """Persist a download target for an indexed movie."""
    _ensure_downloadable(movie)
    profile = _get_profile(s, body.local_media_profile_id, LocalMediaProfileType.MOVIE, movie_site_key(movie))
    # The Daily Wire's isDownloadable only says whether its own apps offer offline downloads.
    # VODLoft downloads the stream its web player uses, so a movie only needs a video.
    if not movie.has_video:
        source_name = get_source(movie.source_key).name
        raise HTTPException(status_code=422, detail=f"{source_name} has no video for this movie yet")

    existing: Optional[MovieMediaDownload] = (
        s.query(MovieMediaDownload)
        .filter(
            MovieMediaDownload.media_item_id == movie.id,
            MovieMediaDownload.local_media_profile_id == profile.id,
        )
        .one_or_none()
    )
    if existing is not None:
        _assert_no_active_attempt(s, existing)
        _reconcile_existing_artifact(s, existing)
        if existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
            raise HTTPException(status_code=409, detail=f"Movie already has a downloaded file for profile '{profile.name}'")
        prepare_media_download_artifact(s, existing)
        existing.file_path = str(resolve_movie_output_path(profile.output_template, movie=movie))
        s.flush()
        return existing

    download = MovieMediaDownload(
        type=MediaType.MOVIE.value,
        media_item_id=movie.id,
        local_media_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=str(resolve_movie_output_path(profile.output_template, movie=movie)),
    )
    s.add(download)
    s.flush()
    record_media_download_history(
        s,
        download.id,
        MediaDownloadHistoryAction.CREATED,
        metadata={
            "file_path": download.file_path,
            "local_media_profile_id": profile.id,
        },
    )
    return download


def create_movie_extra_download(
    s: Session,
    movie: Movie,
    movie_extra_slug: str,
    body: MediaDownloadAPICreate,
) -> MovieExtraMediaDownload:
    """Persist a download target for an extra of an indexed movie."""
    profile = _get_profile(s, body.local_media_profile_id, LocalMediaProfileType.MOVIE, movie_site_key(movie))
    movie_extra: Optional[MovieExtra] = (
        s.query(MovieExtra)
        .filter(MovieExtra.movie_id == movie.id, MovieExtra.slug == movie_extra_slug)
        .one_or_none()
    )
    if movie_extra is None:
        raise HTTPException(status_code=404, detail="Movie extra not found for this movie")

    existing: Optional[MovieExtraMediaDownload] = (
        s.query(MovieExtraMediaDownload)
        .filter(
            MovieExtraMediaDownload.media_item_id == movie_extra.id,
            MovieExtraMediaDownload.local_media_profile_id == profile.id,
        )
        .one_or_none()
    )
    if existing is not None:
        _assert_no_active_attempt(s, existing)
        _reconcile_existing_artifact(s, existing)
        if existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
            raise HTTPException(status_code=409, detail=f"Movie extra already has a downloaded file for profile '{profile.name}'")
        prepare_media_download_artifact(s, existing)
        existing.file_path = str(resolve_movie_output_path(profile.output_template, movie=movie, media_item=movie_extra))
        s.flush()
        return existing

    download = MovieExtraMediaDownload(
        type=MediaType.MOVIE_EXTRA.value,
        media_item_id=movie_extra.id,
        local_media_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=str(resolve_movie_output_path(profile.output_template, movie=movie, media_item=movie_extra)),
    )
    s.add(download)
    s.flush()
    record_media_download_history(
        s,
        download.id,
        MediaDownloadHistoryAction.CREATED,
        metadata={
            "file_path": download.file_path,
            "local_media_profile_id": profile.id,
        },
    )
    return download


def create_video_download(
    s: Session,
    video: Video,
    body: MediaDownloadAPICreate,
) -> VideoMediaDownload:
    """Persist a download target for a single video."""
    _ensure_downloadable(video)
    profile = _get_profile(s, body.local_media_profile_id, LocalMediaProfileType.VIDEO, video_site_key(video))
    existing: Optional[VideoMediaDownload] = (
        s.query(VideoMediaDownload)
        .filter(
            VideoMediaDownload.media_item_id == video.id,
            VideoMediaDownload.local_media_profile_id == profile.id,
        )
        .one_or_none()
    )
    if existing is not None:
        _assert_no_active_attempt(s, existing)
        _reconcile_existing_artifact(s, existing)
        if existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
            raise HTTPException(status_code=409, detail=f"Video already has a downloaded file for profile '{profile.name}'")
        prepare_media_download_artifact(s, existing)
        existing.file_path = str(resolve_video_output_path(profile.output_template, video=video))
        s.flush()
        return existing

    download = VideoMediaDownload(
        type=MediaType.VIDEO.value,
        media_item_id=video.id,
        local_media_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=str(resolve_video_output_path(profile.output_template, video=video)),
    )
    s.add(download)
    s.flush()
    record_media_download_history(
        s,
        download.id,
        MediaDownloadHistoryAction.CREATED,
        metadata={
            "file_path": download.file_path,
            "local_media_profile_id": profile.id,
        },
    )
    return download


_PROFILE_TYPE_LABELS = {
    LocalMediaProfileType.COLLECTION: "Episodes",
    LocalMediaProfileType.MOVIE: "Movies and movie extras",
    LocalMediaProfileType.VIDEO: "Videos",
}


def _get_profile(s: Session, profile_id: int, expected_type: LocalMediaProfileType, site_key: Optional[str]) -> LocalMediaProfileBase:
    profile: Optional[LocalMediaProfileBase] = s.get(LocalMediaProfileBase, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Local media profile not found")
    if profile.type != expected_type.value:
        label = _PROFILE_TYPE_LABELS[expected_type]
        raise HTTPException(status_code=422, detail=f"{label} require a {expected_type.value.title()} Local Media Profile")
    if not profile_offered_for_site(s, profile, site_key):
        raise HTTPException(status_code=422, detail=f"Local Media Profile '{profile.name}' is not available for this Site")
    return profile


def retry_media_download(s: Session, media_download_id: int) -> MediaDownloadBase:
    download: Optional[MediaDownloadBase] = s.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    _assert_no_active_attempt(s, download)
    _reconcile_existing_artifact(s, download)
    prepare_media_download_artifact(s, download)
    s.flush()
    return download


def suppress_media_download_automatic_retry(s: Session, media_download_id: int) -> MediaDownloadBase:
    """Persist the user's choice not to have a Download Profile immediately re-arm this artifact."""
    download: Optional[MediaDownloadBase] = s.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    download.automatic_retry_suppressed = True
    if download.artifact_status == MediaDownloadArtifactStatus.ABSENT.value:
        remove_download_artifacts(download.file_path, sidecar_paths=tuple(asset.path for asset in download.assets))
    s.flush()
    return download


def update_media_download(s: Session, media_download_id: int, body: MediaDownloadAPIUpdate) -> MediaDownloadAPIRead:
    item: Optional[MediaDownloadBase] = s.query(MediaDownloadBase).filter_by(id=media_download_id).one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media download not found")
    update_database_fields(item, body)
    s.flush()
    return MediaDownloadAPIRead.model_validate(item)


def set_media_download_kept(s: Session, media_download_id: int, body: MediaDownloadKeptAPIRequest) -> MediaDownloadAPIRead:
    item = s.get(EpisodeMediaDownload, media_download_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Episode download not found")
    item.kept = body.kept
    s.flush()
    return MediaDownloadAPIRead.model_validate(item)
