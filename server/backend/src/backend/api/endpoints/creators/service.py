from __future__ import annotations

import logging

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.api.models.collection_seasons import ReassignedMoveAPIRead
from backend.services.reassigned import move_and_rename, reassigned_in_creator
from backend.api.models.creator import (
    CreatorAPICreate, CreatorAPIRead, CreatorAPIUpdate, CreatorCombineAPIIn, CreatorLookupAPIRead, CreatorPageAPIRead,
    CreatorSectionMoveAPIIn, CreatorSectionsAPIAdd, CollectionCreatorLeaveAPIRead, CollectionCreatorMatchAPIRead,
)
from backend.api.models.collection import CollectionAPIRead
from backend.db.models import Creator, CreatorAccount, Collection, Episode
from backend.services import creators
from backend.services.creators import NewCollectionSettings, SectionPlan
from backend.services.errors import ServiceError
from backend.services.sites import collection_site
from backend.types.creator_types import NewSectionAction, SectionTarget
from task_manager.scheduler.transactional import queue_task_after_commit
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from sources import CreatorDetails, Feature, SectionRef, get_source
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


def look_up_creator(
    source_key: str, url: str | None, ref: str | None, progress: Callable[[str], None] = lambda step: None,
) -> CreatorDetails:
    """Ask the Source for the creator, telling ``progress`` what it is doing. Slow: call it outside a transaction."""
    if url:
        creators.creator_site(source_key, url)
        return get_source(source_key).creator_details(url, progress)
    if not ref:
        raise ServiceError("Give the creator's link", field="url")
    return get_source(source_key).creator_details(ref, progress)


@dataclass(frozen=True)
class _Section:
    section: SectionRef
    collection_slug: str | None = None
    collection_title: str | None = None

    def __getattr__(self, name):
        return getattr(self.section, name)


@dataclass(frozen=True)
class _Preset:
    key: str
    plan: list[SectionPlan]


@dataclass
class _Lookup:
    details: CreatorDetails
    source_key: str
    site_key: str
    site_name: str
    creator_label: str
    link_seasons: bool
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
    existing = creators.account_in_library(s, site.key, details.ref)
    return CreatorLookupAPIRead.model_validate(_Lookup(
        details=details, source_key=source_key, site_key=site.key, site_name=site.name,
        creator_label=site.creator_label, link_seasons=creators.lists_are_seasons(site),
        sections=[
            _Section(section, kept.get(section.ref), titles.get(kept.get(section.ref)))
            for section in details.sections
        ],
        presets=[_Preset(preset.value, creators.preset_plan(details, preset)) for preset in site.creator_presets],
        creator_slug=existing.creator.slug if existing is not None else None,
        links=list(details.links), facts=list(details.facts),
    ))


def add_creator(s: Session, body: CreatorAPICreate, details: CreatorDetails, *, added_by_id: int | None) -> CreatorPageAPIRead:
    into = None
    if body.into:
        into = s.scalar(select(Creator).where(Creator.slug == body.into))
        if into is None:
            raise ServiceError("This creator is not in the Library", field="into")
    creator, _collections = creators.add_creator(
        s, source_key=body.source_key, details=details,
        plans=[SectionPlan(plan.ref, SectionTarget(plan.target)) for plan in body.sections],
        # An artist's collections hold their music.
        settings=NewCollectionSettings(
            CollectionType.MUSIC if details.music else CollectionType(body.type), EpisodeIdentifier(body.episode_identifier),
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

    def __getattr__(self, name):
        return getattr(self.account, name)


@dataclass
class _CreatorRead:
    creator: Creator
    collection_count: int
    episode_count: int
    collections: list = field(default_factory=list)
    accounts: list | None = None
    reassigned_count: int = 0

    @property
    def creator_label(self) -> str:
        return creators.creator_label(self.creator)

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
    links: list[str]

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
    per_collection = dict(s.execute(
        select(Episode.collection_id, func.count()).where(Episode.collection_id.in_([c.id for c in creator.collections]))
        .group_by(Episode.collection_id)
    ).all())
    kept = {
        account.id: creators.sections_in_library(
            s, account.source_key, account.site_ref, account.sections, account.main_collection,
        )
        for account in creator.accounts
    }
    slugs = {slug for found in kept.values() for slug in found.values()}
    titles = dict(s.execute(select(Collection.slug, Collection.title).where(Collection.slug.in_(slugs))).all())
    collections = [
        _CollectionRead(
            collection, per_collection.get(collection.id, 0),
            [
                section.title for account in creator.accounts for section in account.sections
                if kept[account.id].get(section.ref) == collection.slug
            ],
        )
        for collection in sorted(creator.collections, key=lambda c: c.created_at or c.id)
    ]
    accounts = [
        _AccountRead(account, [
            _Section(section, kept[account.id].get(section.ref), titles.get(kept[account.id].get(section.ref)))
            for section in account.sections
        ])
        for account in creator.accounts
    ]
    return CreatorPageAPIRead.model_validate(_CreatorRead(
        creator, collections_count.get(creator.id, 0), episodes.get(creator.id, 0),
        collections=collections, accounts=accounts, reassigned_count=len(reassigned_in_creator(s, creator)),
    ))


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
    creators.update_creator_settings(s, creator, creators.CreatorSettings(
        NewSectionAction(body.new_sections), body.genre, body.content_rating,
    ))
    s.flush()
    return creator_page(s, slug)


def add_sections(
    s: Session, slug: str, account_id: int, body: CreatorSectionsAPIAdd, *, added_by_id: int | None,
) -> CreatorPageAPIRead:
    creators.place_sections(
        s, _account(s, slug, account_id), [SectionPlan(plan.ref, SectionTarget(plan.target)) for plan in body.sections],
        added_by_id=added_by_id,
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


def look_up_collection_creator(link: CollectionLink) -> CreatorDetails:
    """The creator behind the collection's link, asked of its Source. Slow: call it outside a transaction."""
    source = get_source(link.source_key)
    if not source.has(Feature.CREATORS):
        raise ServiceError(f"{source.name} has no creators")
    site = source.site_for(link.url)
    label = site.creator_label if site is not None else "creator"
    with asking_source(f"Could not look up the {label}"):
        ref = source.creator_of(link.url)
    if ref is None:
        raise ServiceError(f"VODLoft found no {label} behind the link of {link.title}")
    with asking_source(f"Could not look up the {label}"):
        return source.creator_details(ref)


@dataclass
class _Match:
    details: CreatorDetails
    site_name: str
    creator_label: str
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
        details, site.name, site.creator_label, section if keeper is None or movable else None,
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
