"""Moving the feeds and lists of a creator, such as YouTube's Shorts or a playlist, between the creator's own collection,
a collection of their own and out of the Library, several at once, as the creator's Edit page saves them.

- A feed in the creator's own collection can become a collection of its own, or leave the Library; one in a collection
  of its own can join the creator's own collection again. The main feed, such as YouTube's Videos, has the creator's
  own collection's link, so it never becomes a collection of its own.
- A list can move between a season of the creator's own collection, the creator's own collection with its videos where
  the ones in no list go, and a collection of its own, or, from the creator's own collection, leave the Library.

What moves takes its videos along. A video that is not downloaded simply moves; a downloaded one moves the way a
reassigned video does: its files are renamed into the new place, or, for a list, downloaded again there when the new
place downloads it with another Local Media Profile, and the old files go once that succeeded. A feed's downloads
always keep their files, renamed. A video that leaves the Library leaves with its files. A collection of its own that
the feed or list left, and that has nothing left, goes.

Afterwards every collection that gained or lost videos numbers them again, unless the user said not to, and renames
its files and rewrites their metadata, by the same task that changes a collection's episode identification.

``preview_section_moves`` runs the same moves and rolls them back, so what the dialog shows is what saving does.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import (
    Creator, CreatorAccount, CreatorSection, Collection, CollectionListItem, Episode, EpisodeMediaDownload,
)
from backend.services.creators import (
    _make_seasons, _new_collection, _list_of_main, _settings_of, _switch_off, lists_are_seasons,
    section_collection_slug, takes_feed,
)
from backend.services.collections import index_new_collection, reindex_collection
from backend.services.episode_identification import (
    IdentificationChange, ProfileFilesChange, collection_busy, plan_identification, profile_file_changes,
    queue_renumber, renumber_changes,
)
from backend.operations.creators import CreatorMoveSectionsOperation
from backend.services.errors import ServiceError
from backend.services.link_seasons import (
    _holders, adds_outside_videos, lists_in, leaving_outside, place_in_link_seasons, remove_left_episode,
)
from backend.services.season_order import match_seasons_of_downloaded
from backend.services.reassigned import MoveResult, Reassignment, move_reassigned, reassigned_episodes, settle_creator
from backend.types.collection_types import EpisodeIdentifier
from backend.types.creator_types import SectionStatus, SectionTarget
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.link_season_types import OutsideVideos
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import dispatch_operation_targets, spun_off_work
from task_manager.scheduler.types import OperationSource
from sources import MAIN_TAG, Names, SectionKind, SectionRole, VideoDetails, get_source, section_type_names

_FIELD = "places"
# Where a list goes into the creator's own collection: as a season, or with its videos where the ones in no list go.
_INTO_MAIN = (SectionTarget.MAIN, SectionTarget.MAIN_LOOSE)
_ON_DISK = (MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value)
# Episodes the dialog names of each part that moves.
_EXAMPLES = 50


@dataclass(frozen=True)
class SectionMove:
    """Where one feed or list of one of the creator's accounts goes now."""

    account_id: int
    ref: str
    target: SectionTarget


@dataclass
class _Moves:
    result: MoveResult = field(default_factory=MoveResult)
    flows: list["Flow"] = field(default_factory=list)
    new: list[int] = field(default_factory=list)
    """The collections the moves made."""
    touched: set[int] = field(default_factory=set)
    """The collections that gained or lost videos."""
    seasons: dict[int, list[str]] = field(default_factory=dict)
    """The new seasons, by collection id."""
    seasoned: set[str] = field(default_factory=set)
    """The refs of the lists in the creator's own collection that became seasons of their own."""


@dataclass(frozen=True)
class Flow:
    """The videos of one feed or list that leave a collection: for another one, or out of the Library."""

    section: CreatorSection
    names: Names
    """What moves, in the Site's words: Shorts for a feed, videos for a list."""
    source_id: int
    target_id: int | None
    """None when they leave the Library; ``source_id`` when they change seasons within it."""
    episode_ids: list[int]
    """The videos as they were before they moved."""
    files_moved: int = 0
    """For videos that change seasons, how many downloads move along into their new season."""


