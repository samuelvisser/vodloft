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

from collections.abc import Mapping, Sequence, Set as AbstractSet
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import (
    Creator, CreatorAccount, CreatorSection, CreatorSectionItem, Collection, CollectionList, CollectionListItem, Episode,
    EpisodeMediaDownload,
)
from backend.services.creators import (
    SectionPlan, _make_seasons, _new_collection, _own_settings, _settings_of, _switch_off, feed_holder, gather,
    gatherable, list_holder, lists_are_seasons, own_collection, section_collection_slug,
)
from backend.services.collections import index_new_collection, reindex_collection
from backend.services.episode_identification import (
    IdentificationChange, ProfileFilesChange, collection_busy, plan_identification, profile_file_changes,
    queue_renumber, renumber_changes,
)
from backend.operations.creators import CreatorMoveSectionsOperation
from backend.services.errors import ServiceError
from backend.services.link_seasons import (
    _holders, adds_outside_videos, list_each, lists_in, leaving_outside, place_in_link_seasons, remove_left_episode,
)
from backend.services.season_order import match_seasons_of_downloaded
from backend.services.reassigned import (
    MoveResult, Reassignment, move_reassigned, reassigned_episodes, save_left_out, settle_creator,
)
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.creator_types import SectionStatus, SectionTarget
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.link_season_types import OutsideVideos
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import dispatch_operation_targets, spun_off_work
from task_manager.scheduler.types import OperationSource
from sources import ItemRef, MAIN_TAG, Names, SectionKind, SectionRole, VideoDetails, get_source, section_type_names

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
    collection_slug: str | None = None
    """For a feed or list that goes into a collection that gathers the account's feeds and lists: which one, when it
    is not the account's own collection."""
    type: CollectionType | None = None
    episode_identifier: EpisodeIdentifier | None = None
    """For a list that waits for the user's choice and becomes a collection of its own: its type and how it numbers
    its episodes; left out, those every collection of the creator starts with."""


@dataclass
class _Moves:
    result: MoveResult = field(default_factory=MoveResult)
    flows: list["Flow"] = field(default_factory=list)
    new: list[int] = field(default_factory=list)
    """The collections the moves made."""
    touched: set[int] = field(default_factory=set)
    """The collections that gained or lost videos."""
    synced: set[int] = field(default_factory=set)
    dropping: set[int] = field(default_factory=set)
    """The collections of a feed or list of their own that left the Library, which go once their files are deleted."""
    """The collections whose links changed, which are listed again once after all the moves."""
    seasons: dict[int, list[str]] = field(default_factory=dict)
    """The new seasons, by collection id."""
    seasoned: set[str] = field(default_factory=set)
    """The refs of the lists in the creator's own collection that became seasons of their own."""


@dataclass(frozen=True)
class Flow:
    """The videos of one feed or list that leave a collection: for another one, or out of the Library."""

    section: CreatorSection | None
    """None for videos moved to where they belong that no list of a creator holds there, such as videos in no list."""
    names: Names
    """What moves, in the Site's words: Shorts for a feed, videos for a list."""
    source_id: int
    target_id: int | None
    """None when they leave the Library; ``source_id`` when they change seasons within it."""
    episode_ids: list[int]
    """The videos as they were before they moved."""
    files_moved: int = 0
    """For videos that change seasons, how many downloads move along into their new season."""
    to_season: str | None = None
    """For videos moved to the season their collection's lists put them in now, as Moved: that season's name."""
    label: str | None = None
    """Without a section: what the videos are of, such as the list that holds them where they go."""

    @property
    def title(self) -> str:
        return self.section.title if self.section is not None else self.label or ""

    @property
    def kind(self) -> SectionKind:
        return self.section.kind if self.section is not None else SectionKind.LIST

    @property
    def section_key(self) -> str | None:
        return f"{self.section.account_id}:{self.section.ref}" if self.section is not None else None


def place_of(account: CreatorAccount, section: CreatorSection) -> tuple[SectionTarget, Collection | None]:
    """Where the feed or list is now, and in which collection: in a collection that gathers the account's feeds and
    lists, a list as a season or not; in a collection of its own; or nowhere."""
    if section.kind == SectionKind.FEED:
        holder = feed_holder(account, section.ref)
        if holder is not None:
            return SectionTarget.MAIN, holder
    elif (held := list_holder(account, section.ref)) is not None:
        collection, link = held
        return (SectionTarget.MAIN if link.as_season else SectionTarget.MAIN_LOOSE), collection
    own = own_collection(account, section)
    return (SectionTarget.OWN, own) if own is not None else (SectionTarget.EXCLUDE, None)


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


