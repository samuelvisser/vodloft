from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, or_, select, true, update
from sqlalchemy.orm import Session

from backend.db.models import CustomIndexState, Episode, Metadata, Collection, CollectionLocalMediaProfile
from backend.db.models.media_download import EpisodeMediaDownload
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.local_media_profile_types import CollectionLocalMediaProfileScope
from backend.utils.custom_index import (
    CustomIndexNotReadyError,
    INDEX_ASSIGNMENT_PREFIX,
    get_episode_index_assignments,
    indexing_value_definition_keys,
    kept_index_keys,
    set_episode_index_assignment,
)
from jinja_analysis import (
    CustomIndexReachabilityComparison,
    CustomIndexReachabilityStatus,
    compare_custom_index_reachability,
)
from backend.utils.output_template import (
    COLLECTION_OUTPUT_TEMPLATE_FIELDS,
    COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    episode_output_template_values,
    output_template_custom_index_calls,
    output_template_custom_index_keys,
    prepare_output_template,
    resolve_episode_output_path_with_index_values,
)
from backend.utils.output_template_jinja import create_output_template_environment
from task_manager.scheduler.operations import (
    OperationTargetSpec, create_operation, queue_operation_target_dispatch,
)
from task_manager.scheduler.types import OperationSource
from task_manager.scheduler.types import OperationStatus
from task_manager.scheduler.db import TaskOperation, TaskOperationTarget


@dataclass(frozen=True)
class CustomIndexReconciliationResult:
    collection_id: int
    local_media_profile_id: int
    episodes_considered: int
    assignments_changed: int
    synced_episode_ids: tuple[int, ...]
    superseded: bool = False
    synced_source_paths: tuple[tuple[int, str], ...] = ()


def profile_applies_to_collection(profile: CollectionLocalMediaProfile, collection: Collection) -> bool:
    return profile.collection_scope == CollectionLocalMediaProfileScope.BOTH or profile.collection_scope == collection.type


def profile_collection_scope_filter_for_collection_type(collection_type: str):
    """SQL predicate for Collection Local Media Profiles that apply to one collection type."""
    return or_(
        CollectionLocalMediaProfile.collection_scope == CollectionLocalMediaProfileScope.BOTH,
        CollectionLocalMediaProfile.collection_scope == collection_type,
    )


def profile_collection_scope_filter(profile: CollectionLocalMediaProfile):
    """SQL predicate for Collections that are in one Local Media Profile's scope."""
    if profile.collection_scope == CollectionLocalMediaProfileScope.BOTH:
        return true()
    return Collection.type == profile.collection_scope


def profile_uses_custom_indexes(profile: CollectionLocalMediaProfile) -> bool:
    return bool(
        output_template_custom_index_keys(profile.output_template)
        & indexing_value_definition_keys(profile)
    )


def compare_custom_index_assignments(
    previous_template: str,
    current_template: str,
    *,
    previous_definition_keys: frozenset[str],
    current_definition_keys: frozenset[str],
    previous_kept_keys: frozenset[str] = frozenset(),
    current_kept_keys: frozenset[str] = frozenset(),
) -> CustomIndexReachabilityComparison:
    """Compare whole-profile Custom Index assignment semantics across a save.

    Definition membership is part of assignment semantics: adding or removing an
    active key necessarily changes persisted assignments. When the active key
    set is unchanged, delegate branch/reachability equivalence to the shared
    Jinja analyzer. UNKNOWN remains a conservative "might have changed" result.
    """
    previous_active = (
        output_template_custom_index_keys(previous_template)
        & previous_definition_keys
    )
    current_active = (
        output_template_custom_index_keys(current_template)
        & current_definition_keys
    )
    if previous_active != current_active:
        return CustomIndexReachabilityComparison(
            CustomIndexReachabilityStatus.CHANGED,
            reason="The set of active Custom Index keys changed",
        )
    if previous_kept_keys & previous_active != current_kept_keys & current_active:
        return CustomIndexReachabilityComparison(
            CustomIndexReachabilityStatus.CHANGED,
            reason="A Custom Index started or stopped keeping its numbers",
        )
    if not current_active or previous_template == current_template:
        return CustomIndexReachabilityComparison(
            CustomIndexReachabilityStatus.UNCHANGED,
        )
    previous_calls = output_template_custom_index_calls(previous_template)
    current_calls = output_template_custom_index_calls(current_template)
    for key in sorted(current_active):
        if previous_calls.get(key) != current_calls.get(key):
            # start= and step= only change how a number reads; per= changes the numbers.
            return CustomIndexReachabilityComparison(
                CustomIndexReachabilityStatus.CHANGED,
                reason=f"Custom Index '{key}' is grouped differently",
            )

    return compare_custom_index_reachability(
        previous_template,
        current_template,
        environment=create_output_template_environment(),
        keys=current_active,
    )