def place_of(account: CreatorAccount, section: CreatorSection) -> SectionTarget:
    """Where the feed or list is now: in the creator's own collection, in a collection of its own, or nowhere."""
    main = account.main_collection
    if section.kind == SectionKind.FEED:
        if main is not None and takes_feed(main, section.ref):
            return SectionTarget.MAIN
    elif (link := _list_of_main(account, section.ref)) is not None:
        return SectionTarget.MAIN if link.as_season else SectionTarget.MAIN_LOOSE
    return SectionTarget.OWN if _own_collection(account, section) is not None else SectionTarget.EXCLUDE


def _own_collection(account: CreatorAccount, section: CreatorSection) -> Collection | None:
    slug = section_collection_slug(account.site_ref, section)
    return next((
        collection for collection in account.creator.collections
        if collection.id != account.main_collection_id and (collection.sharing_url == section.url or collection.slug == slug)
    ), None)


def _details(episode: Episode) -> VideoDetails:
    """A video the Library has already, to add to another collection without asking its Site again."""
    tag, separator, _rest = (episode.episode_identifier or "").partition(".")
    return VideoDetails(
        slug=episode.source_slug, url=episode.sharing_url, title=episode.title, description=episode.description,
        duration=episode.duration, image_url=episode.thumbnail_landscape_path, author_name=episode.author_name,
        published_at=episode.published_date, drm_protected=episode.drm_protected, access=episode.access,
        tag=tag if separator and tag != MAIN_TAG else MAIN_TAG,
    )


def _whole(s: Session, collection: Collection) -> dict[str, Episode]:
    return {
        episode.source_slug: episode
        for episode in s.scalars(select(Episode).where(Episode.collection_id == collection.id, Episode.part_of.is_(None)))
    }


def _add(s: Session, collection: Collection, episodes: list[Episode]) -> None:
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    if episodes:
        add_listed_episodes(s, collection_id=collection.id, found=[_details(episode) for episode in episodes])
        s.flush()


def _tag(identifier: str | None) -> str:
    return (identifier or "").partition(".")[0]


def _feed_episodes(s: Session, account: CreatorAccount, collection: Collection, section: CreatorSection) -> list[Episode]:
    """The collection's videos of the feed, told apart by their tag: a Short by the short tag, and the main feed's
    videos by any tag no other feed of the Site gives."""
    site = get_source(account.source_key).site_of(account.site_key)
    tag = section.section_type.episode_tag
    others = {type_.episode_tag for type_ in site.section_types if type_.kind is SectionKind.FEED and type_.key != section.type}
    def of_feed(episode: Episode) -> bool:
        found = _tag(episode.episode_identifier)
        return found == tag if tag != MAIN_TAG else found not in others

    return [episode for episode in _whole(s, collection).values() if of_feed(episode)]


def _feeds_of(account: CreatorAccount, collection: Collection) -> list[str]:
    """The feeds the creator's own collection lists."""
    if collection.feeds is not None:
        return list(collection.feeds)
    return [section.ref for section in account.sections if section.kind == SectionKind.FEED]


def _handed_over(s: Session, episodes: Sequence[Episode], target: Collection) -> list[Reassignment]:
    """Pair each downloaded video with the same video in ``target``; one that is not downloaded simply goes."""
    there = _whole(s, target)
    pairs = []
    for episode in episodes:
        if episode.source_slug in there:
            if episode.downloads:
                pairs.append(Reassignment(episode, there[episode.source_slug]))
            else:
                remove_left_episode(s, episode)
        # One that ``target`` leaves out, because a list of the creator that is not in it has it, stays where it is.
    return pairs


def _feed_to_own(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves, added_by_id: int | None) -> None:
    main = account.main_collection
    if section.role is SectionRole.MAIN:
        raise ServiceError(
            f"{section.title} lists everything {main.title} has, so it stays in it or leaves your library", field=_FIELD,
        )
    held = set(_holders(s, lists_in(main)))
    episodes = [episode for episode in _feed_episodes(s, account, main, section) if episode.source_slug not in held]
    main.feeds = sorted(set(_feeds_of(account, main)) - {section.ref})
    own = _new_collection(
        s, account, _settings_of(account.creator), title=f"{account.creator.title} {section.title}",
        slug=section_collection_slug(account.site_ref, section), url=section.url, description=section.description,
        image=section.image_path, added_by_id=added_by_id,
    )
    s.flush()
    moves.flows.append(Flow(section, section.section_type.names, main.id, own.id, [episode.id for episode in episodes]))
    _add(s, own, episodes)
    moves.result.merge(move_reassigned(s, _handed_over(s, episodes, own), download_again=False))
    moves.new.append(own.id)
    moves.touched |= {main.id, own.id}


