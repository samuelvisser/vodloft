"""The collection health check: VODLoft makes sure each collection is healthy by running every check below on it, every
night and whenever the user asks. The user can turn each check off (``checks_off``).

A collection stores its health itself (``Collection.healthy`` and ``health_issues``): what it needs the user for, by
the kind of issue, with how many things each concerns. VODLoft keeps that up to date as it works on a collection, such
as when it places its videos (``note_collection_health``), so Home and the Library only read it. A check works out one
kind of issue again from what the collection holds and sets right what drifted. A new check is a ``HealthCheck``
added to ``CHECKS``, with a kind of its own in ``HealthIssueKind`` and an issue that says what it found.

The creators check is not about one collection: it finds the creator behind each collection that is in no creator
(``find_site_creator``), and suggests grouping the collections of a creator that has several (``creator_suggestions``).
The user can put a suggestion off or dismiss it (``HealthDismissal``).
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.db.core import get_session, run_write_transaction, write_when_changed
from backend.db.models import Collection, CollectionList, CreatorAccount, HealthDismissal, Settings
from backend.services.link_seasons import moved_episodes, section_list_names, seasons_plan
from backend.services.move_causes import clear_move_causes
from backend.services.sites import collection_site, collection_words
from backend.services.source_options import ytdlp_call_options
from backend.types.collection_contracts import CollectionWords
from backend.types.collection_health_types import HealthIssueKind, HealthLevel, ISSUE_LEVELS
from backend.types.link_season_types import ListStatus
from sources import Feature, Names, get_source

logger = logging.getLogger(__name__)

SUGGEST_FROM = 3
"""How many collections of one creator, in no creator yet, make a suggestion to group them."""
LATER = timedelta(days=7)
"""How long Later puts a suggestion off."""


@dataclass(frozen=True)
class MovesIssue:
    """Downloads that the collection's season settings put in another season, which wait for its Move action."""

    count: int
    seasons_plan: str
    """Why they move: what the collection's settings make its seasons now, in words."""
    kind: HealthIssueKind = HealthIssueKind.MOVES
    level: HealthLevel = ISSUE_LEVELS[HealthIssueKind.MOVES]


@dataclass(frozen=True)
class NewListsIssue:
    """Lists the collection's channel added later, which wait for the user's choice in its Seasons dialog."""

    count: int
    names: Names
    """What the collection calls its lists, such as playlists."""
    kind: HealthIssueKind = HealthIssueKind.NEW_LISTS
    level: HealthLevel = ISSUE_LEVELS[HealthIssueKind.NEW_LISTS]


HealthIssue = MovesIssue | NewListsIssue
"""What one kind of issue tells the user."""


def _new_lists(s: Session, collection: Collection) -> int:
    return s.scalar(select(func.count()).select_from(CollectionList).where(
        CollectionList.collection_id == collection.id, CollectionList.status == ListStatus.NEW.value,
    )) or 0


@dataclass(frozen=True)
class HealthCheck:
    kind: HealthIssueKind
    title: str
    """What it checks, in words, for the task's summary, such as downloads to move."""
    count: Callable[[Session, Collection], int]
    """How many things of this kind need the user, worked out from what the collection holds. Reading only."""
    issue: Callable[[Collection, int], HealthIssue]
    """What the issue tells the user, from the stored count."""


CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        HealthIssueKind.MOVES, "downloads to move",
        lambda s, collection: len(moved_episodes(s, collection)),
        lambda collection, count: MovesIssue(count, seasons_plan(collection)),
    ),
    HealthCheck(
        HealthIssueKind.NEW_LISTS, "new lists to choose",
        _new_lists,
        lambda collection, count: NewListsIssue(count, section_list_names(collection)),
    ),
)
_BY_KIND = {check.kind.value: check for check in CHECKS}
TITLES = {**{check.kind.value: check.title for check in CHECKS}, HealthIssueKind.CREATORS.value: "creators to group"}


def checks_off(s: Session) -> set[str]:
    """The checks the user turned off, by kind. Reading only."""
    off = s.scalar(select(Settings.health_checks_off).order_by(Settings.id).limit(1))
    return set(off or ())


def set_check(s: Session, kind: HealthIssueKind, on: bool) -> None:
    """Turn one check on or off. A check that is off stores nothing; the next run of the health check clears what it
    stored before.

    ``s`` is a write transaction's session."""
    row = s.scalars(select(Settings).order_by(Settings.id).limit(1)).first()
    if row is None:
        row = Settings()
        s.add(row)
    off = set(row.health_checks_off or ()) - {kind.value}
    if not on:
        off.add(kind.value)
    row.health_checks_off = sorted(off)


