from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Season
from backend.services.episode_filters import add_upcoming_season
from backend.types.season_types import SeasonOrigin, SeasonType
from backend.types.collection_contracts import collection_contract
from backend.utils.season_ordering import season_type_from_name
from task_manager.events.transactional import queue_event


def collection_indexed(s: Session, collection_id: int) -> bool:
    """Whether the collection's first index finished. The seasons it found are the collection's from the start, and
    only a season found after it is a new one."""
    from task_manager.scheduler.db import TaskOperation
    from task_manager.scheduler.types import OperationStatus

    return s.scalar(select(TaskOperation.id).where(
        TaskOperation.kind == "collection.index", TaskOperation.resource_type == "collection",
        TaskOperation.resource_id == collection_id,
        TaskOperation.status.in_((OperationStatus.SUCCEEDED.value, OperationStatus.PARTIAL.value)),
    ).limit(1)) is not None


def create_season_record(
    s: Session,
    *,
    collection_id: int,
    index: int,
    slug: str,
    name: str,
    origin: SeasonOrigin,
    update_collection_profiles: bool = False,
    season_number: int | None = None,
) -> Season:
    """Create one persistent season without depending on an API request model.

    Without ``season_number`` a normal season is numbered after the collection's last one.
    """
    season_type = season_type_from_name(name)
    if season_type is SeasonType.EXTRA:
        season_number = 0
    elif season_number is None:
        season_number = max(
            (
                existing.season_number
                for existing in s.query(Season).filter(Season.collection_id == collection_id)
                if existing.season_type == SeasonType.NORMAL.value
            ),
            default=0,
        ) + 1

    season = Season(
        collection_id=collection_id,
        index=index,
        slug=slug,
        name=name,
        season_type=season_type.value,
        season_number=season_number,
        origin=origin.value,
    )
    s.add(season)
    s.flush()

    # A season the first index finds is there from the start, so a profile's upcoming seasons don't take it: a Download
    # Profile set up as the collection was added downloads what its preview said it would.
    if (
        update_collection_profiles and collection_contract(season.collection.type).downloads_by_season
        and collection_indexed(s, collection_id)
    ):
        for profile in season.collection.download_profiles:
            add_upcoming_season(profile, season.slug)
        s.flush()

    queue_event(
        s,
        "season.added",
        {
            "resource_id": season.id,
            "id": season.id,
            "slug": season.slug,
            "collection_id": season.collection_id,
        },
    )
    return season