def _feed_to_own(
    s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, moves: _Moves, added_by_id: int | None,
) -> None:
    if section.role is SectionRole.MAIN:
        raise ServiceError(
            f"{section.title} lists everything {source.title} has, so it stays in it or leaves your library", field=_FIELD,
        )
    episodes = _feed_leaving(s, account, section, source)
    source.feeds = sorted(set(_feeds_of(account, source)) - {section.ref})
    own = _new_collection(
        s, account, _settings_of(account.creator), title=f"{account.creator.title} {section.title}",
        slug=section_collection_slug(account.site_ref, section), url=section.url, description=section.description,
        image=section.image_path, added_by_id=added_by_id,
    )
    s.flush()
    moves.flows.append(Flow(section, section.section_type.names, source.id, own.id, [episode.id for episode in episodes]))
    _add(s, own, episodes)
    moves.result.merge(move_reassigned(s, _handed_over(s, episodes, own), download_again=False))
    _drop_if_left_empty(s, account, source)
    moves.new.append(own.id)
    moves.touched |= {source.id, own.id}


def _drop_if_left_empty(s: Session, account: CreatorAccount, collection: Collection) -> None:
    """A collection that gathered some of the account's feeds and lists goes once they all left it with their videos,
    unless it is the account's own collection."""
    if collection is not account.main_collection:
        _drop_if_empty(s, collection)


def _feed_leaving(s: Session, account: CreatorAccount, section: CreatorSection, source: Collection) -> list[Episode]:
    """The videos of the feed that leave the collection with it: all but those a list in it holds."""
    held = set(_holders(s, lists_in(source)))
    return [episode for episode in _feed_episodes(s, account, source, section) if episode.source_slug not in held]


def _feed_out(s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, moves: _Moves) -> None:
    feeds = sorted(set(_feeds_of(account, source)) - {section.ref})
    source.feeds = feeds
    if not feeds:
        # Without a feed it lists none of the creator's uploads, and holds what its playlist seasons give it.
        source.outside_videos = OutsideVideos.ONLY.value
    elif section.role is SectionRole.MAIN and source.outside_videos == OutsideVideos.LEAVE_OUT.value:
        # Its seasons keep their videos, which its other feeds don't list.
        source.outside_videos = OutsideVideos.ADD.value
    section.status = SectionStatus.IGNORED.value
    s.flush()
    held = set(_holders(s, lists_in(source))) if adds_outside_videos(source) else set()
    episodes = _feed_episodes(s, account, source, section)
    before = [episode.id for episode in episodes]
    for episode in episodes:
        # It is in the collection now only for a playlist season that has it, if one has; the others leave, files
        # and all, as the videos of a playlist the user took out do.
        episode.from_link_season = True
    s.flush()
    place_in_link_seasons(s, source, by_user=True)
    moves.flows.append(Flow(section, section.section_type.names, source.id, None, [
        episode_id for episode_id in before if s.get(Episode, episode_id) is None
        or s.get(Episode, episode_id).source_slug not in held
    ]))
    moves.touched.add(source.id)


def _feed_into(
    s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, target: Collection, moves: _Moves,
) -> None:
    """The feed goes into a collection that gathers the account's feeds, from a collection of its own, which goes once
    it is empty, or from another collection that gathers them."""
    gathered = source in account.gatherers
    if gathered:
        episodes = _feed_leaving(s, account, section, source)
        source.feeds = sorted(set(_feeds_of(account, source)) - {section.ref})
    else:
        episodes = sorted(_whole(s, source).values(), key=lambda episode: episode.index)
    if target.feeds is not None:
        target.feeds = sorted({*target.feeds, section.ref})
    if target.outside_videos == OutsideVideos.ONLY.value:
        target.outside_videos = OutsideVideos.LEAVE_OUT.value
    section.status = SectionStatus.KNOWN.value
    s.flush()
    moves.flows.append(Flow(section, section.section_type.names, source.id, target.id, [episode.id for episode in episodes]))
    _add(s, target, episodes)
    moves.result.merge(move_reassigned(s, _handed_over(s, episodes, target), download_again=False))
    _drop_if_left_empty(s, account, source)
    moves.synced.add(target.id)
    moves.touched |= {source.id, target.id}


def _list_items(s: Session, link) -> list[str]:
    return list(s.scalars(
        select(CollectionListItem.source_slug).where(CollectionListItem.list_id == link.id).order_by(CollectionListItem.position)
    ))


def _list_to_own(
    s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, moves: _Moves, added_by_id: int | None,
) -> None:
    _holder, link = list_holder(account, section.ref)
    slugs = _list_items(s, link)
    _switch_off(source, section.ref)
    own = _new_collection(
        s, account, _settings_of(account.creator), title=section.title, slug=section_collection_slug(account.site_ref, section),
        url=section.url, description=section.description, image=section.image_path, added_by_id=added_by_id,
    )
    s.flush()
    have = _whole(s, source)
    episodes = [have[slug] for slug in slugs if slug in have]
    # Its videos come along now, so their files can move; indexing it adds what the Library did not have yet.
    _add(s, own, episodes)
    moves.result.merge(move_reassigned(s, [item for item in reassigned_episodes(s, source) if item.target.collection_id == own.id]))
    settle_creator(s, own)
    place_in_link_seasons(s, source, by_user=True)
    moves.flows.append(Flow(section, _media_names(account), source.id, own.id, _gone(s, account.creator, source.id, episodes)))
    _drop_if_left_empty(s, account, source)
    moves.new.append(own.id)
    moves.touched |= {source.id, own.id}


