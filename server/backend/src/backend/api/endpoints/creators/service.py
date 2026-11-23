"""The creators API: the Library's creators, their pages, and grouping collections under them."""
from __future__ import annotations

import logging
import threading
import time

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from backend.api.models.creator import (
    CollectionCreatorMatchAPIRead, CreatorAPIRead, CreatorAPIUpdate, CreatorCombineAPIIn, CreatorEpisodeAPIRead,
    CreatorEpisodePageAPIRead, CreatorMoviesAPIAdd, CreatorOfferingsAPIRead, CreatorPageAPIRead,
)
from backend.api.pagination import InvalidCursorError, decode_cursor, encode_cursor
from backend.api.models.collection import CollectionAPIRead
from backend.api.endpoints.episodes.service import episode_view_columns
from backend.api.endpoints.movies.service import add_movies
from backend.db.models import Creator, CreatorAccount, Collection, Episode
from backend.services import creators
from backend.services.errors import ServiceError
from backend.services.link_seasons import link_seasons_on, loose_in_one_season, loose_season_name
from backend.services.sites import collection_site
from progress_plan import PlanSnapshot, PlanTracker, StageSpec
from sources import CreatorDetails, Feature, Names, SectionRef, SectionType, Site, get_source
from backend.services.source_requests import asking_source


logger = logging.getLogger(__name__)


class CreatorNotFoundError(LookupError):
    pass


class LookupPlan:
    """The plan a creator lookup reports while it runs: the Site's own steps of looking the creator up, between the
    steps taken around them, such as finding the creator behind a collection's link before and checking the library
    after."""

    def __init__(self, sink: Callable[[PlanSnapshot], None] | None = None) -> None:
        self._sink = sink
        self._lock = threading.RLock()
        self._site = PlanSnapshot(())
        # How many of the steps around the Site's go before them, once the Site's lookup has begun.
        self._before: int | None = None
        self._own = PlanTracker(sink=lambda _snapshot: self._emit())

    def step(self, id: str, label: str):
        """Runs a step of the lookup's own for as long as the block does."""
        self._own.add(StageSpec(id=id, code=id, label=label))
        return self._own.running(id)

    def site(self, snapshot: PlanSnapshot) -> None:
        """The Site's plan of looking the creator up, as it is now."""
        with self._lock:
            if self._before is None:
                self._before = len(self._own.snapshot().stages)
            self._site = snapshot
            self._emit()

    def _emit(self) -> None:
        if self._sink is None:
            return
        with self._lock:
            own, site = self._own.snapshot(), self._site
            at = len(own.stages) if self._before is None else self._before
            own_running = own.main is not None and own.main.state in ("running", "waiting")
            main = own.main_activity if own_running or not site.stages else site.main_activity
            self._sink(PlanSnapshot(own.stages[:at] + site.stages + own.stages[at:], main))


# A creator's lookup takes seconds. Looking a creator up takes what a lookup of the same creator started in the last
# minute found, such as the one behind a collection's link and the creator's page offerings, or waits for it while it
# runs and follows its plan from where it is. Joining the creator uses its lookup's id instead, see ``lookups``.
_FRESH_SECONDS = 60


