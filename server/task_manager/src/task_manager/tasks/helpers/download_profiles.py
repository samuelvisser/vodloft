from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import DownloadProfile
from backend.utils.episode_download_scope import EpisodeDownloadScope
from task_manager.events.transactional import queue_event


def _lock_download_profile(s: Session, profile_id: int) -> DownloadProfile | None:
    """Load one Download Profile while serializing changes to its enabled state.

    Callers run inside ``run_write_transaction``. On SQLite it already writes only from a snapshot no
    other writer changed; PostgreSQL locks the profile row, which also covers concurrent transactions.
    """
    statement = select(DownloadProfile).where(DownloadProfile.id == profile_id)
    if s.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()

    return s.scalars(
        statement.execution_options(populate_existing=True)
    ).one_or_none()


def lock_enabled_download_profile(
        s: Session,
        profile_id: int,
) -> DownloadProfile | None:
    """Lock and return a Download Profile only when it is currently enabled."""
    profile = _lock_download_profile(s, profile_id)
    if profile is None or not profile.enable_profile:
        return None
    return profile


def disable_download_profiles_for_episode_scope(
        s: Session,
        scope: EpisodeDownloadScope,
) -> int:
    """Disable enabled Download Profiles whose Local Media Profile is in ``scope``.

    The caller owns the transaction. Holding the same profile lock used by the
    Download Profile worker makes disabling and automatic reconciliation mutually
    exclusive: either an in-flight reconciliation commits first and can then be
    canceled, or the disable commits first and the worker observes it as disabled.
    """
    local_media_profile_ids = scope.local_media_profile_ids
    if not local_media_profile_ids:
        return 0

    statement = select(DownloadProfile).where(
        DownloadProfile.collection_id == scope.collection.id,
        DownloadProfile.local_media_profile_id.in_(local_media_profile_ids),
        DownloadProfile.enable_profile.is_(True),
    )
    # On SQLite the caller's write transaction already keeps a profile reconciliation out.
    if s.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()

    profiles = list(s.scalars(
        statement.execution_options(populate_existing=True)
    ))
    disabled = 0
    for profile in profiles:
        profile.enable_profile = False
        disabled += 1
        queue_event(s, "download_profile.updated", {
            "resource_id": profile.id,
            "id": profile.id,
            "collection_id": profile.collection_id,
        })

    s.flush()
    return disabled
