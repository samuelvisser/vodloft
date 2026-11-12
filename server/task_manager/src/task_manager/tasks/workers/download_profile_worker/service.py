from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from backend.db.models import DownloadProfile, Episode
from backend.db.core import run_write_transaction
from backend.db.models.media_download import MediaDownloadBase
from backend.services.episode_download_delay import episode_download_delay_ready_at
from backend.services.episode_filters import has_latest_count
from task_manager.scheduler.types import OperationSource
from task_manager.tasks.helpers.download_profiles import lock_enabled_download_profile
from task_manager.tasks.helpers.custom_index_readiness import wait_for_custom_index_pair
from task_manager.tasks.helpers.progress import update_progress
from task_manager.tasks.media_download_operations import (
    create_media_download_operation,
    dispatch_queued_media_download_operations,
    set_media_download_operation_not_before,
)

from ._helpers import (
    cleanup_older_episodes,
    ensure_episode_download,
    episodes_with_nothing_to_do,
    get_download_profile_episodes,
    resolve_target_profiles,
)


async def run_download_profile_worker(
        s: Session, *, resource_id: Optional[int] = None, resource_type: Optional[str] = None, progress=None
) -> None:
    """Reconcile Download Profile domain state and create SYSTEM download operations.

    Each profile reconciliation owns a lock on that Download Profile until its
    operation rows are committed. A concurrent profile disable therefore cannot
    interleave with a stale in-memory profile and recreate downloads after the
    disable has taken effect.
    """
    print("Starting download_profile_worker" + (f" ({resource_type}={resource_id})" if resource_type else ""))

    profiles = resolve_target_profiles(s, resource_type=resource_type, resource_id=resource_id)
    profile_ids = tuple(profile.id for profile in profiles)

    # Profile discovery is advisory only. End that read transaction before taking
    # the per-profile reconciliation lock so the enabled state is re-read fresh.
    s.rollback()

    if not profile_ids:
        # A final-publication event must also release manual bulk downloads
        # waiting for a countdown, even when this collection has no Download Profiles.
        run_write_transaction(dispatch_queued_media_download_operations)
        update_progress(progress, 100, "No enabled download profile in scope")
        print("download_profile_worker completed: nothing to do")
        return

    only_episode_id = resource_id if resource_type == "episode" and resource_id is not None else None
    created = 0
    total = len(profile_ids)

    for index, profile_id in enumerate(profile_ids):
        pending_profile = s.get(DownloadProfile, profile_id)
        pair = (pending_profile.collection_id, pending_profile.local_media_profile_id) if pending_profile is not None else None
        s.rollback()
        if pair is not None:
            await wait_for_custom_index_pair(*pair)
        made = _reconcile_profile(s, profile_id, only_episode_id)
        if made is None:
            update_progress(progress, 100, f"Episode {only_episode_id} no longer exists")
            return
        created += made
        update_progress(
            progress,
            int((index + 1) / total * 90),
            f"Prepared {created} download operation(s) ({index + 1}/{total} profile(s) checked)",
        )

    dispatched = run_write_transaction(dispatch_queued_media_download_operations)

    message = f"Prepared {created} download operation(s)"
    if dispatched:
        message += f"; started {dispatched} queued download(s)"
    update_progress(progress, 100, message)
    print(f"download_profile_worker completed: {message}")


# How many episodes one write transaction reconciles. A show can have thousands of episodes, and
# SQLite has one writer: reconciling them all at once would hold up every other write for minutes.
EPISODES_PER_TRANSACTION = 50


def _profile_version(profile: DownloadProfile) -> tuple:
    """What decides which episodes a profile wants, to notice a change between transactions."""
    return (
        profile.collection_id,
        profile.local_media_profile_id,
        profile.download_with_countdown,
        profile.redownload_final,
        tuple(
            tuple(getattr(item, column.key) for column in inspect(item).mapper.column_attrs)
            for item in profile.filters
        ),
    )


def _reconcile_profile(s: Session, profile_id: int, only_episode_id: Optional[int]) -> Optional[int]:
    """Create the download operations one enabled profile needs; None when the only episode is gone.

    Which episodes the profile wants is read first, then reconciled a batch at a time, each batch in
    its own write transaction that holds the profile lock until it commits. A concurrent disable can
    therefore only proceed after every operation of a batch is durable, and a batch that finds the
    profile disabled or changed stops: the change starts its own reconciliation.
    """
    profile = s.get(DownloadProfile, profile_id)
    if profile is None or not profile.enable_profile:
        s.rollback()
        return 0
    only_episode: Optional[Episode] = None
    if only_episode_id is not None:
        only_episode = s.get(Episode, only_episode_id)
        if only_episode is None:
            s.rollback()
            return None
    version = _profile_version(profile)
    # A new episode can push an older one out of "the latest N".
    cleanup = only_episode_id is None or has_latest_count(profile.filters)
    episodes = get_download_profile_episodes(s, profile, only_episode=only_episode)
    settled = episodes_with_nothing_to_do(s, profile, episodes)
    episode_ids = [
        episode.id
        for episode in episodes
        if episode.id not in settled and not episode.download_dismissed(profile.local_media_profile_id)
    ]
    s.rollback()

    created = 0
    for start in range(0, len(episode_ids), EPISODES_PER_TRANSACTION):
        batch = episode_ids[start:start + EPISODES_PER_TRANSACTION]
        made = run_write_transaction(lambda w: _reconcile_episodes(w, profile_id, version, batch))
        if made is None:
            return created
        created += made

    if cleanup:
        run_write_transaction(lambda w: _cleanup_older_episodes(w, profile_id, version))
    return created


def _locked_profile(s: Session, profile_id: int, version: tuple) -> Optional[DownloadProfile]:
    """The profile, locked, when it is still enabled and wants what it wanted when the run read it."""
    profile = lock_enabled_download_profile(s, profile_id)
    if profile is None or _profile_version(profile) != version:
        return None
    return profile


def _reconcile_episodes(s: Session, profile_id: int, version: tuple, episode_ids: list[int]) -> Optional[int]:
    """Create the download operations one batch of a profile's wanted episodes needs.

    None when the profile was disabled or changed since its episodes were read.
    """
    profile = _locked_profile(s, profile_id, version)
    if profile is None:
        return None
    episodes = {episode.id: episode for episode in s.scalars(select(Episode).where(Episode.id.in_(episode_ids)))}

    created = 0
    for episode_id in episode_ids:
        episode = episodes.get(episode_id)
        if episode is None or episode.download_dismissed(profile.local_media_profile_id):
            continue
        ready_at = episode_download_delay_ready_at(episode)
        delayed = (
            ready_at is not None
            and ready_at > datetime.now(timezone.utc)
        )
        action = ensure_episode_download(
            s,
            profile,
            episode,
            defer_artifact_preparation=delayed,
        )

        if not action.needs_operation:
            set_media_download_operation_not_before(
                s,
                action.media_download_id,
                ready_at if delayed else None,
            )
            continue

        download = s.get(MediaDownloadBase, action.media_download_id)
        if download is None:
            continue
        create_media_download_operation(
            s,
            download,
            source=OperationSource.SYSTEM.value,
            is_redownload=action.is_redownload,
            prepare_existing_artifact=action.prepare_existing_artifact,
            not_before=ready_at if delayed else None,
        )
        created += 1
    return created


def _cleanup_older_episodes(s: Session, profile_id: int, version: tuple) -> int:
    profile = _locked_profile(s, profile_id, version)
    return cleanup_older_episodes(s, profile) if profile is not None else 0
