from __future__ import annotations

from collections import Counter
from typing import Optional, Sequence

from sqlalchemy import func, select, true
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
)
from backend.api.models.season import SeasonAPIRequestDetached
from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Collection, Episode, Season
from backend.db.models.download_profile import DownloadProfile
from backend.services.episode_rules import first_rule_leaving_out, set_profile_rules
from backend.services.which_episodes import EpisodeSelection, episodes_in_window, which_episodes
from backend.types.local_media_profile_types import LocalMediaProfileType
from backend.types.season_types import SeasonType
from backend.utils.local_media_profiles import require_local_media_profile_type
from backend.utils.season_ordering import season_type_from_name
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


def _resolve_or_create_seasons_for_collection(s: Session, collection_id: int, seasons_req: list[SeasonAPIRequestDetached]) -> list[Season]:
    # If empty list provided, clear association
    if not seasons_req:
        return []

    # Collect slugs from request
    slugs = {se.slug for se in seasons_req if getattr(se, 'slug', None)}

    existing: list[Season] = []
    if slugs:
        existing = (
            s.query(Season)
            .filter(Season.collection_id == collection_id)
            .filter(Season.slug.in_(slugs))
            .all()
        )

    by_slug = {se.slug: se for se in existing}

    result: list[Season] = []
    seen_ids: set[int] = set()
    next_index = int(s.scalar(
        select(func.coalesce(func.max(Season.index), 0))
        .where(Season.collection_id == collection_id)
    ) or 0)
    next_regular_number = int(s.scalar(
        select(func.coalesce(func.max(Season.season_number), 0))
        .where(
            Season.collection_id == collection_id,
            Season.season_type == SeasonType.NORMAL.value,
        )
    ) or 0)

    for season_in in seasons_req:
        match = by_slug.get(season_in.slug)
        if match is None:
            # This is normally pre-created by collection indexing, but keep the profile
            # endpoint correct when it receives a newly discovered season first.
            next_index += 1
            season_type = season_type_from_name(season_in.name)
            if season_type is SeasonType.NORMAL:
                next_regular_number += 1
                season_number = next_regular_number
            else:
                season_number = 0
            match = Season(
                collection_id=collection_id,
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
    collection = s.get(Collection, body.collection_id)
    require_local_media_profile_type(
        s, body.local_media_profile_id, LocalMediaProfileType.COLLECTION,
        collection.source_key if collection is not None else None,
    )
    require_unique_download_profile_episode_types(
        s,
        collection_id=body.collection_id,
        local_media_profile_id=body.local_media_profile_id,
        episode_types=body.ep_id_type_list,
    )
    item = create_database_fields(DownloadProfile, body, exclude_fields={"seasons", "rules"})
    s.add(item)
    set_profile_rules(item, body.rules)
    item.seasons = _resolve_or_create_seasons_for_collection(s, collection_id=item.collection_id, seasons_req=body.seasons)
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
    require_unique_download_profile_episode_types(
        s,
        collection_id=item.collection_id,
        local_media_profile_id=body.local_media_profile_id,
        episode_types=body.ep_id_type_list,
        exclude_profile_id=item.id,
    )
    update_database_fields(item, body, exclude_fields={"seasons", "rules"})
    set_profile_rules(item, body.rules)
    item.seasons = _resolve_or_create_seasons_for_collection(s, collection_id=item.collection_id, seasons_req=body.seasons)
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
        collection_id: int,
        local_media_profile_id: int,
        episode_types: Sequence[str],
        exclude_profile_id: int | None = None,
) -> None:
    requested_types = set(episode_types)
    others = select(DownloadProfile.id, DownloadProfile.ep_id_type_list).where(
        DownloadProfile.collection_id == collection_id,
        DownloadProfile.local_media_profile_id == local_media_profile_id,
    )
    if exclude_profile_id is not None:
        others = others.where(DownloadProfile.id != exclude_profile_id)
    other_lists = [list(types or []) for _id, types in s.execute(others)]
    # A profile without an episode types line downloads every type, so it overlaps any other.
    if other_lists and (not requested_types or any(not types for types in other_lists)):
        raise HTTPException(
            status_code=409,
            detail="Another Download Profile of this Collection already downloads these episodes with this Local Media Profile; "
                   "give each profile its own episode types",
        )
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
            DownloadProfile.collection_id == collection_id,
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
                "Episode types already used by another Download Profile for this collection and Local Media Profile: "
                + ", ".join(conflicts)
            ),
        )