def _list_into(
    s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, target: Collection, moves: _Moves, *,
    as_season: bool,
) -> None:
    """The list goes into a collection that gathers the account's lists, as a season or not: from a collection of its
    own, which goes once it is empty, or from another collection that gathers them."""
    gathered = source in account.gatherers
    if gathered:
        _holder, link = list_holder(account, section.ref)
        have = _whole(s, source)
        ordered = [have[slug] for slug in _list_items(s, link) if slug in have]
        listed = _list_items(s, link)
        _switch_off(source, section.ref)
    else:
        ordered = sorted(_whole(s, source).values(), key=lambda episode: episode.index)
        listed = [episode.source_slug for episode in ordered if not episode.removed_from_source]
    _make_seasons(account, target, {section.ref}, as_season=as_season)
    s.flush()
    season = next(link for link in target.lists if link.ref == section.ref)
    moves.flows.append(Flow(section, _media_names(account), source.id, target.id, [episode.id for episode in ordered]))
    if not s.scalar(select(CollectionListItem.list_id).where(CollectionListItem.list_id == season.id).limit(1)):
        # The collection it comes from knows the list's videos; the collection lists them again when it syncs.
        for position, slug in enumerate(listed):
            s.add(CollectionListItem(list_id=season.id, source_slug=slug, position=position))
    have = _whole(s, target)
    missing = [episode for episode in ordered if episode.source_slug not in have]
    _add(s, target, missing)
    others = [
        episode.source_slug for episode in missing
        if episode.author_name not in (None, account.creator.title) or target.outside_videos == OutsideVideos.ONLY.value
    ]
    for episode in s.scalars(select(Episode).where(Episode.collection_id == target.id, Episode.source_slug.in_(others))):
        # A video its feeds don't list is only in it for the list, and stays only while a list in it has it.
        episode.from_link_season = True
    s.flush()
    s.expire(target, ["lists"])
    place_in_link_seasons(s, target)
    moves.result.merge(move_reassigned(s, [
        item for item in reassigned_episodes(s, source) if item.target.collection_id == target.id
    ]))
    settle_creator(s, target)
    if gathered:
        place_in_link_seasons(s, source, by_user=True)
    _drop_if_left_empty(s, account, source)
    moves.synced.add(target.id)
    if as_season:
        moves.seasons.setdefault(target.id, []).append(section.title)
    moves.touched |= {source.id, target.id}


def lists_to_list(s: Session, creator: Creator, moves: Sequence[SectionMove]) -> dict[str, dict[int, str]]:
    """The skipped lists among the moves whose videos the move must know first, as a waiting list's are known: those
    going into a collection or keeping their videos out. Their links by section id, by Source."""
    wanted: dict[str, dict[int, str]] = {}
    for move in moves:
        if move.target is SectionTarget.EXCLUDE:
            continue
        account = next((account for account in creator.accounts if account.id == move.account_id), None)
        section = next((section for section in account.sections if section.ref == move.ref), None) if account else None
        if (
            section is not None and section.kind == SectionKind.LIST and section.status != SectionStatus.NEW.value
            and place_of(account, section)[0] is SectionTarget.EXCLUDE
        ):
            wanted.setdefault(account.source_key, {})[section.id] = section.url
    return wanted


def list_skipped(wanted: Mapping[str, Mapping[int, str]]) -> dict[int, tuple[ItemRef, ...]]:
    """The videos each of ``lists_to_list`` has now, by section id. A list that could not be listed is left out. Slow,
    so no transaction stays open."""
    listed: dict[int, tuple[ItemRef, ...]] = {}
    for source_key, lists in wanted.items():
        listed.update(list_each(get_source(source_key), dict(lists)))
    return listed


def _gone(s: Session, creator: Creator, collection_id: int, episodes: Sequence[Episode]) -> list[int]:
    """The ids of ``episodes`` that leave the collection now that the moves are made: removed already, or placed in
    another collection of the creator, or kept out. Each collection decides by its own setting for a video in several
    seasons: with one episode per video every video of a list that went elsewhere leaves, and with an episode in each
    season the ones a list season of its own has stay."""
    from backend.services.reassigned import creator_places

    ids = [episode.id for episode in episodes]
    s.flush()
    places = creator_places(s, creator)
    blocked = places.blocked.get(collection_id, frozenset())
    slugs = {episode_id: slug for slug, episode_id in places.episodes.get(collection_id, {}).items()}
    return [
        episode_id for episode_id in ids
        if episode_id not in slugs or places.place(collection_id, slugs[episode_id]) is not None or slugs[episode_id] in blocked
    ]


