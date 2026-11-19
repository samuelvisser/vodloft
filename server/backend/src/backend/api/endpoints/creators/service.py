from __future__ import annotations

import contextvars
import logging
import threading
import time

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.api.models.collection_seasons import ReassignedMoveAPIRead
from backend.services.reassigned import move_and_rename, reassigned_in_creator
from backend.api.models.creator import (
    CreatorAPICreate, CreatorAPIRead, CreatorAPIUpdate, CreatorCombineAPIIn, CreatorLookupAPIRead, CreatorPageAPIRead,
    CreatorSectionMoveAPIIn, CreatorSectionsAPIAdd, CollectionCreatorLeaveAPIRead, CollectionCreatorMatchAPIRead,
    CreatorEpisodeAPIRead, CreatorEpisodePageAPIRead,
)
from backend.api.pagination import InvalidCursorError, decode_cursor, encode_cursor
from backend.api.models.collection import CollectionAPIRead
from backend.api.endpoints.episodes.service import episode_view_columns
from backend.app import db_session
from backend.api.endpoints.movies.service import add_movies
from backend.db.models import Creator, CreatorAccount, Collection, Episode, Movie
from backend.services import creators
from backend.services.creators import NewCollectionSettings, SectionPlan
from backend.services.errors import ServiceError
from backend.services.sites import collection_site
from backend.types.creator_types import NewSectionAction, SectionTarget
from task_manager.scheduler.transactional import queue_task_after_commit
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from sources import CreatorDetails, CreatorSectionNames, Feature, SectionRef, get_source
from backend.services.source_requests import asking_source


logger = logging.getLogger(__name__)


class CreatorNotFoundError(LookupError):
    pass


def lookup_creator_label(source_key: str, url: str | None) -> str:
    """What the Site of a creator about to be looked up calls it, told without a network request."""
    if url:
        return creators.creator_site(source_key, url).creator_label
    source = get_source(source_key)
    return next((site.creator_label for site in source.sites if site.creators), "creator")


# A creator's lookup takes seconds. Looking a creator up takes what a lookup of the same creator started in the last
# minute found, such as the lookup VODLoft starts when a pasted link turns out to be a creator, or waits for it while
# it runs. Adding the creator uses its lookup's id instead, see ``lookups``.
_FRESH_SECONDS = 60
_lookups: dict[tuple[str, str], tuple[float, Future]] = {}
_lookups_lock = threading.Lock()
_ahead = ThreadPoolExecutor(max_workers=2, thread_name_prefix="creator-lookup")


def _shared(key: tuple[str, str], work: Callable[[], CreatorDetails]) -> CreatorDetails:
    """What ``work`` finds, or what a lookup of the same creator started in the last minute found or will find."""
    now = time.monotonic()
    with _lookups_lock:
        for old in [old for old, (at, future) in _lookups.items() if now - at >= _FRESH_SECONDS and future.done()]:
            del _lookups[old]
        found = _lookups.get(key)
        if found is not None and now - found[0] < _FRESH_SECONDS:
            future, mine = found[1], False
        else:
            future, mine = Future(), True
            _lookups[key] = (now, future)
    if not mine:
        return future.result()
    try:
        details = work()
    except BaseException as exc:
        with _lookups_lock:
            if _lookups.get(key, (0, None))[1] is future:
                # A lookup that failed is tried again by the next one.
                del _lookups[key]
        future.set_exception(exc)
        raise
    future.set_result(details)
    return details


def look_up_creator(
    source_key: str, url: str | None, ref: str | None, progress: Callable[[str], None] = lambda step: None,
) -> CreatorDetails:
    """Ask the Source for the creator, telling ``progress`` what it is doing. Slow: call it outside a transaction."""
    if url:
        creators.creator_site(source_key, url)
    elif not ref:
        raise ServiceError("Give the creator's link", field="url")
    return _shared((source_key, url or ref), lambda: get_source(source_key).creator_details(url or ref, progress))


def look_up_creator_ahead(source_key: str, url: str) -> None:
    """Start looking up the creator a pasted link is, so that it is found by the time the user chooses to add them."""
    def look_up():
        try:
            look_up_creator(source_key, url, None)
        except Exception as exc:  # The user's own lookup tries again, and says what went wrong.
            logger.info("Could not look up the creator at %s ahead: %s", url, exc)

    _ahead.submit(contextvars.copy_context().run, look_up)