def count_which_episodes(s: Session, collection: Collection, body: WhichEpisodesAPIRequest) -> WhichEpisodesAPIRead:
    """How many of the Collection's indexed episodes each line of the form leaves out."""
    season_ids = list(s.scalars(
        select(Season.id).where(Season.collection_id == collection.id, Season.slug.in_(body.season_slugs))
    )) if body.season_slugs else []
    selection = EpisodeSelection(
        collection=collection,
        ep_id_type_list=body.ep_id_type_list,
        download_with_countdown=body.download_with_countdown,
        download_days_in_past=body.download_days_in_past,
        download_episode_count=body.download_episode_count,
        download_starting_from=body.download_starting_from,
        season_ids=season_ids,
        include_upcoming_seasons=body.include_upcoming_seasons,
        rules=body.rules,
    )
    result = which_episodes(s, selection)
    episodes = None
    if body.include_episodes:
        published_at = func.coalesce(Episode.published_date, Episode.went_live_date)
        episodes = [
            {"id": episode_id, "slug": slug, "title": title, "published_at": published,
             "left_out_by": result.left_out_by.get(episode_id)}
            for episode_id, slug, title, published in s.execute(
                select(Episode.id, Episode.slug, Episode.title, published_at)
                .where(Episode.collection_id == collection.id)
                .order_by(published_at.desc().nulls_last(), Episode.id.desc())
                .offset(body.episodes_offset)
                .limit(body.episodes_limit)
            )
        ]
    return WhichEpisodesAPIRead.model_validate({**vars(result), "episodes": episodes})


def skipped_by_filter(s: Session, collection_id: int) -> list[SkippedByFilterAPIRead]:
    """Episodes of the Collection that its enabled Download Profiles' own rules leave out."""
    skipped: list[SkippedByFilterAPIRead] = []
    profiles = s.scalars(select(DownloadProfile).where(
        DownloadProfile.collection_id == collection_id,
        DownloadProfile.enable_profile.is_(True),
    ))
    for profile in profiles:
        if not profile.rules:
            continue
        for episode in episodes_in_window(s, EpisodeSelection.of_profile(profile)):
            index = first_rule_leaving_out(profile.rules, episode)
            if index is not None:
                skipped.append(SkippedByFilterAPIRead.model_validate({
                    "episode_id": episode.id,
                    "download_profile_id": profile.id,
                    "local_media_profile_id": profile.local_media_profile_id,
                    "rule": profile.rules[index],
                }))
    return skipped


def auto_subtitles_uses(s: Session, local_media_profile_id: int, access) -> list[AutoSubtitlesUseAPIRead]:
    """The Download Profiles of YouTube Collections that use this Local Media Profile."""
    profiles = list(s.scalars(
        select(DownloadProfile).where(DownloadProfile.local_media_profile_id == local_media_profile_id)
        .options(selectinload(DownloadProfile.collection))
    ))
    per_collection = Counter(profile.collection_id for profile in profiles)
    uses: list[AutoSubtitlesUseAPIRead] = []
    for profile in profiles:
        collection = profile.collection
        if not access.allows_source(collection.source_key):
            continue
        source = get_source(collection.source_key)
        if not source.auto_subtitles_for(collection.sharing_url):
            continue
        tags = {tag.key: tag.label for tag in source.episode_tags_for(collection.sharing_url)}
        uses.append(AutoSubtitlesUseAPIRead.model_validate({
            "download_profile_id": profile.id,
            "collection_id": collection.id,
            "collection_title": collection.title,
            "episode_types": [tags.get(key, key) for key in profile.ep_id_type_list]
            if per_collection[profile.collection_id] > 1 else [],
            "auto_subtitles": profile.auto_subtitles,
        }))
    return sorted(uses, key=lambda use: (use.collection_title.lower(), use.download_profile_id))