def _pending_items(s: Session, section: CreatorSection) -> list[str]:
    """What a list that waits for the user's choice has, as the creator's collections listed it last."""
    return list(dict.fromkeys(s.scalars(
        select(CreatorSectionItem.source_slug).where(CreatorSectionItem.section_id == section.id)
    )))


def _pending_episodes(
    s: Session, account: CreatorAccount, slugs: Sequence[str], *, but: Collection | None = None,
) -> dict[int, list[Episode]]:
    """The videos of a waiting list in each of the creator's collections but ``but``, where they are while the list
    changes nothing, by collection id."""
    wanted = set(slugs)
    found: dict[int, list[Episode]] = {}
    for collection in account.creator.collections:
        if collection is but:
            continue
        episodes = [episode for slug, episode in _whole(s, collection).items() if slug in wanted]
        if episodes:
            found[collection.id] = sorted(episodes, key=lambda episode: episode.index)
    return found


def _pending_into(
    s: Session, account: CreatorAccount, section: CreatorSection, target: Collection, moves: _Moves, *, as_season: bool,
) -> None:
    """A list that waited for the user's choice goes into a collection that gathers the account's lists, as a season
    or not. Its videos come along at once, with their files: from the season they were in when the collection has
    them already, and from the other collections of the creator, which leave them."""
    slugs = _pending_items(s, section)
    section.status = SectionStatus.KNOWN.value
    _make_seasons(account, target, {section.ref}, as_season=as_season)
    s.flush()
    link = next(link for link in target.lists if link.ref == section.ref)
    if slugs and not s.scalar(select(CollectionListItem.list_id).where(CollectionListItem.list_id == link.id).limit(1)):
        # The collections listed it while it waited; the collection lists it again when it syncs.
        s.add_all(CollectionListItem(list_id=link.id, source_slug=slug, position=position) for position, slug in enumerate(slugs))
    elsewhere = _pending_episodes(s, account, slugs, but=target)
    have = _whole(s, target)
    here = {have[slug].id: have[slug].season_id for slug in slugs if slug in have}
    seen: set[str] = set()
    missing = []
    for episodes in elsewhere.values():
        for episode in episodes:
            if episode.source_slug not in have and episode.source_slug not in seen:
                seen.add(episode.source_slug)
                missing.append(episode)
    _add(s, target, missing)
    others = [
        episode.source_slug for episode in missing
        if episode.author_name not in (None, account.creator.title) or target.outside_videos == OutsideVideos.ONLY.value
    ]
    for episode in s.scalars(select(Episode).where(Episode.collection_id == target.id, Episode.source_slug.in_(others))):
        # A video its feeds don't list is only in it for the list, and stays only while a list in it has it.
        episode.from_link_season = True
    s.flush()
    s.expire(target, ["lists"])
    place_in_link_seasons(s, target, with_files=set(here))
    moved = [episode_id for episode_id, season_id in here.items() if s.get(Episode, episode_id).season_id != season_id]
    downloaded = set(s.scalars(
        select(EpisodeMediaDownload.media_item_id).where(
            EpisodeMediaDownload.media_item_id.in_(moved), EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
        )
    )) if moved else set()
    if downloaded:
        # Their numbers follow their new season, and their files move into its folder.
        match_seasons_of_downloaded(s, target, downloaded)
        moves.result.rename.setdefault(target.id, []).extend(sorted(downloaded))
    if moved:
        moves.flows.append(Flow(section, _media_names(account), target.id, target.id, moved, files_moved=len(downloaded)))
        if as_season:
            moves.seasoned.add(section.ref)
    for collection_id in elsewhere:
        moves.result.merge(move_reassigned(s, [
            item for item in reassigned_episodes(s, s.get(Collection, collection_id)) if item.target.collection_id == target.id
        ]))
        moves.touched.add(collection_id)
    settle_creator(s, target)
    for collection_id, episodes in elsewhere.items():
        moves.flows.append(Flow(section, _media_names(account), collection_id, target.id, _gone(s, account.creator, collection_id, episodes)))
    moves.synced.add(target.id)
    if as_season:
        moves.seasons.setdefault(target.id, []).append(section.title)
    moves.touched.add(target.id)


def _pending_to_own(
    s: Session, account: CreatorAccount, section: CreatorSection, move: SectionMove, moves: _Moves, added_by_id: int | None,
) -> None:
    """A list that waited for the user's choice becomes a collection of its own. Its videos come along at once from
    the creator's other collections, which leave them, with their files."""
    slugs = _pending_items(s, section)
    section.status = SectionStatus.KNOWN.value
    plan = SectionPlan(section.ref, SectionTarget.OWN, type=move.type, episode_identifier=move.episode_identifier)
    own = _new_collection(
        s, account, _own_settings(_settings_of(account.creator), plan, section), title=section.title,
        slug=section_collection_slug(account.site_ref, section), url=section.url, description=section.description,
        image=section.image_path, added_by_id=added_by_id,
    )
    s.flush()
    elsewhere = _pending_episodes(s, account, slugs, but=own)
    seen: set[str] = set()
    joining = []
    for episodes in elsewhere.values():
        for episode in episodes:
            if episode.source_slug not in seen:
                seen.add(episode.source_slug)
                joining.append(episode)
    # Its videos come along now, so their files can move; indexing it adds what the Library did not have yet.
    _add(s, own, joining)
    for collection_id in elsewhere:
        moves.result.merge(move_reassigned(s, [
            item for item in reassigned_episodes(s, s.get(Collection, collection_id)) if item.target.collection_id == own.id
        ]))
        moves.touched.add(collection_id)
    settle_creator(s, own)
    for collection_id, episodes in elsewhere.items():
        moves.flows.append(Flow(section, _media_names(account), collection_id, own.id, _gone(s, account.creator, collection_id, episodes)))
    moves.new.append(own.id)
    moves.touched.add(own.id)


