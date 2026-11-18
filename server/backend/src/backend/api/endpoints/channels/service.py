from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.api.models.channel import (
    ChannelAPICreate, ChannelAPIRead, ChannelAPIUpdate, ChannelLookupAPIRead, ChannelPageAPIRead, ChannelSectionsAPIAdd,
    CollectionChannelLeaveAPIRead, CollectionChannelMatchAPIRead,
)
from backend.api.models.collection import CollectionAPIRead
from backend.db.models import Channel, Collection, Episode
from backend.services import channels
from backend.services.channels import NewCollectionSettings, SectionPlan
from backend.services.errors import ServiceError
from backend.services.sites import collection_site
from backend.types.channel_types import NewSectionAction, SectionTarget
from task_manager.scheduler.transactional import queue_task_after_commit
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from sources import ChannelDetails, Feature, SectionRef, get_source
from backend.services.source_requests import asking_source


class ChannelNotFoundError(LookupError):
    pass


def lookup_channel_label(source_key: str, url: str | None) -> str:
    """What the Site of a channel about to be looked up calls it, told without a network request."""
    if url:
        return channels.channel_site(source_key, url).channel_label
    source = get_source(source_key)
    return next((site.channel_label for site in source.sites if site.channels), "channel")


def look_up_channel(
    source_key: str, url: str | None, ref: str | None, progress: Callable[[str], None] = lambda step: None,
) -> ChannelDetails:
    """Ask the Source for the channel, telling ``progress`` what it is doing. Slow: call it outside a transaction."""
    if url:
        channels.channel_site(source_key, url)
        return get_source(source_key).channel_details(url, progress)
    if not ref:
        raise ServiceError("Give the channel's link", field="url")
    return get_source(source_key).channel_details(ref, progress)


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
    details: ChannelDetails
    source_key: str
    site_key: str
    site_name: str
    channel_label: str
    link_seasons: bool
    sections: list[_Section]
    presets: list[_Preset]
    channel_slug: str | None = None
    links: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    def __getattr__(self, name):
        return getattr(self.details, name)


def channel_lookup(s: Session, source_key: str, details: ChannelDetails) -> ChannelLookupAPIRead:
    site = channels.channel_site(source_key, details.url) if details.url else get_source(source_key).sites[0]
    kept = channels.sections_in_library(s, source_key, details.ref, details.sections)
    titles = dict(s.execute(select(Collection.slug, Collection.title).where(Collection.slug.in_(kept.values()))).all())
    existing = channels.channel_in_library(s, site.key, details.ref)
    return ChannelLookupAPIRead.model_validate(_Lookup(
        details=details, source_key=source_key, site_key=site.key, site_name=site.name,
        channel_label=site.channel_label, link_seasons=channels.lists_are_seasons(site),
        sections=[
            _Section(section, kept.get(section.ref), titles.get(kept.get(section.ref)))
            for section in details.sections
        ],
        presets=[_Preset(preset.value, channels.preset_plan(details, preset)) for preset in site.channel_presets],
        channel_slug=existing.slug if existing is not None else None,
        links=list(details.links), facts=list(details.facts),
    ))


def add_channel(s: Session, body: ChannelAPICreate, details: ChannelDetails, *, added_by_id: int | None) -> ChannelPageAPIRead:
    channel, _collections = channels.add_channel(
        s, source_key=body.source_key, details=details,
        plans=[SectionPlan(plan.ref, SectionTarget(plan.target)) for plan in body.sections],
        # An artist's collections hold their music.
        settings=NewCollectionSettings(
            CollectionType.MUSIC if details.music else CollectionType(body.type), EpisodeIdentifier(body.episode_identifier),
            body.membership_level,
        ),
        added_by_id=added_by_id, new_sections=NewSectionAction(body.new_sections),
    )
    s.flush()
    return channel_page(s, channel.slug)


