"""A collection that joins a creator: "Add to creator" on the collection's page, and an import that adds a collection
of a creator.

A creator that is not in the Library yet is added for it, and the collection joins as it is: nothing else of the
creator is in the Library, so nothing moves.

A creator in the Library has its collections already, and each of the creator's videos is in one of them only. What
the joining collection is decides who keeps what another collection kept before:

- A collection of all the creator's uploads becomes the creator's own collection, and keeps only what no other
  collection of the creator keeps: a feed that has a collection of its own, such as the creator's Shorts, leaves it
  with its videos, and so does a list that is a collection of its own, also when it is one of its seasons.
- A collection of one list or feed, such as a playlist or the Shorts, takes it, also from the creator's own collection,
  which then leaves its videos.

What moves, moves as in moving the creator's feeds and lists from its Edit page (``section_moves``): a downloaded video
takes its files along into the collection that keeps it now, and every collection that gained or lost videos numbers
them again, unless the user said not to, and renames their files and rewrites their metadata. ``preview_join`` makes
the same changes and rolls them back, so the dialog shows what joining does.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Creator, CreatorAccount, CreatorSection, CreatorSectionItem, Collection, CollectionListItem
from backend.services.creators import (
    _new_creator, _list_of_main, _site_key_of, _switch_off, account_in_library, belong_to, collection_section,
    creator_site, join_overlaps, takes_feed,
)
from backend.services.episode_identification import collection_busy
from backend.services.errors import ServiceError
from backend.services.link_seasons import _holders, lists_in, place_in_link_seasons
from backend.services.reassigned import (
    _list_collection_ids, _main_lists, creator_places, lists_left_out, move_reassigned, reassigned_episodes,
    settle_creator,
)
from backend.services.section_moves import (
    Flow, SectionMovesPreview, _Moves, _add, _feed_episodes, _feeds_of, _handed_over, _media_names, _own_collection, _whole,
    as_one_operation, follow_up, preview, snapshot,
)
from backend.services.sites import site_record
from backend.types.creator_types import SectionStatus
from backend.types.link_season_types import OutsideVideos
from sources import CreatorDetails, SectionKind, SectionRole
from task_manager.scheduler.operations import spun_off_work


@dataclass(frozen=True)
class _Joining:
    account: CreatorAccount
    section: CreatorSection
    known: bool
    """The creator was in the Library already."""


def _joining(
    s: Session, collection: Collection, source_key: str, details: CreatorDetails, added_by_id: int | None,
) -> _Joining:
    """The account and section the collection joins as, adding the creator when it is not in the Library; refused when
    the collection can't join."""
    if collection.creator_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.creator.title}")
    site = creator_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    account = account_in_library(s, record.key, details.ref)
    known = account is not None
    if account is None:
        account = _new_creator(s, source_key, record.key, details, added_by_id=added_by_id)
    creator = account.creator
    section, keeper = collection_section(s, collection, source_key, details, account)
    if not isinstance(section, CreatorSection):
        raise ServiceError(f"{collection.title} is not a playlist, show or the videos of {creator.title}")
    if keeper is not None and not takes_over(account, section, keeper):
        raise ServiceError(f"{keeper.title} already keeps this part of {creator.title}")
    return _Joining(account, section, known)


def takes_over(account: CreatorAccount, section: CreatorSection, keeper: Collection) -> bool:
    """Whether the joining collection takes its section from the collection that keeps it: a list or a feed other
    than the main one from the creator's own collection. A collection of all the uploads leaves those to the creator's
    own collection, and a section that has a collection of its own already stays there."""
    if keeper.id != account.main_collection_id:
        return False
    if section.kind == SectionKind.LIST:
        return _list_of_main(account, section.ref) is not None
    return section.kind == SectionKind.FEED and section.role is not SectionRole.MAIN