def _list_regrouped(
    s: Session, account: CreatorAccount, section: CreatorSection, collection: Collection, moves: _Moves, *, as_season: bool,
) -> None:
    """A list in a collection that gathers the account's lists becomes a season of its own, or stops being one, so
    that its videos go where the ones in no list go. They change seasons, files and all; the files are renamed into
    their new season."""
    _holder, link = list_holder(account, section.ref)
    slugs = set(_list_items(s, link))
    theirs = {episode.id: episode for slug, episode in _whole(s, collection).items() if slug in slugs}
    before = {episode_id: episode.season_id for episode_id, episode in theirs.items()}
    left = frozenset() if as_season or link.season_id is None else frozenset({link.season_id})
    link.as_season = as_season
    s.flush()
    s.expire(collection, ["lists"])
    place_in_link_seasons(s, collection, with_files=set(theirs), by_user=True, left=left)
    moved = [episode_id for episode_id, episode in theirs.items() if episode.season_id != before[episode_id]]
    downloaded = set(s.scalars(
        select(EpisodeMediaDownload.media_item_id).where(
            EpisodeMediaDownload.media_item_id.in_(moved), EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
        )
    )) if moved else set()
    if downloaded:
        # Their numbers follow their new seasons, and their files move into those seasons' folders.
        match_seasons_of_downloaded(s, collection, downloaded)
        moves.result.rename.setdefault(collection.id, []).extend(sorted(downloaded))
    moves.flows.append(Flow(section, _media_names(account), collection.id, collection.id, moved, files_moved=len(downloaded)))
    if as_season:
        moves.seasons.setdefault(collection.id, []).append(section.title)
        moves.seasoned.add(section.ref)
    moves.touched.add(collection.id)


def _list_out(
    s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, moves: _Moves,
    status: SectionStatus = SectionStatus.IGNORED,
) -> None:
    before = {episode.id for episode in _whole(s, source).values()}
    _switch_off(source, section.ref)
    section.status = status.value
    s.flush()
    place_in_link_seasons(s, source, by_user=True)
    leaving = {episode.id for episode in leaving_outside(s, source)}
    after = {episode.id for episode in _whole(s, source).values()} - leaving
    moves.flows.append(Flow(section, _media_names(account), source.id, None, sorted(before - after)))
    # A sync lets the videos only this list kept out come back, and the list's other videos leave.
    moves.synced.add(source.id)
    moves.touched.add(source.id)


def _own_out(
    s: Session, account: CreatorAccount, section: CreatorSection, source: Collection, moves: _Moves, status: SectionStatus,
) -> None:
    """A feed or list that is a collection of its own leaves the Library: the collection goes, with all its episodes
    and their files, also the ones marked Keep, as the move dialog said. Without downloads it goes at once; otherwise a
    task deletes their files first, then the collection."""
    from task_manager.scheduler.transactional import queue_task_after_commit

    section.status = status.value
    episodes = list(_whole(s, source).values())
    moves.flows.append(Flow(section, _media_names(account), source.id, None, [episode.id for episode in episodes]))
    moves.touched.add(source.id)
    has_downloads = s.scalar(
        select(EpisodeMediaDownload.id).join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(Episode.collection_id == source.id).limit(1)
    ) is not None
    if has_downloads:
        moves.dropping.add(source.id)
        queue_task_after_commit(s, def_key="remove_skipped_collection", resource_type="collection", resource_id=source.id)
    else:
        _delete_collection(s, source)


def drop_skipped_collection(s: Session, collection_id: int) -> None:
    """Remove a collection of a feed or list of its own that left the Library once its files are deleted, unless the
    user added the feed or list again meanwhile.

    ``s`` is a write transaction's session."""
    collection = s.get(Collection, collection_id)
    if collection is None or collection.creator is None:
        return
    section = next((
        section for account in collection.creator.accounts for section in account.sections
        if own_collection(account, section) is collection
    ), None)
    if section is not None and section.status in (SectionStatus.IGNORED.value, SectionStatus.KEPT_OUT.value):
        _delete_collection(s, collection)