def request_custom_index_reconciliation(
    session: Session, *, collection_id: int, local_media_profile_id: int,
    dispatch: bool = True,
) -> CustomIndexState:
    """Invalidate a pair in the transaction that changes its inputs."""
    state = session.scalar(select(CustomIndexState).where(
        CustomIndexState.collection_id == collection_id,
        CustomIndexState.local_media_profile_id == local_media_profile_id,
    ))
    if state is None:
        state = CustomIndexState(collection_id=collection_id, local_media_profile_id=local_media_profile_id)
        session.add(state)
        session.flush()
    else:
        session.execute(update(CustomIndexState).where(CustomIndexState.id == state.id).values(
            requested_generation=CustomIndexState.requested_generation + 1,
        ))
        session.refresh(state)
    if dispatch:
        dispatch_custom_index_reconciliation(
            session, collection_id=collection_id, local_media_profile_id=local_media_profile_id,
        )
    return state


def dispatch_custom_index_reconciliation(
    session: Session, *, collection_id: int, local_media_profile_id: int,
) -> None:
    active = session.scalar(select(TaskOperationTarget.id).join(
        TaskOperation, TaskOperation.id == TaskOperationTarget.operation_id,
    ).where(
        TaskOperation.kind == "local_media_profile.manage_custom_indexes",
        TaskOperation.resource_id == local_media_profile_id,
        TaskOperationTarget.resource_type == "collection",
        TaskOperationTarget.resource_id == collection_id,
        TaskOperation.status.in_((
            OperationStatus.QUEUED, OperationStatus.RUNNING,
            OperationStatus.WAITING,
        )),
    ).limit(1))
    if active is not None:
        return
    target = OperationTargetSpec(
            task_key="manage_custom_indexes", resource_type="collection", resource_id=collection_id,
            task_kwargs={"local_media_profile_id": local_media_profile_id},
            slot_key=f"collection:{collection_id}:profile:{local_media_profile_id}",
    )
    operation = create_operation(
            session, kind="local_media_profile.manage_custom_indexes",
            source=OperationSource.SYSTEM,
            resource_type="local_media_profile", resource_id=local_media_profile_id,
            title="Manage custom indexes", targets=[target],
    )
    queue_operation_target_dispatch(session, operation.id, target.resolved_slot_key())


def request_collection_custom_index_reconciliation(session: Session, collection_id: int) -> None:
    collection = session.get(Collection, collection_id)
    if collection is None:
        return

    existing_profile_ids = set(session.scalars(
        select(CustomIndexState.local_media_profile_id).where(
            CustomIndexState.collection_id == collection_id,
        )
    ))
    profile_stmt = (
        select(CollectionLocalMediaProfile)
        .where(or_(
            CollectionLocalMediaProfile.id.in_(existing_profile_ids),
            profile_collection_scope_filter_for_collection_type(collection.type),
        ))
        .order_by(CollectionLocalMediaProfile.id)
    )
    for profile in session.scalars(profile_stmt):
        if profile.id in existing_profile_ids or profile_uses_custom_indexes(profile):
            request_custom_index_reconciliation(
                session, collection_id=collection_id, local_media_profile_id=profile.id,
            )


