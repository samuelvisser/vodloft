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
from backend.db.models import Channel, Collection, CollectionLink, CollectionLinkItem, Episode
from backend.services import channels
from backend.services.channels import NewCollectionSettings, SectionPlan
from backend.services.errors import ServiceError
from backend.types.channel_types import NewSectionAction, SectionTarget
from task_manager.scheduler.transactional import queue_task_after_commit
from backend.types.collection_link_types import LinkPlacement
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from sources import ChannelDetails, Feature, SectionRef, get_source
from backend.services.source_requests import asking_source


class ChannelNotFoundError(LookupError):
    pass


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
    sections: list[_Section]
    claim_order: list[str]
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
        channel_label=site.channel_label or "channel",
        sections=[
            _Section(section, kept.get(section.ref), titles.get(kept.get(section.ref)))
            for section in details.sections
        ],
        claim_order=channels.claim_order(list(details.sections)),
        presets=[_Preset(preset.value, channels.preset_plan(details, preset)) for preset in site.channel_presets],
        channel_slug=existing.slug if existing is not None else None,
        links=list(details.links), facts=list(details.facts),
    ))


def add_channel(s: Session, body: ChannelAPICreate, details: ChannelDetails, *, added_by_id: int | None) -> ChannelPageAPIRead:
    channel, _collections = channels.add_channel(
        s, source_key=body.source_key, details=details,
        plans=[SectionPlan(plan.ref, SectionTarget(plan.target), LinkPlacement(plan.placement)) for plan in body.sections],
        settings=NewCollectionSettings(CollectionType(body.type), EpisodeIdentifier(body.episode_identifier), body.membership_level),
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
    order: list = field(default_factory=list)

    def __getattr__(self, name):
        return getattr(self.channel, name)


def _label(channel: Channel) -> str:
    site = get_source(channel.source_key).site_of(channel.site_key)
    return (site.channel_label if site is not None else None) or "channel"


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
    kept: dict[int, tuple[str, str]] = {}
    for section_id, collection_slug, collection_title in s.execute(
        select(CollectionLink.channel_section_id, Collection.slug, Collection.title)
        .join(Collection, Collection.id == CollectionLink.collection_id)
        .where(CollectionLink.channel_section_id.in_([section.id for section in channel.sections]))
    ):
        kept[section_id] = (collection_slug, collection_title)
    # A section that was in the library before the channel was added stays in its own collection.
    others = [section for section in channel.sections if section.id not in kept]
    elsewhere = channels.sections_in_library(s, channel.source_key, channel.site_ref, others)
    titles_elsewhere = dict(s.execute(select(Collection.slug, Collection.title).where(Collection.slug.in_(elsewhere.values()))).all())
    for section in others:
        if section.ref in elsewhere:
            kept[section.id] = (elsewhere[section.ref], titles_elsewhere.get(elsewhere[section.ref]))
    titles = {section.id: section.title for section in channel.sections}
    collections = [
        _CollectionRead(
            collection, per_collection.get(collection.id, 0),
            [
                titles[link.channel_section_id] for link in sorted(collection.links, key=lambda link: (link.position, link.id))
                if link.channel_section_id in titles
            ],
        )
        for collection in sorted(channel.collections, key=lambda c: c.created_at or c.id)
    ]
    sections = [
        _Section(section, *kept.get(section.id, (None, None)))
        for section in channel.sections
    ]
    links = channels.channel_order(channel)
    listed = dict(s.execute(
        select(CollectionLinkItem.link_id, func.count()).where(CollectionLinkItem.link_id.in_([link.id for link in links]))
        .group_by(CollectionLinkItem.link_id)
    ).all())
    order = [_OrderEntry(link, listed.get(link.id, 0)) for link in links if link.section is not None]
    return ChannelPageAPIRead.model_validate(_ChannelRead(
        channel, _label(channel), collections_count.get(channel.id, 0), episodes.get(channel.id, 0),
        collections=collections, sections=sections, order=order,
    ))


@dataclass(frozen=True)
class _OrderEntry:
    link: CollectionLink
    video_count: int

    @property
    def ref(self) -> str:
        return self.link.section.ref

    @property
    def title(self) -> str:
        return self.link.section.title

    @property
    def kind(self) -> str:
        return self.link.section.kind

    @property
    def kind_label(self) -> str | None:
        return self.link.section.kind_label

    @property
    def collection_slug(self) -> str:
        return self.link.collection.slug

    @property
    def collection_title(self) -> str:
        return self.link.collection.title

    @property
    def placement(self) -> str:
        return self.link.placement


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
    if body.order is not None:
        channels.set_channel_order(s, channel, body.order)
    s.flush()
    return channel_page(s, slug)


def add_sections(s: Session, slug: str, body: ChannelSectionsAPIAdd, *, added_by_id: int | None) -> ChannelPageAPIRead:
    channel = _channel(s, slug)
    channels.place_sections(
        s, channel, [SectionPlan(plan.ref, SectionTarget(plan.target), LinkPlacement(plan.placement)) for plan in body.sections],
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
class CollectionLinks:
    source_key: str
    title: str
    urls: list[str]


def collection_links(s: Session, collection_slug: str) -> CollectionLinks:
    """What looking up the channel behind a collection needs, read before the slow lookup."""
    collection = _collection(s, collection_slug)
    if collection.channel_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.channel.title}")
    urls = [link.url for link in sorted(collection.links, key=lambda link: (link.position, link.id))]
    return CollectionLinks(collection.source_key, collection.title, urls)


def look_up_collection_channel(links: CollectionLinks) -> ChannelDetails:
    """The channel behind the collection's links, asked of its Source. Slow: call it outside a transaction."""
    source = get_source(links.source_key)
    if not source.has(Feature.CHANNELS):
        raise ServiceError(f"{source.name} has no channels")
    with asking_source("Could not look up the channel"):
        ref = next((found for found in map(source.channel_of, links.urls) if found), None)
    if ref is None:
        raise ServiceError(f"VODLoft found no channel behind the links of {links.title}")
    with asking_source("Could not look up the channel"):
        return source.channel_details(ref)


@dataclass
class _Match:
    details: ChannelDetails
    site_name: str
    channel_label: str
    links: list
    channel_slug: str | None = None

    def __getattr__(self, name):
        return getattr(self.details, name)


def collection_channel_match(s: Session, collection_slug: str, source_key: str, details: ChannelDetails) -> CollectionChannelMatchAPIRead:
    collection = _collection(s, collection_slug)
    site = channels.channel_site(source_key, details.url or collection.site_key or get_source(source_key).sites[0].key)
    existing = channels.channel_in_library(s, site.key, details.ref)
    return CollectionChannelMatchAPIRead.model_validate(_Match(
        details, site.name, site.channel_label or "channel",
        channels.match_links(s, collection, source_key, details, existing),
        existing.slug if existing is not None else None,
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
        raise ServiceError(f"{collection.title} is not in a channel")
    return CollectionChannelLeaveAPIRead(
        channel_title=collection.channel.title, videos_kept_elsewhere=channels.videos_kept_elsewhere(s, collection),
    )


def leave_collection_channel(s: Session, collection_slug: str) -> CollectionAPIRead:
    collection = _collection(s, collection_slug)
    channels.leave_channel(s, collection)
    s.refresh(collection)
    return CollectionAPIRead.model_validate(collection)