def _join(s: Session, collection: Collection, joining: _Joining, source_key: str, details: CreatorDetails) -> _Moves:
    """Make the collection one of the creator's, and give each of the creator's videos the one collection that keeps
    it now."""
    account, section = joining.account, joining.section
    creator = account.creator
    main = account.main_collection
    overlaps = join_overlaps(s, collection, source_key, details, account)
    done = _Moves()
    belong_to(collection, creator)
    section.status = SectionStatus.KNOWN.value
    whole = section.kind == SectionKind.FEED and section.role is SectionRole.MAIN
    if whole and main is None:
        account.main_collection = collection
        main = collection
    s.flush()
    s.expire(creator, ["collections"])
    switched: set[int] = set()
    for overlap in overlaps:
        if overlap.ref == section.ref and overlap.can_move_here:
            # The collection of the list takes it from the creator's own collection.
            _take_list(s, account, section, collection, overlap.kept_by)
            switched.add(overlap.kept_by.id)
        else:
            # Another collection keeps the list already, so this one leaves it.
            _switch_off(collection, overlap.ref)
            switched.add(collection.id)
    if main is collection:
        _leave_kept_feeds(s, account, collection, done)
    elif main is not None and section.kind == SectionKind.FEED and takes_feed(main, section.ref):
        _take_feed(s, account, section, collection, main, done)
    s.flush()
    s.expire(creator, ["collections"])
    _settle(s, account, list({other.id: other for other in (collection, main) if other is not None}.values()), done)
    for collection_id in sorted(switched):
        place_in_link_seasons(s, s.get(Collection, collection_id), by_user=True)
    # Only a collection that gains or loses videos has to wait for what it is doing; the transaction rolls back.
    for collection_id in sorted(done.touched):
        busy = collection_busy(s, s.get(Collection, collection_id), "moving its episodes")
        if busy is not None:
            raise ServiceError(busy)
    return done


def _take_list(s: Session, account: CreatorAccount, section: CreatorSection, collection: Collection, main: Collection) -> None:
    """The collection of a list takes it from the creator's own collection, where it was a season. The videos of the
    season that the collection does not have yet join it, so their files can move along."""
    season = _list_of_main(account, section.ref)
    slugs = list(s.scalars(
        select(CollectionListItem.source_slug).where(CollectionListItem.list_id == season.id).order_by(CollectionListItem.position)
    ))
    _switch_off(main, section.ref)
    s.flush()
    have = _whole(s, collection)
    there = _whole(s, main)
    _add(s, collection, [there[slug] for slug in slugs if slug in there and slug not in have])


def _leave_kept_feeds(s: Session, account: CreatorAccount, collection: Collection, done: _Moves) -> None:
    """The collection of all the uploads lets go of the feeds that have a collection of their own, such as the
    creator's Shorts: their videos go there, with their files, except the ones a season of it keeps."""
    held = set(_holders(s, lists_in(collection)))
    for feed in account.sections:
        if feed.kind != SectionKind.FEED or feed.role is SectionRole.MAIN or not takes_feed(collection, feed.ref):
            continue
        own = _own_collection(account, feed)
        if own is None:
            continue
        episodes = [episode for episode in _feed_episodes(s, account, collection, feed) if episode.source_slug not in held]
        collection.feeds = sorted(set(_feeds_of(account, collection)) - {feed.ref})
        if not collection.feeds:
            collection.outside_videos = OutsideVideos.ONLY.value
        s.flush()
        done.flows.append(Flow(feed, feed.section_type.names, collection.id, own.id, [episode.id for episode in episodes]))
        _add(s, own, episodes)
        done.result.merge(move_reassigned(s, _handed_over(s, episodes, own), download_again=False))
        done.touched |= {collection.id, own.id}


def _take_feed(
    s: Session, account: CreatorAccount, feed: CreatorSection, collection: Collection, main: Collection, done: _Moves,
) -> None:
    """The collection of a feed, such as the creator's Shorts, takes it from the creator's own collection, with the
    videos and their files, except the ones a season of the creator's collection keeps."""
    held = set(_holders(s, lists_in(main)))
    episodes = [episode for episode in _feed_episodes(s, account, main, feed) if episode.source_slug not in held]
    main.feeds = sorted(set(_feeds_of(account, main)) - {feed.ref})
    if not main.feeds:
        main.outside_videos = OutsideVideos.ONLY.value
    s.flush()
    done.flows.append(Flow(feed, feed.section_type.names, main.id, collection.id, [episode.id for episode in episodes]))
    _add(s, collection, episodes)
    done.result.merge(move_reassigned(s, _handed_over(s, episodes, collection), download_again=False))
    done.touched |= {main.id, collection.id}