def _feed_out(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves) -> None:
    main = account.main_collection
    feeds = sorted(set(_feeds_of(account, main)) - {section.ref})
    main.feeds = feeds
    if not feeds:
        # Without a feed it lists none of the creator's uploads, and holds what its playlist seasons give it.
        main.outside_videos = OutsideVideos.ONLY.value
    elif section.role is SectionRole.MAIN and main.outside_videos == OutsideVideos.LEAVE_OUT.value:
        # Its seasons keep their videos, which its other feeds don't list.
        main.outside_videos = OutsideVideos.ADD.value
    section.status = SectionStatus.IGNORED.value
    s.flush()
    held = set(_holders(s, lists_in(main))) if adds_outside_videos(main) else set()
    episodes = _feed_episodes(s, account, main, section)
    before = [episode.id for episode in episodes]
    for episode in episodes:
        # It is in the collection now only for a playlist season that has it, if one has; the others leave, files
        # and all, as the videos of a playlist the user took out do.
        episode.from_link_season = True
    s.flush()
    place_in_link_seasons(s, main, by_user=True)
    moves.flows.append(Flow(section, section.section_type.names, main.id, None, [
        episode_id for episode_id in before if s.get(Episode, episode_id) is None
        or s.get(Episode, episode_id).source_slug not in held
    ]))
    moves.touched.add(main.id)


def _feed_to_main(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves) -> None:
    main = account.main_collection
    if main is None:
        raise ServiceError(f"{account.creator.title} has no collection of its own to put {section.title} in", field=_FIELD)
    own = _own_collection(account, section)
    if main.feeds is not None:
        main.feeds = sorted({*main.feeds, section.ref})
    if main.outside_videos == OutsideVideos.ONLY.value:
        main.outside_videos = OutsideVideos.LEAVE_OUT.value
    section.status = SectionStatus.KNOWN.value
    s.flush()
    episodes = sorted(_whole(s, own).values(), key=lambda episode: episode.index)
    moves.flows.append(Flow(section, section.section_type.names, own.id, main.id, [episode.id for episode in episodes]))
    _add(s, main, episodes)
    moves.result.merge(move_reassigned(s, _handed_over(s, episodes, main), download_again=False))
    _drop_if_empty(s, own)
    reindex_collection(s, main)
    moves.touched |= {main.id, own.id}


def _list_to_own(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves, added_by_id: int | None) -> None:
    main = account.main_collection
    season = _list_of_main(account, section.ref)
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
    episodes = [have[slug] for slug in slugs if slug in have]
    moves.flows.append(Flow(section, _media_names(account), main.id, own.id, [episode.id for episode in episodes]))
    # Its videos come along now, so their files can move; indexing it adds what the Library did not have yet.
    _add(s, own, episodes)
    moves.result.merge(move_reassigned(s, [item for item in reassigned_episodes(s, main) if item.target.collection_id == own.id]))
    settle_creator(s, own)
    place_in_link_seasons(s, main, by_user=True)
    moves.new.append(own.id)
    moves.touched |= {main.id, own.id}


def _list_to_main(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves, *, as_season: bool) -> None:
    main = account.main_collection
    own = _own_collection(account, section)
    _make_seasons(account, main, {section.ref}, as_season=as_season)
    s.flush()
    season = next(link for link in main.lists if link.ref == section.ref)
    theirs = _whole(s, own)
    ordered = sorted(theirs.values(), key=lambda episode: episode.index)
    moves.flows.append(Flow(section, _media_names(account), own.id, main.id, [episode.id for episode in ordered]))
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
    moves.result.merge(move_reassigned(s, reassigned_episodes(s, own)))
    settle_creator(s, main)
    _drop_if_empty(s, own)
    reindex_collection(s, main)
    if as_season:
        moves.seasons.setdefault(main.id, []).append(section.title)
    moves.touched |= {main.id, own.id}