def _delete_collection(s: Session, collection: Collection) -> None:
    from task_manager.events.transactional import queue_event

    queue_event(s, "collection.deleted", {"resource_id": collection.id, "id": collection.id, "slug": collection.slug})
    s.delete(collection)
    s.flush()


def _keep_out(s: Session, account: CreatorAccount, section: CreatorSection, moves: _Moves) -> None:
    """The list keeps its videos out of every collection of the creator: they leave each one, files and all, also
    the seasons of its other lists."""
    from backend.services.link_seasons import _drop_outside

    creator = account.creator
    slugs = _pending_items(s, section)
    if not slugs:
        # It was in a collection until now, which listed it, so its videos are known from there.
        slugs = list(dict.fromkeys(s.scalars(
            select(CollectionListItem.source_slug).join(CollectionList, CollectionList.id == CollectionListItem.list_id)
            .where(CollectionList.collection_id.in_([c.id for c in creator.collections]), CollectionList.ref == section.ref)
            .order_by(CollectionListItem.position)
        )))
        s.add_all(CreatorSectionItem(section_id=section.id, source_slug=slug) for slug in slugs)
    section.status = SectionStatus.KEPT_OUT.value
    s.flush()
    for collection in list(creator.collections):
        if collection.id in moves.dropping:
            continue
        leaving = [episode.id for episode in leaving_outside(s, collection) if episode.video_slug in set(slugs)]
        if not leaving:
            continue
        _drop_outside(s, collection, by_user=True)
        left = next((flow for flow in moves.flows if flow.section is section and flow.source_id == collection.id
                     and flow.target_id is None), None)
        if left is not None:
            # It also left the collection it was in: one part says what leaves.
            left.episode_ids.extend(episode_id for episode_id in leaving if episode_id not in left.episode_ids)
        else:
            moves.flows.append(Flow(section, _media_names(account), collection.id, None, leaving))
        moves.touched.add(collection.id)


def _media_names(account: CreatorAccount) -> Names:
    return get_source(account.source_key).site_of(account.site_key).media_names


def _drop_if_empty(s: Session, collection: Collection) -> None:
    s.flush()
    if s.scalar(select(Episode.id).where(Episode.collection_id == collection.id).limit(1)) is None:
        _delete_collection(s, collection)


@dataclass(frozen=True)
class _Checked:
    account: CreatorAccount
    section: CreatorSection
    origin: SectionTarget
    source: Collection | None
    """The collection the feed or list is in now."""
    move: SectionMove
    target: Collection | None
    """The collection it goes into, for one that gathers the account's feeds and lists."""
    pending: bool = False
    """A list that waits for the user's choice: it is in no collection, and its videos are where they would be
    without it."""


def _pending_list(section: CreatorSection, origin: SectionTarget, listed: AbstractSet[int] = frozenset()) -> bool:
    """Whether the section is a list that is not in the Library and whose videos are known, which a move answers: one
    that waits for the user's choice, or a skipped one that was just listed (``listed``)."""
    return origin is SectionTarget.EXCLUDE and section.kind == SectionKind.LIST and (
        section.status == SectionStatus.NEW.value or section.id in listed
    )


def _target_of(creator: Creator, account: CreatorAccount, section: CreatorSection, move: SectionMove) -> Collection | None:
    if move.target not in _INTO_MAIN:
        return None
    if move.collection_slug is None:
        if account.main_collection is None:
            raise ServiceError(f"{creator.title} has no collection of its own to put {section.title} in", field=_FIELD)
        return account.main_collection
    target = next((collection for collection in gatherable(account) if collection.slug == move.collection_slug), None)
    if target is None:
        raise ServiceError(f"{section.title} can't go into that collection", field=_FIELD)
    return target


def _checked(creator: Creator, moves: Sequence[SectionMove], listed: AbstractSet[int] = frozenset()) -> list[_Checked]:
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
        origin, source = place_of(account, section)
        site = get_source(account.source_key).site_of(account.site_key)
        if section.kind == SectionKind.LIST and not lists_are_seasons(site) and move.target is not origin:
            raise ServiceError(f"{section.title} can't move: {site.section_list_names.plural} can't be seasons here", field=_FIELD)
        if section.kind not in (SectionKind.FEED, SectionKind.LIST) or (
            section.kind == SectionKind.FEED and move.target is SectionTarget.MAIN_LOOSE
        ):
            raise ServiceError(f"{section.title} can't move", field=_FIELD)
        target = _target_of(creator, account, section, move)
        if origin is move.target and (target is None or target is source):
            continue
        pending = _pending_list(section, origin, listed)
        if move.target is SectionTarget.KEEP_OUT and section.kind != SectionKind.LIST:
            raise ServiceError(f"Only a list can be blacklisted; skip {section.title} instead", field=_FIELD)
        if move.target is SectionTarget.KEEP_OUT and section.status == SectionStatus.KEPT_OUT.value:
            continue
        if origin is SectionTarget.EXCLUDE and not pending:
            raise ServiceError(
                f"VODLoft could not look up what {section.title} has; try again in a moment" if section.kind == SectionKind.LIST
                else f"{section.title} is not in your library; add it from the creator's page", field=_FIELD,
            )
        if target is not None and target is own_collection(account, section):
            raise ServiceError(f"{target.title} is a collection of {section.title} already", field=_FIELD)
        if (
            section.kind == SectionKind.FEED and section.role is SectionRole.MAIN and target is not None
            and target is not account.main_collection
        ):
            raise ServiceError(
                f"{section.title} lists everything {source.title} has, so it stays in it or leaves your library", field=_FIELD,
            )
        if (
            move.target is SectionTarget.OWN and source is not None and source is not account.main_collection
            and (source.slug == section_collection_slug(account.site_ref, section) or source.sharing_url == section.url)
        ):
            raise ServiceError(f"{source.title} was made from {section.title}, so it stays there; move the others out of it instead", field=_FIELD)
        if origin in _INTO_MAIN and move.target is SectionTarget.OWN and own_collection(account, section) is not None:
            raise ServiceError(f"{own_collection(account, section).title} is a collection of {section.title} already", field=_FIELD)
        checked.append(_Checked(account, section, origin, source, move, target, pending))
    return checked