def ensure_episode_custom_indexes_ready(
    session: Session, *, episode: Episode, profile: CollectionLocalMediaProfile,
) -> None:
    if not profile_uses_custom_indexes(profile):
        return
    state = session.scalar(select(CustomIndexState).where(
        CustomIndexState.collection_id == episode.collection_id,
        CustomIndexState.local_media_profile_id == profile.id,
    ))
    if state is None:
        raise CustomIndexNotReadyError(
            "Custom indexes have not been reconciled",
            repair_collection_id=episode.collection_id, repair_profile_id=profile.id,
        )
    if state.completed_generation != state.requested_generation:
        raise CustomIndexNotReadyError("Waiting for Manage Custom Indexes to complete")


def simulate_episode_indexes(
    episodes: list[Episode], *, template: str, definitions: frozenset[str],
    values_overrides: dict[int, dict[str, str]] | None = None,
    kept: dict[int, dict[str, int]] | None = None,
    keep_keys: frozenset[str] = frozenset(),
) -> dict[int, dict[str, int]]:
    """Evaluate Jinja branches in canonical order without persisting anything.

    Each key counts once per group (its per= value). A key in ``keep_keys``
    keeps the numbers in ``kept`` for the episodes that still reach it; an
    episode it has not numbered yet takes the next number after the highest
    one its group already holds.
    """
    prepared = prepare_output_template(
        template,
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    )
    ordered = sorted(episodes, key=lambda item: (item.index, item.id))
    kept = kept or {}

    def values_for(episode: Episode) -> dict[str, object]:
        return (values_overrides or {}).get(episode.id) or episode_output_template_values(episode)

    def kept_number(episode: Episode, key: str) -> int | None:
        return kept.get(episode.id, {}).get(key) if key in keep_keys else None

    counters: dict[tuple[str, object], int] = defaultdict(int)
    if keep_keys and kept:
        # First pass: learn which group each kept number sits in, so new
        # numbers start after the highest kept number of their own group.
        for episode in ordered:
            def seed(key: str, group: object, episode=episode) -> object:
                if key not in definitions:
                    return ""
                number = kept_number(episode, key)
                if number is None:
                    return 1
                counters[(key, group)] = max(counters[(key, group)], number)
                return number

            prepared.render(values_for(episode), custom_index_resolver=seed)

    desired: dict[int, dict[str, int]] = {}
    for episode in ordered:
        selected: dict[str, int] = {}

        def resolve(key: str, group: object, episode=episode) -> object:
            if key not in definitions:
                return ""
            if key not in selected:
                number = kept_number(episode, key)
                if number is None:
                    counters[(key, group)] += 1
                    number = counters[(key, group)]
                selected[key] = number
            return selected[key]

        prepared.render(values_for(episode), custom_index_resolver=resolve)
        desired[episode.id] = selected
    return desired


def _synced_downloads_before_reindex(
    session: Session, profile: CollectionLocalMediaProfile, episodes: list[Episode],
) -> dict[int, str]:
    """Only previously synchronized physical paths qualify for an automatic move."""
    episode_by_id = {episode.id: episode for episode in episodes}
    if not episode_by_id:
        return {}
    downloads = session.scalars(select(EpisodeMediaDownload).where(
        EpisodeMediaDownload.media_item_id.in_(episode_by_id),
        EpisodeMediaDownload.local_media_profile_id == profile.id,
        EpisodeMediaDownload.artifact_status.in_((
            MediaDownloadArtifactStatus.AVAILABLE,
            MediaDownloadArtifactStatus.CORRUPTED,
        )),
    ))
    synced: dict[int, str] = {}
    definitions = indexing_value_definition_keys(profile)
    for download in downloads:
        episode = episode_by_id[download.media_item_id]
        source = Path(download.file_path)
        if not source.suffix or not source.is_file():
            continue
        try:
            old_path = resolve_episode_output_path_with_index_values(
                profile.output_template, episode=episode, index_definitions=definitions,
                index_values=get_episode_index_assignments(episode, profile.id),
                extension=source.suffix.removeprefix("."),
            )
        except (CustomIndexNotReadyError, ValueError):
            continue
        if source == old_path:
            synced[episode.id] = str(source)
    return synced