def _list_regrouped(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves, *, as_season: bool) -> None:
    """A list in the creator's own collection becomes a season of its own, or stops being one, so that its videos go
    where the ones in no list go. They change seasons, files and all; the files are renamed into their new season."""
    main = account.main_collection
    link = _list_of_main(account, section.ref)
    slugs = set(s.scalars(select(CollectionListItem.source_slug).where(CollectionListItem.list_id == link.id)))
    theirs = {episode.id: episode for slug, episode in _whole(s, main).items() if slug in slugs}
    before = {episode_id: episode.season_id for episode_id, episode in theirs.items()}
    left = frozenset() if as_season or link.season_id is None else frozenset({link.season_id})
    link.as_season = as_season
    s.flush()
    s.expire(main, ["lists"])
    place_in_link_seasons(s, main, with_files=set(theirs), by_user=True, left=left)
    moved = [episode_id for episode_id, episode in theirs.items() if episode.season_id != before[episode_id]]
    downloaded = set(s.scalars(
        select(EpisodeMediaDownload.media_item_id).where(
            EpisodeMediaDownload.media_item_id.in_(moved), EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
        )
    )) if moved else set()
    if downloaded:
        # Their numbers follow their new seasons, and their files move into those seasons' folders.
        match_seasons_of_downloaded(s, main, downloaded)
        moves.result.rename.setdefault(main.id, []).extend(sorted(downloaded))
    moves.flows.append(Flow(section, _media_names(account), main.id, main.id, moved, files_moved=len(downloaded)))
    if as_season:
        moves.seasons.setdefault(main.id, []).append(section.title)
        moves.seasoned.add(section.ref)
    moves.touched.add(main.id)


def _list_out(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves) -> None:
    main = account.main_collection
    before = {episode.id for episode in _whole(s, main).values()}
    _switch_off(main, section.ref)
    section.status = SectionStatus.IGNORED.value
    s.flush()
    place_in_link_seasons(s, main, by_user=True)
    leaving = {episode.id for episode in leaving_outside(s, main)}
    after = {episode.id for episode in _whole(s, main).values()} - leaving
    moves.flows.append(Flow(section, _media_names(account), main.id, None, sorted(before - after)))
    # A sync lets the videos only this list kept out come back, and the list's other videos leave.
    reindex_collection(s, main)
    moves.touched.add(main.id)


def _media_names(account: CreatorAccount) -> Names:
    return get_source(account.source_key).site_of(account.site_key).media_names


def _drop_if_empty(s: Session, collection: Collection) -> None:
    from task_manager.events.transactional import queue_event

    s.flush()
    if s.scalar(select(Episode.id).where(Episode.collection_id == collection.id).limit(1)) is None:
        queue_event(s, "collection.deleted", {"resource_id": collection.id, "id": collection.id, "slug": collection.slug})
        s.delete(collection)
        s.flush()


def _checked(creator: Creator, moves: Sequence[SectionMove]) -> list[tuple[CreatorAccount, CreatorSection, SectionTarget, SectionMove]]:
    """Each move with its account, section and where the section is now, refused when it can't be made."""
    checked = []
    seen = set()
    for move in moves:
        account = next((account for account in creator.accounts if account.id == move.account_id), None)
        section = next((section for section in account.sections if section.ref == move.ref), None) if account else None
        if section is None:
            raise ServiceError(f"{creator.title} has no section {move.ref}", field=_FIELD)
        if (account.id, section.ref) in seen:
            raise ServiceError(f"{section.title} can only move once at a time", field=_FIELD)
        seen.add((account.id, section.ref))
        origin = place_of(account, section)
        if origin is move.target:
            continue
        site = get_source(account.source_key).site_of(account.site_key)
        main = account.main_collection
        if section.kind == SectionKind.LIST and not lists_are_seasons(site):
            raise ServiceError(f"{section.title} can't move: {site.section_list_names.plural} can't be seasons here", field=_FIELD)
        if section.kind not in (SectionKind.FEED, SectionKind.LIST) or (
            section.kind == SectionKind.FEED and move.target is SectionTarget.MAIN_LOOSE
        ):
            raise ServiceError(f"{section.title} can't move", field=_FIELD)
        if origin is SectionTarget.EXCLUDE:
            raise ServiceError(f"{section.title} is not in your library; add it from the creator's page", field=_FIELD)
        if origin is SectionTarget.OWN and move.target is SectionTarget.EXCLUDE:
            own = _own_collection(account, section)
            raise ServiceError(
                f"{section.title} is the collection {own.title}; delete that collection to take it out of your library",
                field=_FIELD,
            )
        if move.target in _INTO_MAIN and main is None:
            raise ServiceError(f"{creator.title} has no collection of its own to put {section.title} in", field=_FIELD)
        if origin in _INTO_MAIN and move.target is SectionTarget.OWN and _own_collection(account, section) is not None:
            raise ServiceError(f"{_own_collection(account, section).title} is a collection of {section.title} already", field=_FIELD)
        checked.append((account, section, origin, move))
    return checked


