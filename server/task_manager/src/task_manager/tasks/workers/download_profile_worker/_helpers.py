from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Sequence, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.db.models import DownloadProfile, Episode, LocalMediaProfileBase
from backend.db.models.media_download import EpisodeMediaDownload
from backend.types.download_profile_types import MediaDownloadArtifactStatus, RetentionFrom
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from backend.types.episode_types import EpisodePublishStatus
from backend.services.episode_rules import kept_by_rule
from backend.services.notifications.emitters import episode_deleted
from backend.services.which_episodes import EpisodeSelection, _utc_now, episodes_in_window, wanted_episodes
from backend.types.media_types import MediaType
from backend.services.media_download_history import record_media_download_history
from backend.utils.output_template import resolve_episode_output_path
from task_manager.tasks.media_download_operations import (
    dispatch_queued_media_download_operations,
    get_active_media_download_operation,
    prepare_media_download_artifact,
    remaining_media_download_budget,
)
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


def _download_profile_stmt():
    """Load profiles with the collection and seasons their episode filters need."""
    return select(DownloadProfile).options(
        joinedload(DownloadProfile.collection),
        selectinload(DownloadProfile.seasons),
        selectinload(DownloadProfile.rules),
    )


def resolve_target_profiles(
        s: Session, *, resource_type: Optional[str], resource_id: Optional[int]
) -> Sequence[DownloadProfile]:
    """Resolve which enabled Download Profiles a worker run should act on."""
    if resource_type == "episode":
        episode = s.get(Episode, resource_id) if resource_id is not None else None
        if episode is None:
            return []
        return _enabled_profiles_for_collection(s, episode.collection_id)

    if resource_type == "collection":
        if resource_id is None:
            return []
        return _enabled_profiles_for_collection(s, resource_id)

    if resource_type == "download_profile" and resource_id:
        profile = s.scalars(
            _download_profile_stmt().where(DownloadProfile.id == resource_id)
        ).one_or_none()
        if profile is None or not profile.enable_profile:
            return []
        return [profile]

    return list(s.scalars(
        _download_profile_stmt().where(DownloadProfile.enable_profile.is_(True))
    ))


def _enabled_profiles_for_collection(s: Session, collection_id: int) -> Sequence[DownloadProfile]:
    return list(s.scalars(
        _download_profile_stmt().where(
            DownloadProfile.collection_id == collection_id,
            DownloadProfile.enable_profile.is_(True),
        )
    ))


def get_download_profile_episodes(
        s: Session,
        profile: DownloadProfile,
        *,
        only_episode: Optional[Episode] = None,
) -> list[Episode]:
    """Episodes a Download Profile currently wants represented by artifacts."""
    return wanted_episodes(
        s,
        EpisodeSelection.of_profile(profile),
        only_episode_id=only_episode.id if only_episode is not None else None,
    )


@dataclass(frozen=True)
class DownloadAction:
    """Whether one persistent MediaDownload needs a new media.download operation."""

    media_download_id: int
    needs_operation: bool
    is_redownload: bool = False
    prepare_existing_artifact: bool | None = None

    @property
    def needs_trigger(self) -> bool:
        """Compatibility name for callers while execution is operation-backed."""
        return self.needs_operation