def note_collection_health(s: Session, collection: Collection) -> bool:
    """Store on the collection's health what every check that is on finds, and nothing for one that is off. Returns
    whether that changed what it stored.

    ``s`` is a write transaction's session, or a read session that ``write_when_changed`` checks."""
    causes = list(collection.move_causes or ())
    return bool(_note_checks(s, collection)) or causes != list(collection.move_causes or ())


def _note_checks(s: Session, collection: Collection) -> list[str]:
    """Store what every check that is on finds. Returns the kinds whose stored health changed."""
    off = checks_off(s)
    changed = []
    for check in CHECKS:
        count = 0 if check.kind.value in off else check.count(s, collection)
        if collection.note_health(check.kind, count):
            changed.append(check.kind.value)
        if check.kind is HealthIssueKind.MOVES and check.kind.value not in off and not count:
            # Nothing waits for the Move action, so what made downloads wait is over.
            clear_move_causes(collection)
    return changed


@dataclass(frozen=True)
class CollectionHealth:
    """What the health check found on one collection, by the kinds of issue."""

    collection_id: int
    slug: str
    title: str
    needs_attention: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)
    """The kinds whose stored health was off, and is set right now."""

    @property
    def healthy(self) -> bool:
        return not self.needs_attention


def check_collection_health(collection_id: int) -> CollectionHealth | None:
    """Run every health check on the collection, and store its health. None when the collection is gone. Takes the
    writer's turn only when a check found the stored health off."""

    def work(s: Session) -> CollectionHealth | None:
        collection = s.get(Collection, collection_id)
        if collection is None:
            return None
        corrected = _note_checks(s, collection)
        if corrected:
            # Setting right what VODLoft stored does not change the collection, so it keeps its last update time.
            flag_modified(collection, "updated_at")
        return CollectionHealth(collection.id, collection.slug, collection.title, sorted(collection.health_issues), corrected)

    return write_when_changed(work)


@dataclass(frozen=True)
class UnhealthyCollection:
    """A collection that needs the user, with what for."""

    slug: str
    title: str
    words: CollectionWords
    """What it calls its seasons and episodes."""
    issues: list[HealthIssue]


def unhealthy_collections(s: Session) -> list[UnhealthyCollection]:
    """Every collection that needs the user, by title, as it stored its health. Reading only."""
    return [
        UnhealthyCollection(collection.slug, collection.title, collection_words(collection), [
            _BY_KIND[kind].issue(collection, count) for kind, count in sorted(collection.health_issues.items())
            if kind in _BY_KIND
        ])
        for collection in s.scalars(select(Collection).where(Collection.healthy.is_(False)).order_by(Collection.title))
    ]


# --- Creators ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _CreatorLookup:
    collection_id: int
    source_key: str
    url: str


def _needs_creator_lookup(s: Session, collection_id: int) -> _CreatorLookup | None:
    """What looking up the creator behind the collection's link needs, or None when there is nothing to look up: it is
    in a creator, has no link of its own, was looked up for this link already, or its Site has no creators."""
    collection = s.get(Collection, collection_id)
    if (
        collection is None or collection.creator_id is not None or collection.sharing_url is None
        or collection.site_creator_url == collection.sharing_url
    ):
        return None
    site = collection_site(collection)
    if not site.creators or not get_source(collection.source_key).has(Feature.CREATORS):
        return None
    return _CreatorLookup(collection.id, collection.source_key, collection.sharing_url)


def find_site_creator(collection_id: int) -> bool:
    """Find the creator behind the collection's link at its Site, and store it, when the collection is in no creator
    and was not looked up for this link yet. Slow: it may ask the Site. Returns whether it looked one up. A lookup
    that fails is tried again on the next run."""
    session = get_session()
    try:
        lookup = _needs_creator_lookup(session, collection_id)
    finally:
        session.rollback()
        session.close()
    if lookup is None:
        return False
    try:
        with ytdlp_call_options(lookup.source_key):
            ref = get_source(lookup.source_key).creator_of(lookup.url)
    except Exception as exc:  # noqa: BLE001 - a Site that fails now is asked again on the next run
        logger.warning("Could not find the creator behind %s: %s", lookup.url, exc)
        return False

    def store(w: Session) -> None:
        collection = w.get(Collection, collection_id)
        if collection is None or collection.sharing_url != lookup.url:
            return
        collection.site_creator_ref, collection.site_creator_url = ref, lookup.url
        flag_modified(collection, "updated_at")

    run_write_transaction(store, concurrent=True)
    return True


def creator_subject(site_key: str, ref: str) -> str:
    return f"{site_key}:{ref}"


