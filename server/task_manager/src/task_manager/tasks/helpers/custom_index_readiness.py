from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from time import monotonic

from sqlalchemy import select

from backend.db.models import CustomIndexState, CollectionLocalMediaProfile
from backend.services.custom_indexes import (
    profile_uses_custom_indexes, request_custom_index_reconciliation,
)
from backend.utils.custom_index import CustomIndexNotReadyError
from backend.utils.file_locks import async_file_lock, lock_file_path
from controller.db_utils import db_session


@asynccontextmanager
async def custom_index_pair_lock(
    collection_id: int,
    local_media_profile_id: int,
    *,
    shared: bool = False,
):
    """Coordinate filesystem/index work for one Collection/Profile pair across workers.

    Maintenance jobs take the default exclusive lock because they mutate index
    assignments or move existing files. Downloads only need a stable generation
    while they resolve and publish their own artifact, so they take a shared lock.
    That keeps maintenance out while still allowing separate downloads for the
    same Collection/Profile pair to use the configured global concurrency.
    """
    async with async_file_lock(lock_file_path("indexes", f"{collection_id}-{local_media_profile_id}"), shared=shared):
        yield


def pair_is_ready(collection_id: int, local_media_profile_id: int) -> bool:
    with db_session() as session:
        profile = session.get(CollectionLocalMediaProfile, local_media_profile_id)
        if profile is None or not profile_uses_custom_indexes(profile):
            return True
        state = session.scalar(select(CustomIndexState).where(
            CustomIndexState.collection_id == collection_id,
            CustomIndexState.local_media_profile_id == local_media_profile_id,
        ))
        return state is not None and state.completed_generation == state.requested_generation


def request_missing_index_repair(error: CustomIndexNotReadyError) -> None:
    if error.repair_collection_id is None or error.repair_profile_id is None:
        return
    with db_session() as session:
        request_custom_index_reconciliation(
            session, collection_id=error.repair_collection_id,
            local_media_profile_id=error.repair_profile_id,
        )
        session.commit()


async def wait_for_custom_index_pair(
    collection_id: int, local_media_profile_id: int, *, timeout: float = 180, progress=None,
) -> None:
    """Wait outside the caller's write transaction for the latest generation."""
    waiting = False
    try:
        deadline = monotonic() + timeout
        while True:
            if progress is not None and hasattr(progress, "raise_if_canceled"):
                progress.raise_if_canceled()
            with db_session() as session:
                profile = session.get(CollectionLocalMediaProfile, local_media_profile_id)
                if profile is None or not profile_uses_custom_indexes(profile):
                    return
                state = session.scalar(select(CustomIndexState).where(
                    CustomIndexState.collection_id == collection_id,
                    CustomIndexState.local_media_profile_id == local_media_profile_id,
                ))
                if state is None:
                    request_custom_index_reconciliation(
                        session, collection_id=collection_id,
                        local_media_profile_id=local_media_profile_id,
                    )
                    session.commit()
                elif state.completed_generation == state.requested_generation:
                    return
            if monotonic() >= deadline:
                raise CustomIndexNotReadyError(
                    f"Manage Custom Indexes did not finish for Collection {collection_id}, "
                    f"Local Media Profile {local_media_profile_id}"
                )
            if progress is not None and hasattr(progress, "set_wait_state") and not waiting:
                progress.set_wait_state("custom_indexes", "Waiting for Custom Index assignments")
                waiting = True
            await asyncio.sleep(0.5)
    finally:
        if waiting and progress is not None:
            progress.set_wait_state(None)