def ensure_episode_download(
        s: Session,
        profile: DownloadProfile,
        episode: Episode,
        *,
        defer_artifact_preparation: bool = False,
) -> DownloadAction:
    """Reconcile one desired episode artifact without encoding worker state on it."""
    local_media_profile = cast(LocalMediaProfileBase, profile.local_media_profile)
    local_media_profile_id = cast(int, profile.local_media_profile_id)
    existing: Optional[EpisodeMediaDownload] = (
        s.query(EpisodeMediaDownload)
        .filter(
            EpisodeMediaDownload.media_item_id == episode.id,
            EpisodeMediaDownload.local_media_profile_id == profile.local_media_profile_id,
        )
        .one_or_none()
    )
    redownload_when_final = (
        profile.download_with_countdown
        and profile.redownload_final
        and episode.publish_status == EpisodePublishStatus.PUBLISHED_WITH_COUNTDOWN
    )

    if existing is None:
        download = EpisodeMediaDownload(
            type=MediaType.EPISODE.value,
            media_item_id=episode.id,
            local_media_profile_id=local_media_profile_id,
            download_profile_id=profile.id,
            artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
            file_path="",
            redownload_when_final=redownload_when_final,
        )
        s.add(download)
        s.flush()
        download.file_path = str(resolve_episode_output_path(
            local_media_profile.output_template,
            episode=episode,
            local_media_profile=local_media_profile,
            media_download=download,
        ))
        s.flush()
        record_media_download_history(
            s,
            download.id,
            MediaDownloadHistoryAction.CREATED,
            metadata={
                "file_path": download.file_path,
                "local_media_profile_id": local_media_profile_id,
                "download_profile_id": profile.id,
            },
        )
        return DownloadAction(download.id, True)

    if redownload_when_final and not existing.automatic_retry_suppressed:
        existing.redownload_when_final = True

    target_path = str(resolve_episode_output_path(
        local_media_profile.output_template,
        episode=episode,
        local_media_profile=local_media_profile,
        media_download=existing,
    ))

    if get_active_media_download_operation(s, existing.id) is not None:
        if existing.download_profile_id != profile.id:
            existing.download_profile_id = profile.id
        s.flush()
        return DownloadAction(existing.id, False)

    if existing.artifact_status != MediaDownloadArtifactStatus.ABSENT.value:
        resolve_media_download_file(s, existing)

    if existing.download_profile_id != profile.id:
        existing.download_profile_id = profile.id

    if existing.automatic_retry_suppressed:
        s.flush()
        return DownloadAction(existing.id, False)

    if existing.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value:
        s.flush()
        return DownloadAction(existing.id, False)

    if defer_artifact_preparation:
        needs_preparation = (
            existing.artifact_status != MediaDownloadArtifactStatus.ABSENT.value
        )
        s.flush()
        return DownloadAction(
            existing.id,
            True,
            prepare_existing_artifact=needs_preparation,
        )

    prepare_media_download_artifact(s, existing)
    existing.file_path = target_path
    s.flush()
    return DownloadAction(existing.id, True)


def remaining_download_budget(s: Session) -> int:
    """Compatibility wrapper: concurrency is now calculated from active TaskRuns."""
    return remaining_media_download_budget(s)


def trigger_next_pending_downloads(s: Session, *, budget: Optional[int] = None) -> int:
    """Compatibility wrapper: pending downloads are durable queued operations."""
    return dispatch_queued_media_download_operations(s, budget=budget)


def cleanup_older_episodes(s: Session, profile: DownloadProfile) -> int:
    """Remove downloads that have fallen outside a profile's retention limit.

    Changing your own rules later never deletes anything: an episode a rule now
    leaves out keeps its download. Downloads kept by hand or by a Keep rule are
    never removed.
    """
    selection = EpisodeSelection.of_profile(profile)
    if profile.download_episode_count > 0:
        in_window_ids = {episode.id for episode in episodes_in_window(s, selection)}
        stmt = select(EpisodeMediaDownload).where(
            EpisodeMediaDownload.download_profile_id == profile.id,
        )
        if in_window_ids:
            stmt = stmt.where(EpisodeMediaDownload.media_item_id.notin_(in_window_ids))
        if not profile.delete_older_episodes:
            stmt = stmt.where(
                EpisodeMediaDownload.artifact_status
                == MediaDownloadArtifactStatus.ABSENT.value
            )
    elif profile.download_days_in_past > 0:
        if not profile.delete_older_episodes:
            return 0
        cutoff = _utc_now() - timedelta(days=profile.download_days_in_past)
        stmt = (
            select(EpisodeMediaDownload)
            .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
            .where(EpisodeMediaDownload.download_profile_id == profile.id)
        )
        if profile.retention_from == RetentionFrom.DOWNLOADED:
            stmt = stmt.where(
                EpisodeMediaDownload.downloaded_at.is_not(None),
                EpisodeMediaDownload.downloaded_at < cutoff,
            )
        else:
            stmt = stmt.where(
                Episode.published_date.is_not(None),
                Episode.published_date < cutoff,
            )
    else:
        return 0

    rows = [
        row
        for row in s.scalars(stmt.where(EpisodeMediaDownload.kept.is_(False)))
        if not (profile.rules and kept_by_rule(profile.rules, row.media))
    ]
    for row in rows:
        if profile.delete_older_episodes:
            had_file = row.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value
            path = row.file_path
            prepare_media_download_artifact(s, row)
            if had_file:
                episode_deleted(s, row.media, path=path, reason="It fell outside its Download Profile's limit.")

        # Retention cleanup is the end of this managed download's lifetime.
        s.delete(row)

    if rows:
        s.flush()
    return len(rows)