def _apply(
    s: Session, creator: Creator, moves: Sequence[SectionMove], *, added_by_id: int | None,
    listed: Mapping[int, tuple[ItemRef, ...]] | None = None,
) -> _Moves:
    if listed:
        # A skipped list moves as a waiting one does, now that its videos are known.
        save_left_out(s, listed)
    checked = _checked(creator, moves, frozenset(listed or ()))
    involved = {
        collection.id: collection for item in checked
        for collection in (item.account.main_collection, item.source, item.target) if collection is not None
    }
    for collection in involved.values():
        busy = collection_busy(s, collection, "moving its episodes")
        if busy is not None:
            raise ServiceError(busy, field=_FIELD)
    done = _Moves()
    # What leaves a collection goes first, so what joins one finds it as it will be.
    for item in sorted(checked, key=lambda item: item.move.target in _INTO_MAIN):
        account, section, source, target = item.account, item.section, item.source, item.target
        if target is not None:
            target = gather(s, account, target)
        if item.origin is SectionTarget.OWN and item.move.target in (SectionTarget.EXCLUDE, SectionTarget.KEEP_OUT):
            kept_out = item.move.target is SectionTarget.KEEP_OUT
            _own_out(s, account, section, source, done, SectionStatus.KEPT_OUT if kept_out else SectionStatus.IGNORED)
            if kept_out:
                s.expire(creator, ["collections"])
                _keep_out(s, account, section, done)
        elif item.move.target is SectionTarget.KEEP_OUT:
            if source is not None:
                _list_out(s, account, section, source, done, SectionStatus.KEPT_OUT)
            _keep_out(s, account, section, done)
        elif item.pending:
            if item.move.target is SectionTarget.OWN:
                _pending_to_own(s, account, section, item.move, done, added_by_id)
            else:
                _pending_into(s, account, section, target, done, as_season=item.move.target is SectionTarget.MAIN)
        elif section.kind == SectionKind.FEED:
            if item.move.target is SectionTarget.OWN:
                _feed_to_own(s, account, section, source, done, added_by_id)
            elif item.move.target is SectionTarget.EXCLUDE:
                _feed_out(s, account, section, source, done)
            else:
                _feed_into(s, account, section, source, target, done)
        elif item.move.target is SectionTarget.OWN:
            _list_to_own(s, account, section, source, done, added_by_id)
        elif item.move.target is SectionTarget.EXCLUDE:
            _list_out(s, account, section, source, done)
        elif target is source:
            _list_regrouped(s, account, section, source, done, as_season=item.move.target is SectionTarget.MAIN)
        else:
            _list_into(s, account, section, source, target, done, as_season=item.move.target is SectionTarget.MAIN)
        s.flush()
        s.expire(account, ["main_collection", "gathering"])
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
    listed: Mapping[int, tuple[ItemRef, ...]] | None = None,
) -> None:
    """Move the creator's feeds and lists, with their videos, then number the videos of every collection that gained
    or lost some again, rename their files and rewrite their metadata. ``renumber`` says, by collection slug, which
    collections keep their numbers instead. ``listed`` has what the skipped lists among them have, from
    ``list_skipped``.

    ``s`` is a write transaction's session."""
    # Every operation and task the move starts is a part of one operation for the whole move, which tells the user
    # when it is done and shows its progress on the creator's page.
    with spun_off_work(s) as work:
        done = _apply(s, creator, moves, added_by_id=added_by_id, listed=listed)
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

    # Each collection whose links changed is listed again once, however many feeds and lists it gained or lost.
    for collection_id in sorted(done.synced - done.dropping):
        collection = s.get(Collection, collection_id)
        if collection is not None:
            reindex_collection(s, collection)
    for collection_id in sorted(done.result.sources):
        queue_task_after_commit(s, def_key="remove_left_episodes", resource_type="collection", resource_id=collection_id)
    for collection_id in sorted(done.touched - done.dropping):
        collection = s.get(Collection, collection_id)
        if collection is None:
            continue
        again = _numbered_again(collection, renumber)
        if collection_id in done.result.rename or (again and plan_identification(
            s, collection, EpisodeIdentifier(collection.episode_identifier),
        ).identifiers):
            queue_renumber(s, collection, renumber=again, sections=sorted({
                flow.section_key for flow in done.flows
                if collection_id in (flow.source_id, flow.target_id) and flow.section_key is not None
            }))
    for collection_id in done.new:
        collection = s.get(Collection, collection_id)
        if collection is not None:
            # The feed or list it was made of says how many videos it has, which its indexing weighs.
            expected = s.scalar(select(CreatorSection.item_count).where(CreatorSection.url == collection.sharing_url))
            index_new_collection(s, collection, expected_videos=expected)