def _apply(
    s: Session, creator: Creator, moves: Sequence[SectionMove], *, added_by_id: int | None,
) -> _Moves:
    checked = _checked(creator, moves)
    involved = {
        collection.id: collection for account, section, _origin, _move in checked
        for collection in (account.main_collection, _own_collection(account, section)) if collection is not None
    }
    for collection in involved.values():
        busy = collection_busy(s, collection, "moving its episodes")
        if busy is not None:
            raise ServiceError(busy, field=_FIELD)
    done = _Moves()
    # What leaves the creator's own collection goes first, so what joins it finds it as it will be.
    for account, section, origin, move in sorted(checked, key=lambda item: item[3].target in _INTO_MAIN):
        if section.kind == SectionKind.FEED:
            if move.target is SectionTarget.OWN:
                _feed_to_own(s, account, section, done, added_by_id)
            elif move.target is SectionTarget.EXCLUDE:
                _feed_out(s, account, section, done)
            else:
                _feed_to_main(s, account, section, done)
        elif move.target is SectionTarget.OWN:
            _list_to_own(s, account, section, done, added_by_id)
        elif move.target is SectionTarget.EXCLUDE:
            _list_out(s, account, section, done)
        elif origin in _INTO_MAIN:
            _list_regrouped(s, account, section, done, as_season=move.target is SectionTarget.MAIN)
        else:
            _list_to_main(s, account, section, done, as_season=move.target is SectionTarget.MAIN)
        s.flush()
        s.expire(account, ["main_collection"])
        s.expire(creator, ["collections"])
    return done


def _numbered_again(collection: Collection, renumber: Mapping[str, bool]) -> bool:
    """Whether the collection numbers its episodes again after the move: unless the user said not to, and never when
    it numbers them by date, which no move changes."""
    if EpisodeIdentifier(collection.episode_identifier) is EpisodeIdentifier.DATE_BASED:
        return False
    return renumber.get(collection.slug, True)


def move_sections(
    s: Session, creator: Creator, moves: Sequence[SectionMove], *, renumber: Mapping[str, bool], added_by_id: int | None,
) -> None:
    """Move the creator's feeds and lists, with their videos, then number the videos of every collection that gained
    or lost some again, rename their files and rewrite their metadata. ``renumber`` says, by collection slug, which
    collections keep their numbers instead.

    ``s`` is a write transaction's session."""
    # Every operation and task the move starts is a part of one operation for the whole move, which tells the user
    # when it is done and shows its progress on the creator's page.
    with spun_off_work(s) as work:
        done = _apply(s, creator, moves, added_by_id=added_by_id)
        follow_up(s, done, renumber)
    moved = [section for move in moves if (section := s.scalar(select(CreatorSection).where(
        CreatorSection.account_id == move.account_id, CreatorSection.ref == move.ref,
    ))) is not None]
    as_one_operation(s, creator, work, moved)