class _SiteLookup:
    """One lookup of a creator at its Site, by the Site's plan, which every lookup of the same creator while it is
    fresh follows."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.future: Future[CreatorDetails] = Future()
        self._lock = threading.Lock()
        self._followers: list[Callable[[PlanSnapshot], None]] = []
        self.plan = PlanTracker(sink=lambda _snapshot: self._tell())

    def _tell(self) -> None:
        with self._lock:
            snapshot = self.plan.snapshot()
            for follower in self._followers:
                follower(snapshot)

    def follow(self, follower: Callable[[PlanSnapshot], None]) -> None:
        """Tells ``follower`` the plan as it is now, and each time it changes."""
        with self._lock:
            follower(self.plan.snapshot())
            self._followers.append(follower)


_lookups: dict[tuple[str, str], _SiteLookup] = {}
_lookups_lock = threading.Lock()


def _shared(key: tuple[str, str], work: Callable[[PlanTracker], CreatorDetails], plan: LookupPlan | None) -> CreatorDetails:
    """What ``work`` finds by its plan, or what a lookup of the same creator started in the last minute found or will
    find, with ``plan`` following the plan of whichever lookup it is."""
    now = time.monotonic()
    with _lookups_lock:
        for old in [old for old, lookup in _lookups.items() if now - lookup.started >= _FRESH_SECONDS and lookup.future.done()]:
            del _lookups[old]
        lookup = _lookups.get(key)
        mine = lookup is None or now - lookup.started >= _FRESH_SECONDS
        if mine:
            lookup = _lookups[key] = _SiteLookup()
    if not mine and lookup.future.done():
        # Found already: there is nothing left to follow, so the lookup shows no steps.
        return lookup.future.result()
    if plan is not None:
        lookup.follow(plan.site)
    if not mine:
        return lookup.future.result()
    try:
        details = work(lookup.plan)
    except BaseException as exc:
        with _lookups_lock:
            if _lookups.get(key) is lookup:
                # A lookup that failed is tried again by the next one.
                del _lookups[key]
        lookup.future.set_exception(exc)
        raise
    lookup.future.set_result(details)
    return details


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

    @property
    def site(self) -> Site:
        return creators.account_site(self.account)

    @property
    def offers(self) -> bool:
        return creators.has_offerings(self.account)

    def __getattr__(self, name):
        return getattr(self.account, name)


@dataclass
class _CreatorRead:
    creator: Creator
    collection_count: int
    episode_count: int
    collections: list = field(default_factory=list)
    movies: list = field(default_factory=list)
    last_published_date: datetime | None = None

    @property
    def accounts(self) -> list[_AccountRead]:
        return [_AccountRead(account) for account in self.creator.accounts]

    @property
    def creator_names(self) -> Names:
        return creators.creator_names(self.creator)

    @property
    def music(self) -> bool:
        return creators.is_music_creator(self.creator)

    @property
    def kind(self) -> str:
        return creators.creator_kind(self.creator)

    @property
    def words(self):
        return creators.creator_words(self.creator)

    @property
    def open_count(self) -> int:
        """How often its page and its collections' pages were opened."""
        return self.creator.open_count + sum(collection.open_count for collection in self.creator.collections)

    @property
    def last_opened_at(self) -> datetime | None:
        """When its page or one of its collections' pages was last opened."""
        opened = [self.creator.last_opened_at, *(collection.last_opened_at for collection in self.creator.collections)]
        return max((at for at in opened if at is not None), default=None)

    def __getattr__(self, name):
        return getattr(self.creator, name)


def record_creator_opened(s: Session, slug: str) -> None:
    """Count one more opening of the creator's page, for the Library's Often used and Recently used orders."""
    opened = s.execute(
        update(Creator)
        .where(Creator.slug == slug)
        # Opening the page does not change the creator, so it keeps its last update time.
        .values(
            open_count=Creator.open_count + 1,
            last_opened_at=datetime.now(timezone.utc),
            updated_at=Creator.updated_at,
        )
    )
    if opened.rowcount == 0:
        raise CreatorNotFoundError(f"Creator '{slug}' not found")


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

    @property
    def years(self) -> str:
        if self.first_published_date is None or self.last_published_date is None:
            return ""
        return f"{self.first_published_date.year}-{self.last_published_date.year}"

    @property
    def loose_season(self) -> str | None:
        if not (link_seasons_on(self.collection) and loose_in_one_season(self.collection)):
            return None
        return loose_season_name(self.collection)

    @property
    def site(self) -> Site | None:
        return collection_site(self.collection) if self.collection.site_key else None

    def __getattr__(self, name):
        return getattr(self.collection, name)