def _counts(s: Session, channel_ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    collections = dict(s.execute(
        select(Collection.channel_id, func.count()).where(Collection.channel_id.in_(channel_ids)).group_by(Collection.channel_id)
    ).all())
    episodes = dict(s.execute(
        select(Collection.channel_id, func.count(Episode.id)).join(Episode, Episode.collection_id == Collection.id)
        .where(Collection.channel_id.in_(channel_ids)).group_by(Collection.channel_id)
    ).all())
    return collections, episodes


@dataclass
class _ChannelRead:
    channel: Channel
    channel_label: str
    collection_count: int
    episode_count: int
    collections: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    def __getattr__(self, name):
        return getattr(self.channel, name)


def _label(channel: Channel) -> str:
    site = get_source(channel.source_key).site_of(channel.site_key)
    return site.channel_label if site is not None else "channel"


def list_channels(s: Session) -> list[ChannelAPIRead]:
    rows = list(s.scalars(select(Channel).order_by(Channel.title)))
    collections, episodes = _counts(s, [channel.id for channel in rows])
    return [
        ChannelAPIRead.model_validate(_ChannelRead(
            channel, _label(channel), collections.get(channel.id, 0), episodes.get(channel.id, 0),
        ))
        for channel in rows
    ]


@dataclass(frozen=True)
class _CollectionRead:
    collection: Collection
    episode_count: int
    links: list[str]

    def __getattr__(self, name):
        return getattr(self.collection, name)


def channel_page(s: Session, slug: str) -> ChannelPageAPIRead:
    channel = s.scalar(
        select(Channel).where(Channel.slug == slug).options(selectinload(Channel.sections), selectinload(Channel.collections))
    )
    if channel is None:
        raise ChannelNotFoundError(f"Channel '{slug}' not found")
    collections_count, episodes = _counts(s, [channel.id])
    per_collection = dict(s.execute(
        select(Episode.collection_id, func.count()).where(Episode.collection_id.in_([c.id for c in channel.collections]))
        .group_by(Episode.collection_id)
    ).all())
    kept = channels.sections_in_library(s, channel.source_key, channel.site_ref, channel.sections, channel.main_collection)
    titles = dict(s.execute(select(Collection.slug, Collection.title).where(Collection.slug.in_(kept.values()))).all())
    collections = [
        _CollectionRead(
            collection, per_collection.get(collection.id, 0),
            [section.title for section in channel.sections if kept.get(section.ref) == collection.slug],
        )
        for collection in sorted(channel.collections, key=lambda c: c.created_at or c.id)
    ]
    sections = [_Section(section, kept.get(section.ref), titles.get(kept.get(section.ref))) for section in channel.sections]
    return ChannelPageAPIRead.model_validate(_ChannelRead(
        channel, _label(channel), collections_count.get(channel.id, 0), episodes.get(channel.id, 0),
        collections=collections, sections=sections,
    ))


def _channel(s: Session, slug: str) -> Channel:
    channel = s.scalar(select(Channel).where(Channel.slug == slug))
    if channel is None:
        raise ChannelNotFoundError(f"Channel '{slug}' not found")
    return channel


def update_channel(s: Session, slug: str, body: ChannelAPIUpdate) -> ChannelPageAPIRead:
    channel = _channel(s, slug)
    channels.update_channel_settings(s, channel, channels.ChannelSettings(
        NewSectionAction(body.new_sections), body.genre, body.content_rating,
    ))
    s.flush()
    return channel_page(s, slug)


def add_sections(s: Session, slug: str, body: ChannelSectionsAPIAdd, *, added_by_id: int | None) -> ChannelPageAPIRead:
    channel = _channel(s, slug)
    channels.place_sections(
        s, channel, [SectionPlan(plan.ref, SectionTarget(plan.target)) for plan in body.sections],
        added_by_id=added_by_id,
    )
    s.flush()
    return channel_page(s, slug)


def check_channel(s: Session, slug: str) -> None:
    """Look for the channel's new sections now, as the daily look does."""
    channel = _channel(s, slug)
    queue_task_after_commit(s, def_key=channels.FOLLOW_TASK_KEY, resource_type="channel", resource_id=channel.id)


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
    """What looking up the channel behind a collection needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if collection.channel_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.channel.title}")
    if collection.sharing_url is None:
        raise ServiceError(f"{collection.title} has no link of its own, so it belongs to no channel")
    return CollectionLink(collection.source_key, collection.title, collection.sharing_url)


def look_up_collection_channel(link: CollectionLink) -> ChannelDetails:
    """The channel behind the collection's link, asked of its Source. Slow: call it outside a transaction."""
    source = get_source(link.source_key)
    if not source.has(Feature.CHANNELS):
        raise ServiceError(f"{source.name} has no channels")
    site = source.site_for(link.url)
    label = site.channel_label if site is not None else "channel"
    with asking_source(f"Could not look up the {label}"):
        ref = source.channel_of(link.url)
    if ref is None:
        raise ServiceError(f"VODLoft found no {label} behind the link of {link.title}")
    with asking_source(f"Could not look up the {label}"):
        return source.channel_details(ref)


@dataclass
class _Match:
    details: ChannelDetails
    site_name: str
    channel_label: str
    section: object | None
    kept_by: str | None
    channel_slug: str | None = None

    def __getattr__(self, name):
        return getattr(self.details, name)


def collection_channel_match(s: Session, collection_slug: str, source_key: str, details: ChannelDetails) -> CollectionChannelMatchAPIRead:
    collection = _collection(s, collection_slug)
    site = channels.channel_site(source_key, details.url or collection.site_key or get_source(source_key).sites[0].key)
    existing = channels.channel_in_library(s, site.key, details.ref)
    section, kept_by = channels.collection_section(s, collection, source_key, details, existing)
    return CollectionChannelMatchAPIRead.model_validate(_Match(
        details, site.name, site.channel_label, section, kept_by, existing.slug if existing is not None else None,
    ))


def join_collection_channel(
    s: Session, collection_slug: str, source_key: str, details: ChannelDetails, *, added_by_id: int | None,
) -> CollectionAPIRead:
    collection = _collection(s, collection_slug)
    channels.join_channel(s, collection, source_key=source_key, details=details, added_by_id=added_by_id)
    s.flush()
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)


def collection_channel_leave(s: Session, collection_slug: str) -> CollectionChannelLeaveAPIRead:
    collection = _collection(s, collection_slug)
    if collection.channel is None:
        raise ServiceError(f"{collection.title} is not in a {collection_site(collection).channel_label}")
    return CollectionChannelLeaveAPIRead(channel_title=collection.channel.title)


def leave_collection_channel(s: Session, collection_slug: str) -> CollectionAPIRead:
    collection = _collection(s, collection_slug)
    channels.leave_channel(s, collection)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)