@dataclass(frozen=True)
class SuggestedCollection:
    slug: str
    title: str


@dataclass(frozen=True)
class CreatorSuggestion:
    """Several collections of one creator that are in no creator yet, which the user can group under the creator."""

    site_key: str
    ref: str
    title: str
    """The creator's name, as their collections give it."""
    creator_names: Names
    """What the Site calls its creators."""
    site_name: str
    collections: list[SuggestedCollection]
    creator_slug: str | None = None
    """The creator in the Library already, when they are: the collections join them."""
    creator_title: str | None = None
    kind: HealthIssueKind = HealthIssueKind.CREATORS
    level: HealthLevel = ISSUE_LEVELS[HealthIssueKind.CREATORS]


def _suggested(s: Session) -> dict[tuple[str, str], list[Collection]]:
    rows = s.scalars(
        select(Collection).where(
            Collection.creator_id.is_(None), Collection.site_creator_ref.is_not(None),
            Collection.site_creator_url == Collection.sharing_url, Collection.site_key.is_not(None),
        ).order_by(Collection.title)
    ).all()
    groups: dict[tuple[str, str], list[Collection]] = {}
    for collection in rows:
        groups.setdefault((collection.site_key, collection.site_creator_ref), []).append(collection)
    return {key: collections for key, collections in groups.items() if len(collections) >= SUGGEST_FROM}


def _put_off(s: Session, now: datetime) -> set[str]:
    return set(s.scalars(select(HealthDismissal.subject).where(
        HealthDismissal.kind == HealthIssueKind.CREATORS.value,
        or_(HealthDismissal.until.is_(None), HealthDismissal.until > now),
    )))


def creator_suggestions(s: Session, now: datetime | None = None) -> list[CreatorSuggestion]:
    """Every creator with several collections in no creator, that the user did not put off or dismiss, as the
    collections stored their creator. None when the check is off. Reading only."""
    if HealthIssueKind.CREATORS.value in checks_off(s):
        return []
    put_off = _put_off(s, now or datetime.now(timezone.utc))
    suggestions = []
    for (site_key, ref), collections in _suggested(s).items():
        if creator_subject(site_key, ref) in put_off:
            continue
        site = collection_site(collections[0])
        account = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == site_key, CreatorAccount.site_ref == ref))
        title = Counter(collection.author_name for collection in collections if collection.author_name).most_common(1)
        suggestions.append(CreatorSuggestion(
            site_key, ref, account.creator.title if account is not None else (title[0][0] if title else ref),
            site.creator_names, site.name or site_key,
            [SuggestedCollection(collection.slug, collection.title) for collection in collections],
            account.creator.slug if account is not None else None,
            account.creator.title if account is not None else None,
        ))
    return sorted(suggestions, key=lambda suggestion: suggestion.title.casefold())


def suggested_collections(s: Session, site_key: str, ref: str) -> list[Collection]:
    """The collections a suggestion would group, by title. Reading only."""
    return _suggested(s).get((site_key, ref), [])


def put_off_suggestion(s: Session, kind: HealthIssueKind, subject: str, *, for_good: bool, now: datetime | None = None) -> None:
    """Hide a suggestion: for a while with Later, for good with Dismiss.

    ``s`` is a write transaction's session."""
    row = s.scalar(select(HealthDismissal).where(HealthDismissal.kind == kind.value, HealthDismissal.subject == subject))
    if row is None:
        row = HealthDismissal(kind=kind.value, subject=subject)
        s.add(row)
    row.until = None if for_good else (now or datetime.now(timezone.utc)) + LATER


def dismissed_count(s: Session, now: datetime | None = None) -> int:
    """How many suggestions the user dismissed, or put off for now. Reading only."""
    now = now or datetime.now(timezone.utc)
    return s.scalar(select(func.count()).select_from(HealthDismissal).where(
        or_(HealthDismissal.until.is_(None), HealthDismissal.until > now),
    )) or 0


def reset_dismissals(s: Session) -> int:
    """Show every suggestion the user put off or dismissed again. Returns how many there were.

    ``s`` is a write transaction's session."""
    return s.execute(delete(HealthDismissal)).rowcount or 0


__all__ = [
    "CHECKS", "LATER", "SUGGEST_FROM", "TITLES", "CollectionHealth", "CreatorSuggestion", "HealthCheck", "HealthIssue",
    "MovesIssue", "NewListsIssue", "SuggestedCollection", "UnhealthyCollection", "check_collection_health", "checks_off",
    "creator_subject", "creator_suggestions", "dismissed_count", "find_site_creator", "note_collection_health",
    "put_off_suggestion", "reset_dismissals", "set_check", "suggested_collections", "unhealthy_collections",
]