def follow_up(s: Session, done: _Moves, renumber: Mapping[str, bool]) -> None:
    """After the moves: let the old files of what moved go once their new downloads succeeded, number the videos of
    every collection that gained or lost some again, rename their files and rewrite their metadata, and index the new
    collections. ``renumber`` says, by collection slug, which collections keep their numbers instead."""
    from task_manager.scheduler.transactional import queue_task_after_commit

    for collection_id in sorted(done.result.sources):
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=collection_id)
    for collection_id in sorted(done.touched):
        collection = s.get(Collection, collection_id)
        if collection is None:
            continue
        again = _numbered_again(collection, renumber)
        if collection_id in done.result.rename or (again and plan_identification(
            s, collection, EpisodeIdentifier(collection.episode_identifier),
        ).identifiers):
            queue_renumber(s, collection, renumber=again, sections=sorted({
                f"{flow.section.account_id}:{flow.section.ref}" for flow in done.flows
                if collection_id in (flow.source_id, flow.target_id)
            }))
    for collection_id in done.new:
        collection = s.get(Collection, collection_id)
        if collection is not None:
            index_new_collection(s, collection)


def as_one_operation(s: Session, creator: Creator, work, sections: Sequence[CreatorSection]) -> None:
    """Make the operations and tasks ``work`` gathered the parts of one "creator.move_sections" operation, which tells
    the user when the whole move is done, named by the feeds and lists that moved."""
    if not work.operations and not work.tasks:
        return
    for operation in work.operations:
        operation.source = OperationSource.SYSTEM.value
    dispatch_operation_targets(s, create_operation(s, CreatorMoveSectionsOperation(
        creator, parts=work.operations, tasks=work.tasks,
        sections=[f"{section.account_id}:{section.ref}" for section in sections],
        names=section_type_names(section.section_type for section in sections),
    )))


@dataclass(frozen=True)
class MovedPart:
    """The videos of one feed or list that leave a collection or join it."""

    section_title: str
    section_kind: SectionKind
    names: Names
    direction: str
    """out, to another collection; in, from another one; leave, out of the Library; or within the collection,
    season, into a season of their list's own, or loose, from it to where the videos in no list go."""
    count: int
    other_title: str | None
    """The collection they move to or come from."""
    examples: list[str]
    """The titles of the videos, newest first, up to a few dozen."""
    downloads_deleted: int = 0
    kept_deleted: int = 0
    """Of the downloads deleted, the ones marked Keep."""
    deleting_profiles: list[str] = field(default_factory=list)
    files_moved: int = 0
    """Downloads whose files move along into this collection."""


@dataclass(frozen=True)
class CollectionMovePreview:
    slug: str
    title: str
    type: str
    state: str
    """existing, new, or deleted once it is empty."""
    episode_identifier: EpisodeIdentifier
    parts: list[MovedPart]
    new_seasons: list[str]
    episodes: int
    """How many episodes it has afterwards."""
    renumber_offered: bool
    """Whether it can number its episodes again: not when it numbers them by date."""
    changes: list[IdentificationChange]
    """The episodes that get a new number when it numbers them again, newest first."""
    profiles: list[ProfileFilesChange]
    """What numbering again does to each Local Media Profile's files; the metadata is rewritten either way."""
    files_follow: bool
    """Files moved into it, so its files are renamed and their metadata rewritten also when it keeps its numbers."""
    indexed: bool
    """It looks for videos it does not have yet afterwards."""


@dataclass(frozen=True)
class SectionMovesPreview:
    collections: list[CollectionMovePreview]


@dataclass(frozen=True)
class _Before:
    collection_id: int
    slug: str
    title: str
    published: object
    downloads: list[tuple[str, bool]]
    """The Local Media Profile name of each download on disk, and whether it is marked Keep."""


def snapshot(s: Session, collections: Sequence[Collection]) -> dict[int, _Before]:
    """The collections' videos as they are before the moves, for ``preview``."""
    ids = [collection.id for collection in collections]
    found: dict[int, _Before] = {}
    for episode in s.scalars(select(Episode).where(Episode.collection_id.in_(ids), Episode.part_of.is_(None))):
        found[episode.id] = _Before(
            episode.collection_id, episode.source_slug, episode.title, episode.published_date,
            [
                (download.local_media_profile.name, bool(download.kept)) for download in episode.downloads
                if download.artifact_status in _ON_DISK
            ],
        )
    return found


def _newest_first(befores: list[_Before]) -> list[str]:
    from datetime import datetime, timezone

    earliest = datetime.min.replace(tzinfo=timezone.utc)
    return [item.title for item in sorted(befores, key=lambda item: item.published or earliest, reverse=True)][:_EXAMPLES]


