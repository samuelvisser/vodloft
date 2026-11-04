from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from fastapi import HTTPException

from backend.api.models.download_profile import (
    AutoSubtitlesUseAPIRead,
    DownloadProfileAPICreate,
    DownloadProfileAPIRead,
    DownloadProfileAPIUpdate,
    SkippedByFilterAPIRead,
    WhichEpisodesAPIRead,
    WhichEpisodesAPIRequest,
    WhichEpisodesEpisodeAPIRead,
)
from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Collection
from backend.db.models.download_profile import DownloadProfile
from backend.services.episode_filters import (
    EpisodeSelection, collection_episodes, evaluate, is_date_line, published_at, set_profile_filters,
)
from backend.types.local_media_profile_types import LocalMediaProfileType
from backend.utils.local_media_profiles import require_local_media_profile_type
from sources import get_source
from task_manager.events.transactional import queue_event


def get_download_profiles_list(s: Session, collection_slug: Optional[str] = None) -> list[DownloadProfileAPIRead]:

    if collection_slug is not None:
        items = (
            s.query(DownloadProfile)
            .filter(
                DownloadProfile.collection.has(slug=collection_slug)
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
        "collection_id": item.collection_id,
    }


def create_download_profile(s: Session, body: DownloadProfileAPICreate) -> DownloadProfileAPIRead:
    collection = s.get(Collection, body.collection_id)
    require_local_media_profile_type(
        s, body.local_media_profile_id, LocalMediaProfileType.COLLECTION,
        collection.source_key if collection is not None else None,
    )
    require_one_profile_per_local_media_profile(
        s, collection_id=body.collection_id, local_media_profile_id=body.local_media_profile_id,
    )
    item = create_database_fields(DownloadProfile, body, exclude_fields={"filters"})
    s.add(item)
    set_profile_filters(item, body.filters)
    s.flush()

    queue_event(s, "download_profile.added", _profile_event(item))

    return DownloadProfileAPIRead.model_validate(item)


def update_download_profile(s: Session, download_profile_id: int, body: DownloadProfileAPIUpdate) -> DownloadProfileAPIRead:
    item: Optional[DownloadProfile] = s.get(DownloadProfile, download_profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Download profile not found")

    # A profile limited to other Sources after it was chosen stays usable where it already is.
    require_local_media_profile_type(
        s, body.local_media_profile_id, LocalMediaProfileType.COLLECTION,
        item.collection.source_key if body.local_media_profile_id != item.local_media_profile_id else None,
    )
    require_one_profile_per_local_media_profile(
        s, collection_id=item.collection_id, local_media_profile_id=body.local_media_profile_id,
        exclude_profile_id=item.id,
    )
    update_database_fields(item, body, exclude_fields={"filters"})
    set_profile_filters(item, body.filters)
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


def require_one_profile_per_local_media_profile(
        s: Session,
        *,
        collection_id: int,
        local_media_profile_id: int,
        exclude_profile_id: int | None = None,
) -> None:
    """A collection has at most one Download Profile per Local Media Profile."""
    stmt = select(DownloadProfile.id).where(
        DownloadProfile.collection_id == collection_id,
        DownloadProfile.local_media_profile_id == local_media_profile_id,
    )
    if exclude_profile_id is not None:
        stmt = stmt.where(DownloadProfile.id != exclude_profile_id)
    if s.scalar(stmt.limit(1)) is not None:
        raise HTTPException(
            status_code=409,
            detail="This Collection already has a Download Profile for this Local Media Profile",
        )


def count_which_episodes(s: Session, collection: Collection, body: WhichEpisodesAPIRequest) -> WhichEpisodesAPIRead:
    """How many of the Collection's indexed episodes each line of the form leaves out."""
    selection = EpisodeSelection(
        collection=collection, download_with_countdown=body.download_with_countdown, filters=body.filters,
    )
    episodes = collection_episodes(s, collection.id)
    result = evaluate(s, selection, episodes=episodes)
    page = None
    if body.include_episodes:
        page = [
            WhichEpisodesEpisodeAPIRead.model_validate({
                "id": episode.id, "slug": episode.slug, "title": episode.title,
                "published_at": published_at(episode), "left_out_by": result.left_out_by.get(episode.id),
            })
            for episode in episodes[body.episodes_offset:body.episodes_offset + body.episodes_limit]
        ]
    return WhichEpisodesAPIRead(
        total=result.total, unavailable=result.unavailable, filters=result.counts,
        downloaded=len(result.wanted), episodes=page,
    )


def skipped_by_filter(s: Session, collection_id: int) -> list[SkippedByFilterAPIRead]:
    """Episodes of the Collection that a filter of its enabled Download Profiles leaves out, other than a date line."""
    skipped: list[SkippedByFilterAPIRead] = []
    profiles = s.scalars(select(DownloadProfile).where(
        DownloadProfile.collection_id == collection_id,
        DownloadProfile.enable_profile.is_(True),
    ))
    for profile in profiles:
        if not any(not is_date_line(item) and item.action != "keep" for item in profile.filters):
            continue
        result = evaluate(s, EpisodeSelection.of_profile(profile))
        for episode_id in result.left_out_by:
            index = result.left_out_by_filter(episode_id)
            if index is None or is_date_line(profile.filters[index]):
                continue
            skipped.append(SkippedByFilterAPIRead.model_validate({
                "episode_id": episode_id,
                "download_profile_id": profile.id,
                "local_media_profile_id": profile.local_media_profile_id,
                "filter": profile.filters[index],
            }))
    return skipped


def auto_subtitles_uses(s: Session, local_media_profile_id: int, access) -> list[AutoSubtitlesUseAPIRead]:
    """The Download Profiles of YouTube Collections that use this Local Media Profile."""
    profiles = list(s.scalars(
        select(DownloadProfile).where(DownloadProfile.local_media_profile_id == local_media_profile_id)
        .options(selectinload(DownloadProfile.collection))
    ))
    uses: list[AutoSubtitlesUseAPIRead] = []
    for profile in profiles:
        collection = profile.collection
        if not access.allows_source(collection.source_key):
            continue
        source = get_source(collection.source_key)
        if not source.auto_subtitles_for(collection.sharing_url):
            continue
        uses.append(AutoSubtitlesUseAPIRead.model_validate({
            "download_profile_id": profile.id,
            "collection_id": collection.id,
            "collection_title": collection.title,
            "auto_subtitles": profile.auto_subtitles,
        }))
    return sorted(uses, key=lambda use: (use.collection_title.lower(), use.download_profile_id))