@dataclass(frozen=True)
class _Section:
    section: SectionRef
    collection_slug: str | None = None
    collection_title: str | None = None
    movie: Movie | None = None
    creator_id: int | None = None

    @property
    def movie_slug(self) -> str | None:
        return self.movie.slug if self.movie is not None else None

    @property
    def movie_title(self) -> str | None:
        return self.movie.title if self.movie is not None else None

    @property
    def movie_joined(self) -> bool:
        return self.movie is not None and self.creator_id is not None and self.movie.creator_id == self.creator_id

    def __getattr__(self, name):
        return getattr(self.section, name)


@dataclass(frozen=True)
class _Preset:
    key: str
    plan: list[SectionPlan]
    music_plan: list[SectionPlan]


@dataclass
class _Lookup:
    details: CreatorDetails
    source_key: str
    site_key: str
    site_name: str
    creator_label: str
    creator_sections: CreatorSectionNames
    link_seasons: bool
    movies: bool
    sections: list[_Section]
    presets: list[_Preset]
    creator_slug: str | None = None
    links: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    def __getattr__(self, name):
        return getattr(self.details, name)


def creator_lookup(s: Session, source_key: str, details: CreatorDetails) -> CreatorLookupAPIRead:
    site = creators.creator_site(source_key, details.url) if details.url else get_source(source_key).sites[0]
    kept = creators.sections_in_library(s, source_key, details.ref, details.sections)
    titles = dict(s.execute(select(Collection.slug, Collection.title).where(Collection.slug.in_(kept.values()))).all())
    movies = creators.takes_movies(source_key)
    movies_kept = creators.movies_in_library(s, source_key, details.sections)
    existing = creators.account_in_library(s, site.key, details.ref)
    return CreatorLookupAPIRead.model_validate(_Lookup(
        details=details, source_key=source_key, site_key=site.key, site_name=site.name,
        creator_label=site.creator_label, creator_sections=site.creator_sections,
        link_seasons=creators.lists_are_seasons(site), movies=movies,
        sections=[
            _Section(section, kept.get(section.ref), titles.get(kept.get(section.ref)), movies_kept.get(section.ref))
            for section in details.sections
        ],
        presets=[
            _Preset(
                preset.value, creators.preset_plan(details, preset, movies=movies, movies_in_library=movies_kept),
                # A music artist on a site with videos keeps their albums, not all of their uploads.
                creators.preset_plan(details, preset, feeds=site.audio, movies=movies, movies_in_library=movies_kept),
            )
            for preset in site.creator_presets
        ],
        creator_slug=existing.creator.slug if existing is not None else None,
        links=list(details.links), facts=list(details.facts),
    ))


def _collection_type(body: CreatorAPICreate, details: CreatorDetails) -> CollectionType:
    """What the creator's collections are. An artist's hold their music. Where the Site is sure whether the creator is
    an artist, it decides; elsewhere the user did, by the type they add the creator with."""
    if not details.music_known:
        return CollectionType(body.type)
    if details.music:
        return CollectionType.MUSIC
    if CollectionType(body.type) is CollectionType.MUSIC:
        raise ServiceError(f"{details.title} isn't a music artist", field="type")
    return CollectionType(body.type)


def creator_movies_to_add(body: CreatorAPICreate, details: CreatorDetails) -> list[str]:
    """The creator's movies that adding them puts in the Library, read before the Source looks them up."""
    with db_session() as s:
        return creators.movies_to_add(s, body.source_key, details.sections, _plans(body))


def _plans(body: CreatorAPICreate | CreatorSectionsAPIAdd) -> list[SectionPlan]:
    return [
        SectionPlan(
            plan.ref, SectionTarget(plan.target), CollectionType(plan.type) if plan.type else None,
            EpisodeIdentifier(plan.episode_identifier) if plan.episode_identifier else None,
        )
        for plan in body.sections
    ]