def _settle(s: Session, account: CreatorAccount, collections: list[Collection], done: _Moves) -> None:
    """Each of ``collections`` lets go of the videos another collection of the creator keeps by a list now: a
    downloaded one moves there with its files, one that is not downloaded simply goes. A video a list of the creator
    that is in no collection has leaves too, unless it is downloaded."""
    creator = account.creator
    places = creator_places(s, creator)
    lists = _list_collection_ids(creator, _main_lists(creator))
    sections = [section for section in account.sections if section.kind == SectionKind.LIST]
    flows: dict[tuple[int, int | None, int], list[int]] = {}
    of_section = {section.id: section for section in sections}
    for collection in collections:
        if collection.id in lists:
            continue
        holders = _holders(s, lists_in(collection))
        left = lists_left_out(s, collection)
        blocking = {
            slug: section_id for section_id, slug in s.execute(
                select(CreatorSectionItem.section_id, CreatorSectionItem.source_slug).where(CreatorSectionItem.section_id.in_(left))
            )
        } if left else {}
        for slug, episode_id in places.episodes.get(collection.id, {}).items():
            target = places.place(collection.id, slug)
            if target is not None:
                section = _list_of(sections, target, holders.get(slug) if target.id in creator.main_collection_ids else None)
                if section is not None:
                    flows.setdefault((collection.id, target.id, section.id), []).append(episode_id)
            elif slug in places.blocked.get(collection.id, ()) and episode_id not in places.downloaded and slug in blocking:
                section = of_section.get(blocking[slug])
                if section is not None:
                    flows.setdefault((collection.id, None, section.id), []).append(episode_id)
    for (source_id, target_id, section_id), episode_ids in sorted(flows.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2])):
        done.flows.append(Flow(of_section[section_id], _media_names(account), source_id, target_id, episode_ids))
        done.touched |= {source_id} | ({target_id} if target_id is not None else set())
    for collection in collections:
        if collection.id not in lists:
            done.result.merge(move_reassigned(s, reassigned_episodes(s, collection)))
    settle_creator(s, collections[0])


def _list_of(sections: list[CreatorSection], target: Collection, season) -> CreatorSection | None:
    """The list by which ``target`` keeps a video: the list it is a collection of, or the season that has it."""
    if season is not None:
        return next((section for section in sections if section.ref == season.ref), None)
    return next((section for section in sections if target.sharing_url == section.url or target.slug == section.ref), None)


def preview_join(s: Session, collection: Collection, *, source_key: str, details: CreatorDetails) -> SectionMovesPreview:
    """What joining the creator does to each of the creator's collections, made and rolled back. Empty when nothing
    moves, as for a creator that is not in the Library yet.

    ``s`` is a write transaction's session; it is rolled back."""
    joining = _joining(s, collection, source_key, details, None)
    if not joining.known:
        s.rollback()
        return SectionMovesPreview([])
    creator = joining.account.creator
    others = [*creator.collections, collection]
    titles = {other.id: (other.slug, other.title, other.type) for other in others}
    before = snapshot(s, others)
    done = _join(s, collection, joining, source_key, details)
    return preview(s, creator.id, titles, before, done)


def join_creator(
    s: Session, collection: Collection, *, source_key: str, details: CreatorDetails, added_by_id: int | None = None,
    renumber: Mapping[str, bool] | None = None,
) -> Creator:
    """Make a collection one of a creator's, adding the creator when it is not in the Library yet. ``renumber`` says,
    by collection slug, which collections keep their numbers after what moves.

    ``details`` was looked up before the write transaction. ``s`` is a write transaction's session."""
    joining = _joining(s, collection, source_key, details, added_by_id)
    account, section = joining.account, joining.section
    creator = account.creator
    if not joining.known:
        belong_to(collection, creator)
        section.status = SectionStatus.KNOWN.value
        if section.kind == SectionKind.FEED and section.role is SectionRole.MAIN and account.main_collection is None:
            account.main_collection = collection
        s.flush()
        return creator
    with spun_off_work(s) as work:
        done = _join(s, collection, joining, source_key, details)
        follow_up(s, done, renumber or {})
    moved = list({flow.section.id: flow.section for flow in done.flows}.values())
    as_one_operation(s, creator, work, moved or [section])
    return creator


__all__ = ["join_creator", "preview_join", "takes_over"]
