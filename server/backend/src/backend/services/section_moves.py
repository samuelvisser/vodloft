"""Moving a list of a creator, such as a playlist, between a season of the creator's own collection and a collection of
its own, or out of the Library.

The list takes its videos along. A video that is not downloaded simply moves; a downloaded one moves the way a
reassigned video does: its files are renamed into the new place, or downloaded again there when the new place downloads
it with another Local Media Profile, and the old files go once that succeeded. A collection of its own that the list
left, and that has nothing left, goes.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import CreatorAccount, CreatorSection, Collection, CollectionListItem, Episode
from backend.services.creators import (
    _make_seasons, _new_collection, _season_of_main, _settings_of, _switch_off, lists_are_seasons,
    section_collection_slug,
)
from backend.services.collections import index_new_collection, reindex_collection
from backend.services.errors import ServiceError
from backend.services.link_seasons import place_in_link_seasons
from backend.services.reassigned import MoveResult, move_and_rename, reassigned_episodes, settle_creator
from backend.types.creator_types import SectionStatus, SectionTarget
from sources import MAIN_TAG, SectionKind, VideoDetails, get_source


@dataclass
class SectionMove:
    result: MoveResult
    collection: Collection | None
    """The collection the list is in now; None when it left the Library."""


def _details(episode: Episode) -> VideoDetails:
    """A video the Library has already, to add to another collection without asking its Site again."""
    tag, separator, _rest = (episode.episode_identifier or "").partition(".")
    return VideoDetails(
        slug=episode.source_slug, url=episode.sharing_url, title=episode.title, description=episode.description,
        duration=episode.duration, image_url=episode.thumbnail_landscape_path, author_name=episode.author_name,
        published_at=episode.published_date, drm_protected=episode.drm_protected, access=episode.access,
        tag=tag if separator and tag != "ep" else MAIN_TAG,
    )


def _whole(s: Session, collection: Collection) -> dict[str, Episode]:
    return {
        episode.source_slug: episode
        for episode in s.scalars(select(Episode).where(Episode.collection_id == collection.id, Episode.part_of.is_(None)))
    }


def _own_collection(account: CreatorAccount, section: CreatorSection) -> Collection | None:
    slug = section_collection_slug(account.site_ref, section)
    return next((
        collection for collection in account.creator.collections
        if collection.id != account.main_collection_id and (collection.sharing_url == section.url or collection.slug == slug)
    ), None)


def _add(s: Session, collection: Collection, episodes: list[Episode]) -> None:
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    if episodes:
        add_listed_episodes(s, collection_id=collection.id, found=[_details(episode) for episode in episodes])
        s.flush()


def _to_own(s: Session, account: CreatorAccount, section: CreatorSection, *, added_by_id: int | None) -> SectionMove:
    main = account.main_collection
    season = _season_of_main(account, section.ref)
    slugs = list(s.scalars(
        select(CollectionListItem.source_slug).where(CollectionListItem.list_id == season.id).order_by(CollectionListItem.position)
    ))
    _switch_off(main, section.ref)
    own = _new_collection(
        s, account, _settings_of(account.creator), title=section.title, slug=section_collection_slug(account.site_ref, section),
        url=section.url, description=section.description, image=section.image_path, added_by_id=added_by_id,
    )
    s.flush()
    have = _whole(s, main)
    # Its videos come along now, so their files can move; indexing it adds what the Library did not have yet.
    _add(s, own, [have[slug] for slug in slugs if slug in have])
    result, _operations = move_and_rename(s, [
        item for item in reassigned_episodes(s, main) if item.target.collection_id == own.id
    ])
    settle_creator(s, own)
    place_in_link_seasons(s, main, by_user=True)
    index_new_collection(s, own)
    return SectionMove(result, own)


def _to_season(s: Session, account: CreatorAccount, section: CreatorSection, own: Collection) -> SectionMove:
    main = account.main_collection
    _make_seasons(account, main, {section.ref})
    s.flush()
    season = next(link for link in main.lists if link.ref == section.ref)
    theirs = _whole(s, own)
    ordered = sorted(theirs.values(), key=lambda episode: episode.index)
    if not s.scalar(select(CollectionListItem.list_id).where(CollectionListItem.list_id == season.id).limit(1)):
        # The collection of its own knows the list's videos; the creator's collection lists them again when it syncs.
        for position, episode in enumerate(episode for episode in ordered if not episode.removed_from_source):
            s.add(CollectionListItem(list_id=season.id, source_slug=episode.source_slug, position=position))
    have = _whole(s, main)
    missing = [episode for episode in ordered if episode.source_slug not in have]
    _add(s, main, missing)
    others = [episode.source_slug for episode in missing if episode.author_name not in (None, account.creator.title)]
    for episode in s.scalars(select(Episode).where(Episode.collection_id == main.id, Episode.source_slug.in_(others))):
        # Another creator's video is only in it for the list, and stays only when it adds such videos.
        episode.from_link_season = True
    s.flush()
    s.expire(main, ["lists"])
    place_in_link_seasons(s, main)
    result, _operations = move_and_rename(s, reassigned_episodes(s, own))
    settle_creator(s, main)
    left = s.scalar(select(Episode.id).where(Episode.collection_id == own.id).limit(1))
    if left is None:
        _delete_collection(s, own)
    reindex_collection(s, main)
    return SectionMove(result, main)


def _delete_collection(s: Session, collection: Collection) -> None:
    from task_manager.events.transactional import queue_event

    queue_event(s, "collection.deleted", {"resource_id": collection.id, "id": collection.id, "slug": collection.slug})
    s.delete(collection)
    s.flush()


def _out(s: Session, account: CreatorAccount, section: CreatorSection) -> SectionMove:
    main = account.main_collection
    _switch_off(main, section.ref)
    section.status = SectionStatus.IGNORED.value
    s.flush()
    place_in_link_seasons(s, main, by_user=True)
    return SectionMove(MoveResult(), None)


def move_section(
    s: Session, account: CreatorAccount, ref: str, target: SectionTarget, *, added_by_id: int | None = None,
) -> SectionMove:
    """Move one of the lists of a creator's account, with its videos, to a season of the account's own collection,
    to a collection of its own, or, from a season, out of the Library.

    ``s`` is a write transaction's session."""
    creator = account.creator
    section = next((section for section in account.sections if section.ref == ref), None)
    if section is None:
        raise ServiceError(f"{creator.title} has no section {ref}", field="target")
    site = get_source(account.source_key).site_of(account.site_key)
    if section.kind != SectionKind.LIST or not lists_are_seasons(site):
        raise ServiceError(f"{section.title} can't move: only a playlist can be a season or a collection of its own", field="target")
    in_main = _season_of_main(account, ref) is not None
    own = _own_collection(account, section)
    if target is SectionTarget.OWN:
        if not in_main:
            raise ServiceError(f"{section.title} is not a season of {creator.title}'s collection", field="target")
        if own is not None:
            raise ServiceError(f"{own.title} is a collection of {section.title} already", field="target")
        return _to_own(s, account, section, added_by_id=added_by_id)
    if target is SectionTarget.MAIN:
        if account.main_collection is None:
            raise ServiceError(f"{creator.title} has no collection of its own to make it a season of", field="target")
        if in_main:
            raise ServiceError(f"{section.title} is a season of {creator.title}'s collection already", field="target")
        if own is None:
            raise ServiceError(f"{section.title} is not in your Library; add it from the creator's page", field="target")
        return _to_season(s, account, section, own)
    if not in_main:
        raise ServiceError(
            f"{section.title} is a collection of its own; delete that collection to take it out of your Library",
            field="target",
        )
    return _out(s, account, section)

