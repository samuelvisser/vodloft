from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session
from fastapi import HTTPException

from backend.api.models.download_profile import DownloadProfileAPICreate, DownloadProfileAPIRead, DownloadProfileAPIUpdate
from backend.api.models.season import SeasonAPIRequestDetached
from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Season
from backend.db.models.download_profile import DownloadProfile
from backend.types.local_media_profile_types import LocalMediaProfileType
from backend.types.season_types import SeasonType
from backend.utils.local_media_profiles import require_local_media_profile_type
from backend.utils.season_ordering import season_type_from_name
from task_manager.events.transactional import queue_event


def get_download_profiles_list(s: Session, show_slug: Optional[str] = None) -> list[DownloadProfileAPIRead]:

    if show_slug is not None:
        items = (
            s.query(DownloadProfile)
            .filter(
                DownloadProfile.show.has(slug=show_slug)
            )
            .order_by(DownloadProfile.id)
            .all()
        )
    else:
        items = (
            s.query(DownloadProfile)
            .order_by(DownloadProfile.id)
            .all()
        )

    return [DownloadProfileAPIRead.model_validate(it) for it in items]


def get_download_profile(s: Session, download_profile_id: int) -> DownloadProfileAPIRead:
    item = (
        s.query(DownloadProfile)
        .filter_by(id=download_profile_id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Download profile not found")

    return DownloadProfileAPIRead.model_validate(item)


def _profile_event(item: DownloadProfile) -> dict[str, int]:
    return {
        "resource_id": item.id,
        "id": item.id,
        "show_id": item.show_id,
    }


def _resolve_or_create_seasons_for_show(s: Session, show_id: int, seasons_req: list[SeasonAPIRequestDetached]) -> list[Season]:
    # If empty list provided, clear association
    if not seasons_req:
        return []

    # Collect slugs from request
    slugs = {se.slug for se in seasons_req if getattr(se, 'slug', None)}

    existing: list[Season] = []
    if slugs:
        existing = (
            s.query(Season)
            .filter(Season.show_id == show_id)
            .filter(Season.slug.in_(slugs))
            .all()
        )

    by_slug = {se.slug: se for se in existing}

    result: list[Season] = []
    seen_ids: set[int] = set()
    next_index = int(s.scalar(
        select(func.coalesce(func.max(Season.index), 0))
        .where(Season.show_id == show_id)
    ) or 0)
    next_regular_number = int(s.scalar(
        select(func.coalesce(func.max(Season.season_number), 0))
        .where(
            Season.show_id == show_id,
            Season.season_type == SeasonType.NORMAL.value,
        )
    ) or 0)

    for season_in in seasons_req:
        match = by_slug.get(season_in.slug)
        if match is None:
            # This is normally pre-created by show indexing, but keep the profile
            # endpoint correct when it receives a newly discovered season first.
            next_index += 1
            season_type = season_type_from_name(season_in.name)
            if season_type is SeasonType.NORMAL:
                next_regular_number += 1
                season_number = next_regular_number
            else:
                season_number = 0
            match = Season(
                show_id=show_id,
                index=next_index,
                slug=season_in.slug,
                name=season_in.name,
                season_type=season_type.value,
                season_number=season_number,
            )
            s.add(match)
            by_slug.setdefault(match.slug, match)
        if match.id is not None:
            if match.id not in seen_ids:
                result.append(match)
                seen_ids.add(match.id)
        else:
            # Not flushed yet, use object identity to avoid duplicates
            if id(match) not in seen_ids:
                result.append(match)
                seen_ids.add(id(match))

    return result


def create_download_profile(s: Session, body: DownloadProfileAPICreate) -> DownloadProfileAPIRead:
    require_local_media_profile_type(s, body.local_media_profile_id, LocalMediaProfileType.SHOW)
    require_unique_download_profile_episode_types(
        s,
        show_id=body.show_id,
        local_media_profile_id=body.local_media_profile_id,
        episode_types=body.ep_id_type_list,
    )
    item = create_database_fields(DownloadProfile, body, exclude_fields={"seasons"})
    s.add(item)
    item.seasons = _resolve_or_create_seasons_for_show(s, show_id=item.show_id, seasons_req=body.seasons)
    s.flush()

    queue_event(s, "download_profile.added", _profile_event(item))

    return DownloadProfileAPIRead.model_validate(item)


def update_download_profile(s: Session, download_profile_id: int, body: DownloadProfileAPIUpdate) -> DownloadProfileAPIRead:
    item: Optional[DownloadProfile] = s.get(DownloadProfile, download_profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Download profile not found")

    require_local_media_profile_type(s, body.local_media_profile_id, LocalMediaProfileType.SHOW)
    require_unique_download_profile_episode_types(
        s,
        show_id=item.show_id,
        local_media_profile_id=body.local_media_profile_id,
        episode_types=body.ep_id_type_list,
        exclude_profile_id=item.id,
    )
    update_database_fields(item, body, exclude_fields={"seasons"})
    item.seasons = _resolve_or_create_seasons_for_show(s, show_id=item.show_id, seasons_req=body.seasons)
    s.flush()

    queue_event(s, "download_profile.updated", _profile_event(item))

    return DownloadProfileAPIRead.model_validate(item)


def delete_download_profile(s: Session, download_profile_id: int) -> DownloadProfileAPIRead:
    item = s.get(DownloadProfile, download_profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Download profile not found")

    payload = DownloadProfileAPIRead.model_validate(item)

    queue_event(s, "download_profile.deleted", _profile_event(item))

    s.delete(item)
    s.flush()
    return payload


def require_unique_download_profile_episode_types(
        s: Session,
        *,
        show_id: int,
        local_media_profile_id: int,
        episode_types: Sequence[str],
        exclude_profile_id: int | None = None,
) -> None:
    requested_types = set(episode_types)
    if not requested_types:
        return

    episode_type = func.json_each(
        DownloadProfile.ep_id_type_list
    ).table_valued("key", "value").alias("episode_type")
    stmt = (
        select(episode_type.c.value)
        .select_from(DownloadProfile)
        .join(episode_type, true())
        .where(
            DownloadProfile.show_id == show_id,
            DownloadProfile.local_media_profile_id == local_media_profile_id,
            episode_type.c.value.in_(requested_types),
        )
        .distinct()
    )
    if exclude_profile_id is not None:
        stmt = stmt.where(DownloadProfile.id != exclude_profile_id)

    conflicts = sorted(str(value) for value in s.scalars(stmt))
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail=(
                "Episode types already used by another Download Profile for this show and Local Media Profile: "
                + ", ".join(conflicts)
            ),
        )
