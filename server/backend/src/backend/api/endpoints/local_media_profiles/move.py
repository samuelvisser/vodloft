from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.api.models.local_media_profile_move import (
    LocalMediaProfileMoveAPIRequest,
    LocalMediaProfileMovePreviewAPIRead,
)
from backend.db.models import CollectionLocalMediaProfile
from backend.services.profile_moves import ProfileMoveError, plan_profile_move
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import queue_operation_target_dispatch

from .operations import LocalMediaProfileMoveEpisodesOperation


def _collection_profile(s: Session, slug: str) -> CollectionLocalMediaProfile:
    profile = s.query(CollectionLocalMediaProfile).filter_by(slug=slug).one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Collection Local Media Profile not found")
    return profile


def get_move_preview(s: Session, source_slug: str, target_slug: str) -> LocalMediaProfileMovePreviewAPIRead:
    source = _collection_profile(s, source_slug)
    target = _collection_profile(s, target_slug)
    try:
        plans = plan_profile_move(s, source, target)
    except ProfileMoveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LocalMediaProfileMovePreviewAPIRead.model_validate({"target": target, "collections": plans})


def request_move(s: Session, source_slug: str, request: LocalMediaProfileMoveAPIRequest) -> dict[str, bool | int | str]:
    source = _collection_profile(s, source_slug)
    target = _collection_profile(s, request.target_slug)
    chosen = {collection.collection_id: collection.move_download_profile for collection in request.collections}
    try:
        plans = {plan.collection.id: plan for plan in plan_profile_move(s, source, target, collection_ids=chosen)}
    except ProfileMoveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    collections: list[tuple[int, bool, list[int]]] = []
    episodes = paused = 0
    for collection_id, move_download_profile in chosen.items():
        plan = plans.get(collection_id)
        if plan is None:
            raise HTTPException(status_code=422, detail=f"{source.name} has no episodes of Collection {collection_id} to move")
        if not plan.in_scope:
            raise HTTPException(status_code=422, detail=f"{target.name} is not offered for {plan.collection.title}")
        if plan.blocked:
            raise HTTPException(
                status_code=422,
                detail=f"Several episodes of {plan.collection.title} would get the same path in {target.name}",
            )
        moving = sum(item.outcome.moves for item in plan.episodes)
        if not moving:
            continue
        # Keep both sides' Download Profiles from downloading this Collection while its files move.
        held = []
        for profile in (*plan.source_download_profiles, *plan.target_download_profiles):
            if profile.enable_profile:
                profile.enable_profile = False
                held.append(profile.id)
        paused += len(held)
        episodes += moving
        collections.append((collection_id, move_download_profile and plan.can_move_download_profile, held))

    if not collections:
        raise HTTPException(status_code=422, detail="None of the chosen episodes can be moved")

    operation = create_operation(
        s,
        LocalMediaProfileMoveEpisodesOperation(
            source, target=target, collections=collections, episodes_requested=episodes,
        ),
    )
    for collection_id, _, _ in collections:
        queue_operation_target_dispatch(s, operation.id, f"collection:{collection_id}")
    s.flush()
    return {
        "queued": True,
        "operation_id": operation.id,
        "episodes_queued": episodes,
        "collections_queued": len(collections),
        "download_profiles_paused": paused,
    }