def reconcile_collection_profile_custom_indexes(
    session: Session, *, collection_id: int, local_media_profile_id: int,
    auto_rename: bool = True,
) -> CustomIndexReconciliationResult:
    state = session.scalar(select(CustomIndexState).where(
        CustomIndexState.collection_id == collection_id,
        CustomIndexState.local_media_profile_id == local_media_profile_id,
    ))
    profile = session.get(CollectionLocalMediaProfile, local_media_profile_id)
    collection = session.get(Collection, collection_id)
    empty = CustomIndexReconciliationResult(collection_id, local_media_profile_id, 0, 0, ())
    if state is None or profile is None or collection is None:
        return empty

    generation = state.requested_generation
    episodes = list(session.scalars(select(Episode).where(Episode.collection_id == collection_id)
        .order_by(Episode.index.asc(), Episode.id.asc())))
    applicable = profile_applies_to_collection(profile, collection)
    old = {ep.id: get_episode_index_assignments(ep, profile.id) for ep in episodes}
    desired = simulate_episode_indexes(
        episodes, template=profile.output_template,
        definitions=indexing_value_definition_keys(profile),
        kept=old, keep_keys=kept_index_keys(profile),
    ) if applicable and profile_uses_custom_indexes(profile) else {ep.id: {} for ep in episodes}
    synced = _synced_downloads_before_reindex(session, profile, episodes) if auto_rename and applicable else {}

    # Compare-and-swap and metadata edits belong to the same transaction.
    updated = session.execute(update(CustomIndexState).where(
        CustomIndexState.id == state.id,
        CustomIndexState.requested_generation == generation,
    ).values(completed_generation=generation)).rowcount
    if not updated:
        return CustomIndexReconciliationResult(collection_id, local_media_profile_id, len(episodes), 0, (), True)

    changed = 0
    synced_episode_ids: list[int] = []
    for episode in episodes:
        before, after = old[episode.id], desired[episode.id]
        raw_count = sum(
            item.key.startswith(f"{INDEX_ASSIGNMENT_PREFIX}{profile.id}.")
            for item in episode.meta_items
        )
        if before == after and raw_count == len(after):
            continue
        changed += max(1, len(set(before.items()) ^ set(after.items())))
        prefix = f"{INDEX_ASSIGNMENT_PREFIX}{profile.id}."
        seen: set[str] = set()
        for item in list(episode.meta_items):
            if not item.key.startswith(prefix):
                continue
            key = item.key[len(prefix):]
            if key not in after or key in seen:
                episode.meta_items.remove(item)
                continue
            seen.add(key)
            if item.value != str(after[key]):
                item.value = str(after[key])
        for key, value in after.items():
            if key not in seen:
                set_episode_index_assignment(episode, profile.id, key, value)
        if episode.id in synced:
            synced_episode_ids.append(episode.id)
    session.flush()
    return CustomIndexReconciliationResult(
        collection_id, local_media_profile_id, len(episodes), changed, tuple(synced_episode_ids),
        synced_source_paths=tuple((id_, synced[id_]) for id_ in synced_episode_ids),
    )


def remove_profile_custom_index_state(session: Session, *, local_media_profile_id: int) -> None:
    prefix = f"{INDEX_ASSIGNMENT_PREFIX}{local_media_profile_id}."
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    session.execute(delete(Metadata).where(
        Metadata.parent_table == Episode.__tablename__,
        Metadata.key.like(f"{escaped}%", escape="\\"),
    ))
    session.execute(delete(CustomIndexState).where(
        CustomIndexState.local_media_profile_id == local_media_profile_id,
    ))
    session.flush()