def as_one_operation(
    s: Session, creator: Creator, work, sections: Sequence[CreatorSection], *, names: Names | None = None,
) -> None:
    """Make the operations and tasks ``work`` gathered the parts of one "creator.move_sections" operation, which tells
    the user when the whole move is done, named by the feeds and lists that moved, or by ``names`` when given."""
    if not work.operations and not work.tasks:
        return
    for operation in work.operations:
        operation.source = OperationSource.SYSTEM.value
    dispatch_operation_targets(s, create_operation(s, CreatorMoveSectionsOperation(
        creator, parts=work.operations, tasks=work.tasks,
        sections=[f"{section.account_id}:{section.ref}" for section in sections],
        names=names or section_type_names(section.section_type for section in sections),
    )))


@dataclass(frozen=True)
class MovedPart:
    """The videos of one feed or list that leave a collection or join it."""

    section_title: str
    section_kind: SectionKind
    names: Names
    direction: str
    """out, to another collection; in, from another one; leave, out of the Library; or within the collection,
    season, into a season of their list's own, loose, from it to where the videos in no list go, or moved, to the
    season the collection's lists put them in now, named by ``other_title``."""
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


def preview_section_moves(
    s: Session, creator: Creator, moves: Sequence[SectionMove], listed: Mapping[int, tuple[ItemRef, ...]] | None = None,
) -> SectionMovesPreview:
    """What saving the moves does, collection by collection: the moves are made and rolled back. ``listed`` is as for
    ``move_sections``.

    ``s`` is a write transaction's session; it is rolled back."""
    titles = {collection.id: (collection.slug, collection.title, collection.type) for collection in creator.collections}
    before = snapshot(s, creator.collections)
    done = _apply(s, creator, moves, added_by_id=None, listed=listed)
    return preview(s, titles, before, done)


def preview(
    s: Session, titles: dict[int, tuple[str, str, str]], before: dict[int, _Before], done: _Moves,
) -> SectionMovesPreview:
    """What ``done`` did to each collection it touched, from the videos ``before`` it, and rolls it all back.
    ``titles`` has the slug, title and type of each collection before."""
    s.flush()
    s.expire_all()
    after = {
        collection_id: collection for collection_id in done.touched
        if (collection := s.get(Collection, collection_id)) is not None
    }
    for collection_id in done.new:
        collection = s.get(Collection, collection_id)
        titles[collection_id] = (collection.slug, collection.title, collection.type)
    parts: dict[int, list[MovedPart]] = {}
    for flow in done.flows:
        items = [before[episode_id] for episode_id in flow.episode_ids if episode_id in before]
        if not items:
            continue
        common = dict(section_title=flow.title, section_kind=flow.kind, names=flow.names,
                      count=len(items), examples=_newest_first(items))
        if flow.target_id is None:
            deleted = [download for item in items for download in item.downloads]
            parts.setdefault(flow.source_id, []).append(MovedPart(
                direction="leave", other_title=None, downloads_deleted=len(deleted),
                kept_deleted=sum(1 for _name, kept in deleted if kept),
                deleting_profiles=sorted({name for name, _kept in deleted}), **common,
            ))
            continue
        if flow.target_id == flow.source_id and flow.to_season is not None:
            # They go to the season the collection's lists put them in now.
            parts.setdefault(flow.source_id, []).append(MovedPart(
                direction="moved", other_title=flow.to_season, files_moved=flow.files_moved, **common,
            ))
            continue
        if flow.target_id == flow.source_id:
            # The list became a season of its own, or stopped being one.
            parts.setdefault(flow.source_id, []).append(MovedPart(
                direction="season" if flow.section is not None and flow.section.ref in done.seasoned else "loose",
                other_title=None, files_moved=flow.files_moved, **common,
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
        if collection is None or collection_id in done.dropping:
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
    "CollectionMovePreview", "MovedPart", "SectionMove", "SectionMovesPreview", "drop_skipped_collection", "move_sections", "place_of",
    "preview_section_moves", "list_skipped", "lists_to_list",
]