def creator_page(s: Session, slug: str) -> CreatorPageAPIRead:
    creator = s.scalar(
        select(Creator).where(Creator.slug == slug)
        .options(selectinload(Creator.accounts), selectinload(Creator.collections), selectinload(Creator.movies))
    )
    if creator is None:
        raise CreatorNotFoundError(f"Creator '{slug}' not found")
    collections_count, episodes = _counts(s, [creator.id])
    stats = {
        row.collection_id: row for row in s.execute(
            select(
                Episode.collection_id, func.count().label("episode_count"),
                func.min(Episode.published_date).label("first"), func.max(Episode.published_date).label("last"),
            ).where(Episode.collection_id.in_([c.id for c in creator.collections])).group_by(Episode.collection_id)
        )
    }
    collections = [
        _CollectionRead(
            collection, stats[collection.id].episode_count if collection.id in stats else 0,
            stats[collection.id].first if collection.id in stats else None,
            stats[collection.id].last if collection.id in stats else None,
        )
        for collection in sorted(creator.collections, key=lambda c: c.created_at or c.id)
    ]
    return CreatorPageAPIRead.model_validate(_CreatorRead(
        creator, collections_count.get(creator.id, 0), episodes.get(creator.id, 0), collections=collections,
        movies=sorted(creator.movies, key=lambda movie: (movie.release_date or movie.published_at or datetime.min).isoformat(), reverse=True),
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


@dataclass(frozen=True)
class AccountLink:
    """What looking one of the creator's accounts up needs, read before the slow lookup."""

    account_id: int
    source_key: str
    ref: str
    site_key: str


def offering_accounts(s: Session, slug: str) -> list[AccountLink]:
    """The creator's accounts whose Site has more of their work than their channel, such as shows and movies."""
    return [
        AccountLink(account.id, account.source_key, account.url or account.site_ref, account.site_key)
        for account in _creator(s, slug).accounts if creators.has_offerings(account)
    ]


def look_up_account(link: AccountLink) -> CreatorDetails | None:
    """Who the account is at its Site now, or None when the Site can't say. Slow: call it outside a transaction."""
    try:
        return _shared((link.source_key, link.ref), lambda tracker: get_source(link.source_key).creator_details(link.ref, tracker), None)
    except Exception:  # The page shows the rest all the same.
        logger.warning("Could not look up creator account %s at %s", link.ref, link.source_key, exc_info=True)
        return None


@dataclass(frozen=True)
class _Offering:
    section: SectionRef
    collection: Collection | None
    movie: object | None
    creator_id: int

    @property
    def section_type(self) -> SectionType:
        return self.section.type

    @property
    def collection_slug(self) -> str | None:
        return self.collection.slug if self.collection is not None else None

    @property
    def collection_title(self) -> str | None:
        return self.collection.title if self.collection is not None else None

    @property
    def collection_joined(self) -> bool:
        return self.collection is not None and self.collection.creator_id == self.creator_id

    @property
    def movie_slug(self) -> str | None:
        return self.movie.slug if self.movie is not None else None

    @property
    def movie_title(self) -> str | None:
        return self.movie.title if self.movie is not None else None

    @property
    def movie_joined(self) -> bool:
        return self.movie is not None and self.movie.creator_id == self.creator_id

    def __getattr__(self, name):
        return getattr(self.section, name)


@dataclass(frozen=True)
class _AccountOfferings:
    account_id: int
    site: Site
    offerings: list[_Offering]


def creator_offerings(
    s: Session, slug: str, found: Sequence[tuple[AccountLink, CreatorDetails | None]],
) -> CreatorOfferingsAPIRead:
    """What each account's Site offers of the creator beside their channel, with what the Library has of it. Reading
    only."""
    creator = _creator(s, slug)
    accounts = []
    for link, details in found:
        if details is None:
            continue
        sections = creators.offered(details, link.source_key)
        kept = creators.collections_of(s, link.source_key, link.site_key, sections)
        movies = creators.movies_offered(s, link.source_key, sections)
        accounts.append(_AccountOfferings(
            link.account_id, creators.account_site(_account(s, slug, link.account_id)),
            [_Offering(section, kept.get(section.ref), movies.get(section.ref), creator.id) for section in sections],
        ))
    return CreatorOfferingsAPIRead.model_validate({"accounts": accounts})


def movies_to_add(s: Session, slug: str, account_id: int, body: CreatorMoviesAPIAdd) -> tuple[str, list[str]]:
    """The Source of one of the creator's accounts and those of the movies that are not in the Library yet, read
    before the Source looks them up."""
    account = _account(s, slug, account_id)
    if not creators.takes_movies(account.source_key):
        raise ServiceError(f"VODLoft can't add movies from {creators.account_site(account).name}", field="refs")
    in_library = creators.movies_in_library(s, account.source_key, body.refs)
    return account.source_key, [ref for ref in body.refs if ref not in in_library]


def add_creator_movies(
    s: Session, slug: str, account_id: int, body: CreatorMoviesAPIAdd, movies: Sequence[object],
) -> CreatorPageAPIRead:
    """Put the movies, looked up before, in the Library, and make them and the ones in it already the creator's.

    ``s`` is a write transaction's session."""
    creator = _creator(s, slug)
    account = _account(s, slug, account_id)
    add_movies(s, list(movies))
    creators.join_movies(s, creator, account.source_key, body.refs)
    s.flush()
    s.expire_all()
    return creator_page(s, slug)


def update_creator(s: Session, slug: str, body: CreatorAPIUpdate) -> CreatorPageAPIRead:
    creator = _creator(s, slug)
    title = (body.title or "").strip()
    if title and title != creator.title:
        creators.rename_creator(creator, title)
    creators.update_creator_settings(creator, genre=body.genre, content_rating=body.content_rating)
    s.flush()
    return creator_page(s, slug)


def account_link(s: Session, slug: str, account_id: int) -> AccountLink:
    """The Source and the link or id that look one of the creator's accounts up, read before the slow lookup."""
    account = _account(s, slug, account_id)
    return AccountLink(account.id, account.source_key, account.url or account.site_ref, account.site_key)


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


def delete_creator(s: Session, slug: str, *, with_collections: bool = False) -> None:
    """Take the creator out of the Library, and keep its collections and movies as they are, or delete its
    collections too.

    ``s`` is a write transaction's session."""
    remove_creator(s, _creator(s, slug), with_collections=with_collections)


def remove_creator(s: Session, creator: Creator, *, with_collections: bool) -> None:
    """Take ``creator`` out of the Library; ``with_collections`` deletes its collections as their Edit page does,
    and otherwise they stay as plain ones. ``s`` is a write transaction's session."""
    if with_collections:
        # The collections package imports this module, so its service is imported here.
        from backend.api.endpoints.collections.service import delete_collection

        for collection in list(creator.collections):
            delete_collection(s, collection.slug)
        s.expire(creator, ["collections"])
    creators.delete_creator(s, creator)


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
    """What looking up the creator behind a channel collection needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if collection.creator_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.creator.title}")
    creators.check_joins(collection)
    return CollectionLink(collection.source_key, collection.title, collection.sharing_url)


def look_up_collection_creator(link: CollectionLink, plan: LookupPlan | None = None) -> CreatorDetails:
    """The creator behind the collection's link, asked of its Source the way the Add creator page asks it, reporting by
    ``plan``. Slow: call it outside a transaction."""
    plan = plan or LookupPlan()
    source = get_source(link.source_key)
    if not source.has(Feature.CREATORS):
        raise ServiceError(f"{source.name} has no creators")
    site = source.site_for(link.url)
    label = (site.creator_names if site is not None else Site.creator_names).singular
    with asking_source(f"Could not look up the {label}"), plan.step("find_creator", f"Finding the {label} behind the link"):
        ref = source.creator_of(link.url)
    if ref is None:
        raise ServiceError(f"VODLoft found no {label} behind the link of {link.title}")
    with asking_source(f"Could not look up the {label}"):
        return _shared((link.source_key, ref), lambda tracker: source.creator_details(ref, tracker), plan)


@dataclass
class _Match:
    details: CreatorDetails
    site_name: str
    creator_names: Names
    creator_slug: str | None = None
    creator_title: str | None = None

    def __getattr__(self, name):
        return getattr(self.details, name)


def collection_creator_match(s: Session, source_key: str, details: CreatorDetails) -> CollectionCreatorMatchAPIRead:
    """The creator behind a collection's link, and whether they are in the Library already. Reading only."""
    site = creators.creator_site(source_key, details.url or get_source(source_key).sites[0].key)
    existing = creators.account_of(s, source_key, details)
    creator = existing.creator if existing is not None else None
    return CollectionCreatorMatchAPIRead.model_validate(_Match(
        details, site.name, site.creator_names,
        creator.slug if creator is not None else None, creator.title if creator is not None else None,
    ))


def join_collection_creator(
    s: Session, collection_slug: str, source_key: str, details: CreatorDetails, *, added_by_id: int | None,
) -> CollectionAPIRead:
    """Group the collection under the creator behind its link, adding the creator when they are not in the Library.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    creators.join_creator_of(s, collection, source_key, details, added_by_id=added_by_id)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)


def add_collection_to_creator(s: Session, collection_slug: str, creator_slug: str) -> CollectionAPIRead:
    """Group the collection under a creator in the Library.

    ``s`` is a write transaction's session."""
    collection = _collection(s, collection_slug)
    creator = s.scalar(select(Creator).where(Creator.slug == creator_slug))
    if creator is None:
        raise ServiceError("This creator is not in the Library", field="creator_slug")
    creators.join_creator(s, collection, creator)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)


def leave_collection_creator(s: Session, collection_slug: str) -> CollectionAPIRead:
    collection = _collection(s, collection_slug)
    creators.leave_creator(s, collection)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)