def add_creator(
    s: Session, body: CreatorAPICreate, details: CreatorDetails, *, added_by_id: int | None,
    movies: Sequence[object] = (),
) -> CreatorPageAPIRead:
    """Add the creator, with ``movies``, the Source's records of the movies it adds, looked up before."""
    into = None
    if body.into:
        into = s.scalar(select(Creator).where(Creator.slug == body.into))
        if into is None:
            raise ServiceError("This creator is not in the Library", field="into")
    add_movies(s, list(movies))
    creator, _collections = creators.add_creator(
        s, source_key=body.source_key, details=details,
        plans=_plans(body),
        settings=NewCollectionSettings(
            _collection_type(body, details), EpisodeIdentifier(body.episode_identifier),
            body.membership_level,
        ),
        added_by_id=added_by_id, new_sections=NewSectionAction(body.new_sections), into=into,
    )
    s.flush()
    return creator_page(s, creator.slug)


def _counts(s: Session, creator_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    collections = dict(s.execute(
        select(Collection.creator_id, func.count()).where(Collection.creator_id.in_(creator_ids)).group_by(Collection.creator_id)
    ).all())
    episodes = dict(s.execute(
        select(Collection.creator_id, func.count(Episode.id)).join(Episode, Episode.collection_id == Collection.id)
        .where(Collection.creator_id.in_(creator_ids)).group_by(Collection.creator_id)
    ).all())
    return collections, episodes


@dataclass
class _AccountRead:
    account: CreatorAccount
    sections: list
    movies: bool = False

    def __getattr__(self, name):
        return getattr(self.account, name)


@dataclass
class _CreatorRead:
    creator: Creator
    collection_count: int
    episode_count: int
    collections: list = field(default_factory=list)
    movies: list = field(default_factory=list)
    accounts: list | None = None
    reassigned_count: int = 0
    last_published_date: datetime | None = None

    @property
    def creator_label(self) -> str:
        return creators.creator_label(self.creator)

    @property
    def section_names(self):
        return creators.creator_sections(self.creator)

    @property
    def kind(self) -> str:
        return creators.creator_kind(self.creator)

    def __getattr__(self, name):
        if name == "accounts":
            return self.creator.accounts
        return getattr(self.creator, name)

    def __post_init__(self):
        if self.accounts is None:
            self.accounts = list(self.creator.accounts)


def list_creators(s: Session) -> list[CreatorAPIRead]:
    rows = list(s.scalars(
        select(Creator).order_by(Creator.title).options(selectinload(Creator.accounts), selectinload(Creator.collections))
    ))
    collections, episodes = _counts(s, [creator.id for creator in rows])
    return [
        CreatorAPIRead.model_validate(_CreatorRead(creator, collections.get(creator.id, 0), episodes.get(creator.id, 0)))
        for creator in rows
    ]


@dataclass(frozen=True)
class _CollectionRead:
    collection: Collection
    episode_count: int
    first_published_date: datetime | None
    last_published_date: datetime | None
    links: list[str]

    @property
    def years(self) -> str:
        if self.first_published_date is None or self.last_published_date is None:
            return ""
        return f"{self.first_published_date.year}-{self.last_published_date.year}"

    def __getattr__(self, name):
        return getattr(self.collection, name)


def creator_page(s: Session, slug: str) -> CreatorPageAPIRead:
    creator = s.scalar(
        select(Creator).where(Creator.slug == slug)
        .options(selectinload(Creator.accounts).selectinload(CreatorAccount.sections), selectinload(Creator.collections))
    )
    if creator is None:
        raise CreatorNotFoundError(f"Creator '{slug}' not found")
    collections_count, episodes = _counts(s, [creator.id])
    collection_ids = [c.id for c in creator.collections]
    stats = {
        row.collection_id: row for row in s.execute(
            select(
                Episode.collection_id, func.count().label("episode_count"),
                func.min(Episode.published_date).label("first"), func.max(Episode.published_date).label("last"),
            ).where(Episode.collection_id.in_(collection_ids)).group_by(Episode.collection_id)
        )
    }
    kept = {
        account.id: creators.sections_in_library(
            s, account.source_key, account.site_ref, account.sections, account.main_collection,
        )
        for account in creator.accounts
    }
    slugs = {slug for found in kept.values() for slug in found.values()}
    titles = dict(s.execute(select(Collection.slug, Collection.title).where(Collection.slug.in_(slugs))).all())
    movies_kept = {
        account.id: creators.movies_in_library(s, account.source_key, account.sections) for account in creator.accounts
    }
    collections = [
        _CollectionRead(
            collection, stats[collection.id].episode_count if collection.id in stats else 0,
            stats[collection.id].first if collection.id in stats else None,
            stats[collection.id].last if collection.id in stats else None,
            [
                section.title for account in creator.accounts for section in account.sections
                if kept[account.id].get(section.ref) == collection.slug
            ],
        )
        for collection in sorted(creator.collections, key=lambda c: c.created_at or c.id)
    ]
    accounts = [
        _AccountRead(account, [
            _Section(
                section, kept[account.id].get(section.ref), titles.get(kept[account.id].get(section.ref)),
                movies_kept[account.id].get(section.ref), creator.id,
            )
            for section in account.sections
        ], creators.takes_movies(account.source_key))
        for account in creator.accounts
    ]
    return CreatorPageAPIRead.model_validate(_CreatorRead(
        creator, collections_count.get(creator.id, 0), episodes.get(creator.id, 0),
        collections=collections, accounts=accounts,
        movies=sorted(creator.movies, key=lambda movie: (movie.release_date or movie.published_at or datetime.min).isoformat(), reverse=True),
        reassigned_count=len(reassigned_in_creator(s, creator)),
        last_published_date=max((row.last for row in stats.values() if row.last is not None), default=None),
    ))


def creator_episodes(s: Session, slug: str, *, cursor: str | None, limit: int) -> CreatorEpisodePageAPIRead:
    """One page of the episodes of all of the creator's collections, newest first, and those without a date last."""
    creator_id = s.scalar(select(Creator.id).where(Creator.slug == slug))
    if creator_id is None:
        raise CreatorNotFoundError(f"Creator '{slug}' not found")
    stmt = (
        select(*episode_view_columns(), Collection.slug.label("collection_slug"), Collection.title.label("collection_title"))
        .join(Collection, Episode.collection_id == Collection.id)
        .where(Collection.creator_id == creator_id)
        .order_by(Episode.published_date.desc().nulls_last(), Episode.id.desc())
    )
    if cursor:
        values = decode_cursor(cursor)
        cursor_id, published_raw = values.get("id"), values.get("published_at")
        if (
            values.get("kind") != "creator-episodes" or values.get("creator") != slug
            or not isinstance(cursor_id, int) or isinstance(cursor_id, bool)
            or (published_raw is not None and not isinstance(published_raw, str))
        ):
            raise InvalidCursorError("Cursor does not match this list")
        if published_raw is None:
            stmt = stmt.where(Episode.published_date.is_(None), Episode.id < cursor_id)
        else:
            published_at = datetime.fromisoformat(published_raw)
            stmt = stmt.where(or_(
                Episode.published_date < published_at,
                and_(Episode.published_date == published_at, Episode.id < cursor_id),
                Episode.published_date.is_(None),
            ))
    rows = s.execute(stmt.limit(limit + 1)).mappings().all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor({
            "kind": "creator-episodes", "creator": slug, "id": last["id"],
            "published_at": last["published_date"].isoformat() if last["published_date"] else None,
        })
    return CreatorEpisodePageAPIRead(
        items=[CreatorEpisodeAPIRead.model_validate(row) for row in rows], limit=limit, next_cursor=next_cursor,
    )


def move_creator_section(
    s: Session, slug: str, account_id: int, ref: str, body: CreatorSectionMoveAPIIn, *, added_by_id: int | None,
) -> CreatorPageAPIRead:
    """Move one of the playlists of a creator's account, with its videos and their files, and show the creator again.

    ``s`` is a write transaction's session."""
    from backend.services.section_moves import move_section

    move_section(s, _account(s, slug, account_id), ref, SectionTarget(body.target), added_by_id=added_by_id)
    s.flush()
    s.expire_all()
    return creator_page(s, slug)


def move_creator_reassigned(s: Session, slug: str) -> ReassignedMoveAPIRead:
    """Move every reassigned video of the creator to the collection it belongs in now, with its files.

    ``s`` is a write transaction's session."""
    result, operations = move_and_rename(s, reassigned_in_creator(s, _creator(s, slug)))
    s.flush()
    return ReassignedMoveAPIRead(
        episodes=result.episodes, renamed=result.renamed, downloading=result.downloading, operation_ids=operations,
    )


def _creator(s: Session, slug: str) -> Creator:
    creator = s.scalar(select(Creator).where(Creator.slug == slug))
    if creator is None:
        raise CreatorNotFoundError(f"Creator '{slug}' not found")
    return creator


def _account(s: Session, slug: str, account_id: int) -> CreatorAccount:
    account = next((account for account in _creator(s, slug).accounts if account.id == account_id), None)
    if account is None:
        raise CreatorNotFoundError(f"Creator '{slug}' has no account {account_id}")
    return account


def update_creator(s: Session, slug: str, body: CreatorAPIUpdate) -> CreatorPageAPIRead:
    creator = _creator(s, slug)
    title = (body.title or "").strip()
    if title and title != creator.title:
        creators.rename_creator(creator, title)
        creator.title_from_user = True
    creators.update_creator_settings(s, creator, creators.CreatorSettings(
        NewSectionAction(body.new_sections), body.genre, body.content_rating,
    ))
    s.flush()
    return creator_page(s, slug)


def account_movies_to_add(slug: str, account_id: int, body: CreatorSectionsAPIAdd) -> tuple[str, list[str]]:
    """The Source of one of the creator's accounts and the movies that adding the sections puts in the Library,
    read before the Source looks them up."""
    with db_session() as s:
        account = _account(s, slug, account_id)
        return account.source_key, creators.movies_to_add(s, account.source_key, account.sections, _plans(body))


def add_sections(
    s: Session, slug: str, account_id: int, body: CreatorSectionsAPIAdd, *, added_by_id: int | None,
    movies: Sequence[object] = (),
) -> CreatorPageAPIRead:
    add_movies(s, list(movies))
    creators.place_sections(
        s, _account(s, slug, account_id), _plans(body),
        added_by_id=added_by_id,
        type=CollectionType(body.type) if body.type else None,
        episode_identifier=EpisodeIdentifier(body.episode_identifier) if body.episode_identifier else None,
    )
    s.flush()
    return creator_page(s, slug)


def account_link(s: Session, slug: str, account_id: int) -> tuple[str, str]:
    """The Source and the link or id that look one of the creator's accounts up, read before the slow lookup."""
    account = _account(s, slug, account_id)
    return account.source_key, account.url or account.site_ref


def look_up_account(source_key: str, ref: str) -> CreatorDetails | None:
    """Who the account is at its Site now, or None when the Site can't say. Slow: call it outside a transaction."""
    try:
        return get_source(source_key).creator_details(ref)
    except Exception:  # The account splits off all the same, named after the creator it leaves.
        logger.warning("Could not look up creator account %s at %s", ref, source_key, exc_info=True)
        return None


def split_creator_account(s: Session, slug: str, account_id: int, details: CreatorDetails | None) -> CreatorPageAPIRead:
    """Make one of the creator's accounts a creator of their own again, and show that creator.

    ``s`` is a write transaction's session."""
    own = creators.split_account(s, _account(s, slug, account_id), details)
    s.expire_all()
    return creator_page(s, own.slug)


def combine_creator(s: Session, slug: str, body: CreatorCombineAPIIn) -> CreatorPageAPIRead:
    """Make another creator in the Library a part of this one, and show this creator again.

    ``s`` is a write transaction's session."""
    creator = _creator(s, slug)
    other = s.scalar(select(Creator).where(Creator.slug == body.other_slug))
    if other is None:
        raise ServiceError("This creator is not in the Library", field="other_slug")
    creators.combine_creators(s, creator, other)
    s.expire_all()
    return creator_page(s, slug)


def delete_creator(s: Session, slug: str) -> None:
    """Take the creator out of the Library, and keep its collections as plain ones.

    ``s`` is a write transaction's session."""
    creators.delete_creator(s, _creator(s, slug))


def check_creator(s: Session, slug: str) -> None:
    """Look for the creator's new sections now, as the daily look does."""
    creator = _creator(s, slug)
    queue_task_after_commit(s, def_key=creators.FOLLOW_TASK_KEY, resource_type="creator", resource_id=creator.id)


class CollectionNotFoundError(LookupError):
    pass


def _collection(s: Session, slug: str) -> Collection:
    collection = s.scalar(select(Collection).where(Collection.slug == slug))
    if collection is None:
        raise CollectionNotFoundError(f"Collection '{slug}' not found")
    return collection


@dataclass(frozen=True)
class CollectionLink:
    source_key: str
    title: str
    url: str


def collection_link(s: Session, collection_slug: str) -> CollectionLink:
    """What looking up the creator behind a collection needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if collection.creator_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.creator.title}")
    if collection.sharing_url is None:
        raise ServiceError(f"{collection.title} has no link of its own, so it belongs to no creator")
    return CollectionLink(collection.source_key, collection.title, collection.sharing_url)


def look_up_collection_creator(
    link: CollectionLink, progress: Callable[[str], None] = lambda step: None,
) -> CreatorDetails:
    """The creator behind the collection's link, asked of its Source, telling ``progress`` what it is doing. Slow: call
    it outside a transaction."""
    source = get_source(link.source_key)
    if not source.has(Feature.CREATORS):
        raise ServiceError(f"{source.name} has no creators")
    site = source.site_for(link.url)
    label = site.creator_label if site is not None else "creator"
    progress(f"Finding the {label} behind the link")
    with asking_source(f"Could not look up the {label}"):
        ref = source.creator_of(link.url)
    if ref is None:
        raise ServiceError(f"VODLoft found no {label} behind the link of {link.title}")
    with asking_source(f"Could not look up the {label}"):
        return source.creator_details(ref, progress)


@dataclass
class _Match:
    details: CreatorDetails
    site_name: str
    creator_label: str
    section_names: object
    section: object | None
    kept_by: str | None
    creator_slug: str | None = None
    overlaps: list = field(default_factory=list)

    def __getattr__(self, name):
        return getattr(self.details, name)


def collection_creator_match(s: Session, collection_slug: str, source_key: str, details: CreatorDetails) -> CollectionCreatorMatchAPIRead:
    collection = _collection(s, collection_slug)
    site = creators.creator_site(source_key, details.url or collection.site_key or get_source(source_key).sites[0].key)
    existing = creators.account_in_library(s, site.key, details.ref)
    section, keeper = creators.collection_section(s, collection, source_key, details, existing)
    overlaps = creators.join_overlaps(s, collection, source_key, details, existing)
    movable = keeper is not None and any(overlap.ref == section.ref and overlap.can_move_here for overlap in overlaps)
    return CollectionCreatorMatchAPIRead.model_validate(_Match(
        details, site.name, site.creator_label, site.creator_sections, section if keeper is None or movable else None,
        keeper.title if keeper is not None and not movable else None,
        existing.creator.slug if existing is not None else None,
        overlaps,
    ))


def join_collection_creator(
    s: Session, collection_slug: str, source_key: str, details: CreatorDetails, *, added_by_id: int | None,
    move_here: frozenset[str] = frozenset(),
) -> CollectionAPIRead:
    collection = _collection(s, collection_slug)
    creators.join_creator(
        s, collection, source_key=source_key, details=details, added_by_id=added_by_id, move_here=move_here,
    )
    s.flush()
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)


def add_collection_to_creator(s: Session, collection_slug: str, creator_slug: str) -> CollectionAPIRead:
    """Add the collection to a creator in the Library that its link is not on."""
    collection = _collection(s, collection_slug)
    creator = s.scalar(select(Creator).where(Creator.slug == creator_slug))
    if creator is None:
        raise ServiceError("This creator is not in the Library", field="creator_slug")
    creators.add_to_creator(s, collection, creator)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)


def collection_creator_leave(s: Session, collection_slug: str) -> CollectionCreatorLeaveAPIRead:
    collection = _collection(s, collection_slug)
    if collection.creator is None:
        raise ServiceError(f"{collection.title} is not in a {collection_site(collection).creator_label}")
    return CollectionCreatorLeaveAPIRead(creator_title=collection.creator.title)


def leave_collection_creator(s: Session, collection_slug: str) -> CollectionAPIRead:
    collection = _collection(s, collection_slug)
    creators.leave_creator(s, collection)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)