def preview_section_moves(s: Session, creator: Creator, moves: Sequence[SectionMove]) -> SectionMovesPreview:
    """What saving the moves does, collection by collection: the moves are made and rolled back.

    ``s`` is a write transaction's session; it is rolled back."""
    titles = {collection.id: (collection.slug, collection.title, collection.type) for collection in creator.collections}
    before = snapshot(s, creator.collections)
    done = _apply(s, creator, moves, added_by_id=None)
    return preview(s, creator.id, titles, before, done)


def preview(
    s: Session, creator_id: int, titles: dict[int, tuple[str, str, str]], before: dict[int, _Before], done: _Moves,
) -> SectionMovesPreview:
    """What ``done`` did to each collection it touched, from the videos ``before`` it, and rolls it all back.
    ``titles`` has the slug, title and type of each collection before."""
    s.flush()
    s.expire_all()
    creator = s.get(Creator, creator_id)
    after = {collection.id: collection for collection in creator.collections}
    for collection_id in done.new:
        collection = s.get(Collection, collection_id)
        titles[collection_id] = (collection.slug, collection.title, collection.type)
    parts: dict[int, list[MovedPart]] = {}
    for flow in done.flows:
        items = [before[episode_id] for episode_id in flow.episode_ids if episode_id in before]
        if not items:
            continue
        common = dict(section_title=flow.section.title, section_kind=flow.section.kind, names=flow.names,
                      count=len(items), examples=_newest_first(items))
        if flow.target_id is None:
            deleted = [download for item in items for download in item.downloads]
            parts.setdefault(flow.source_id, []).append(MovedPart(
                direction="leave", other_title=None, downloads_deleted=len(deleted),
                kept_deleted=sum(1 for _name, kept in deleted if kept),
                deleting_profiles=sorted({name for name, _kept in deleted}), **common,
            ))
            continue
        if flow.target_id == flow.source_id:
            # The list became a season of its own, or stopped being one.
            parts.setdefault(flow.source_id, []).append(MovedPart(
                direction="season" if flow.section.ref in done.seasoned else "loose", other_title=None,
                files_moved=flow.files_moved, **common,
            ))
            continue
        moved = sum(len(item.downloads) for item in items)
        parts.setdefault(flow.source_id, []).append(MovedPart(direction="out", other_title=titles[flow.target_id][1], **common))
        parts.setdefault(flow.target_id, []).append(MovedPart(
            direction="in", other_title=titles[flow.source_id][1], files_moved=moved, **common,
        ))
    previews = []
    for collection_id in sorted(done.touched, key=lambda key: (key in done.new, key)):
        slug, title, type_ = titles[collection_id]
        collection = after.get(collection_id)
        if collection is None:
            previews.append(CollectionMovePreview(
                slug=slug, title=title, type=type_, state="deleted", episode_identifier=EpisodeIdentifier.SEASONAL,
                parts=parts.get(collection_id, []), new_seasons=[], episodes=0, renumber_offered=False, changes=[],
                profiles=[], files_follow=False, indexed=False,
            ))
            continue
        identification = EpisodeIdentifier(collection.episode_identifier)
        offered = identification is not EpisodeIdentifier.DATE_BASED
        changes, changed_ids = renumber_changes(s, collection) if offered else ([], set())
        # Saving renames files and rewrites metadata only where files moved in or numbers change, as move_sections.
        follow = collection_id in done.result.rename
        previews.append(CollectionMovePreview(
            slug=slug, title=title, type=type_, state="new" if collection_id in done.new else "existing",
            episode_identifier=identification, parts=parts.get(collection_id, []),
            new_seasons=done.seasons.get(collection_id, []),
            episodes=len(_whole(s, collection)), renumber_offered=offered and bool(changes), changes=changes,
            profiles=profile_file_changes(s, collection, changed_ids) if follow or changes else [], files_follow=follow,
            indexed=collection_id in done.new,
        ))
    s.rollback()
    return SectionMovesPreview(previews)


__all__ = [
    "CollectionMovePreview", "MovedPart", "SectionMove", "SectionMovesPreview", "move_sections", "place_of",
    "preview_section_moves",
]
