from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.api.models.channel import (
    ChannelAPICreate, ChannelAPIRead, ChannelLookupAPIRead, ChannelPageAPIRead,
)
from backend.db.models import Channel, Collection, CollectionLink, Episode
from backend.services import channels
from backend.services.channels import NewCollectionSettings, SectionPlan
from backend.services.errors import ServiceError
from backend.types.channel_types import SectionTarget
from backend.types.collection_link_types import LinkPlacement
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from sources import ChannelDetails, SectionRef, get_source


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
        added_by_id=added_by_id,
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
            [titles[link.channel_section_id] for link in collection.links if link.channel_section_id in titles],
        )
        for collection in sorted(channel.collections, key=lambda c: c.created_at or c.id)
    ]
    sections = [
        _Section(section, *kept.get(section.id, (None, None)))
        for section in channel.sections
    ]
    return ChannelPageAPIRead.model_validate(_ChannelRead(
        channel, _label(channel), collections_count.get(channel.id, 0), episodes.get(channel.id, 0),
        collections=collections, sections=sections,
    ))
