"""Channels: a creator on one Site, whose sections go into collections.

A channel never indexes anything itself. Adding one makes a collection for each place its sections go, and each
section becomes a link of that collection. A video several sections list is kept by the link highest in the
channel's order: lists first, the newest first, then Live, Shorts and Videos. Videos holds all of a channel's
uploads, so it keeps only what the sections above it leave.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Channel, ChannelSection, Collection, CollectionLink
from backend.services.collections import add_collection, index_new_collection
from backend.services.errors import ServiceError
from backend.services.sites import site_record
from backend.types.channel_types import SectionTarget
from backend.types.collection_link_types import LinkPlacement
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.utils.helpers import generate_uuid, slugify
from sources import (
    ChannelDetails, ChannelPreset, Feature, SectionKind, SectionRef, SectionRole, Site, UnknownSourceError, get_source,
)


@dataclass(frozen=True)
class SectionPlan:
    """Where one section goes, and how its videos are placed there."""

    ref: str
    target: SectionTarget
    placement: LinkPlacement


def channel_site(source_key: str, url_or_site_key: str) -> Site:
    """The Site of a channel, which must offer channels."""
    try:
        source = get_source(source_key)
    except UnknownSourceError as exc:
        raise ServiceError(str(exc)) from exc
    site = source.site_for(url_or_site_key) if url_or_site_key.startswith("http") else source.site_of(url_or_site_key)
    if not source.has(Feature.CHANNELS) or site is None or not site.channel_label:
        raise ServiceError(f"{site.name if site else source.name} has no channels VODLoft can add")
    return site


def _usable(section: SectionRef) -> bool:
    # A section only some members can watch is left for the user to pick; a single item is added on its own page.
    return section.access is None and section.kind is not SectionKind.ITEM


def preset_plan(details: ChannelDetails, preset: ChannelPreset) -> list[SectionPlan]:
    """What a preset does with each section. The user can change any of it before the channel is added."""
    plans = []
    for section in details.sections:
        target, placement = SectionTarget.SKIP, LinkPlacement.SITE_SEASONS
        if preset is not ChannelPreset.PICK and _usable(section):
            if section.kind is SectionKind.FEED:
                target = SectionTarget.OWN if section.role is SectionRole.SHORT else SectionTarget.MAIN
            elif section.has_seasons or preset is ChannelPreset.PER_LIST:
                target = SectionTarget.OWN
            else:
                target, placement = SectionTarget.MAIN, LinkPlacement.ONE_SEASON
        plans.append(SectionPlan(section.ref, target, placement))
    return plans


_FEED_ORDER = {SectionRole.LIVE: 0, SectionRole.SHORT: 1, SectionRole.MAIN: 2}


def claim_order(sections: list[SectionRef]) -> list[str]:
    """The refs of the sections in the order that decides which keeps a shared video: lists as the Site lists
    them, which is newest first, then Live, Shorts and Videos."""
    lists = [section for section in sections if section.kind is not SectionKind.FEED]
    feeds = sorted((section for section in sections if section.kind is SectionKind.FEED), key=lambda s: _FEED_ORDER[s.role])
    return [section.ref for section in lists + feeds]


def section_collection_slug(channel_ref: str, section: SectionRef | ChannelSection) -> str:
    """The slug a section's own collection gets: its own id for a list, such as a playlist or a Daily Wire show,
    whose collection is known by it, and the channel's id with the feed's for a feed."""
    return section.ref if section.kind == SectionKind.LIST else f"{channel_ref}-{section.ref}"


def sections_in_library(
    s: Session, source_key: str, channel_ref: str, sections: Sequence[SectionRef | ChannelSection],
) -> dict[str, str]:
    """The slugs of the collections that already keep a section, by the section's ref: a collection with a link to
    it, or one known by the slug its own collection would get. Works on a channel being looked up and on a saved one."""
    urls = {section.url: section.ref for section in sections}
    slugs = {section_collection_slug(channel_ref, section): section.ref for section in sections}
    slugs[channel_ref] = next((s.ref for s in sections if s.kind == SectionKind.FEED and s.role == SectionRole.MAIN), "")
    found: dict[str, str] = {}
    for url, slug in s.execute(
        select(CollectionLink.url, Collection.slug).join(Collection, Collection.id == CollectionLink.collection_id)
        .where(CollectionLink.url.in_(urls))
    ):
        found[urls[url]] = slug
    for slug in s.scalars(select(Collection.slug).where(Collection.source_key == source_key, Collection.slug.in_(slugs))):
        if slugs[slug]:
            found.setdefault(slugs[slug], slug)
    return found


def channel_in_library(s: Session, site_key: str, ref: str) -> Channel | None:
    return s.scalar(select(Channel).where(Channel.site_key == site_key, Channel.site_ref == ref))


def _unique_slug(s: Session, model, wanted: str) -> str:
    """``wanted`` itself while it is free, since a Source may know a collection by it; else a slug made from it."""
    if wanted and s.scalar(select(model.id).where(model.slug == wanted)) is None:
        return wanted
    base = slugify(wanted) or "channel"
    slug, suffix = base, 2
    while s.scalar(select(model.id).where(model.slug == slug)) is not None:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    return slug


@dataclass(frozen=True)
class NewCollectionSettings:
    """What every collection made while adding a channel starts with."""

    type: CollectionType
    episode_identifier: EpisodeIdentifier
    membership_level: str


def add_channel(
    s: Session, *, source_key: str, details: ChannelDetails, plans: list[SectionPlan], settings: NewCollectionSettings,
    added_by_id: int | None = None,
) -> tuple[Channel, list[Collection]]:
    """Put a channel in the Library with the collections its sections go to, and start indexing them.

    ``details`` was looked up before the write transaction. Sections already kept by a collection are left where they
    are. Returns the channel and the collections it made."""
    site = channel_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    if channel_in_library(s, record.key, details.ref) is not None:
        raise ServiceError(f"{details.title} is already in your library")
    by_ref = {section.ref: section for section in details.sections}
    unknown = [plan.ref for plan in plans if plan.ref not in by_ref]
    if unknown:
        raise ServiceError(f"{details.title} has no section {unknown[0]}")
    channel = Channel(
        uuid=generate_uuid(), slug=_unique_slug(s, Channel, slugify(details.handle or details.title) or details.ref), source_key=source_key,
        site_key=record.key, site_ref=details.ref, url=details.url, title=details.title, handle=details.handle,
        description=details.description, avatar_path=details.avatar_url, banner_path=details.banner_url,
        links=list(details.links), facts=list(details.facts), added_by_id=added_by_id,
    )
    channel.sections = [
        ChannelSection(
            ref=section.ref, url=section.url, title=section.title, kind=section.kind.value, role=section.role.value,
            kind_label=section.kind_label, item_count=section.item_count, image_path=section.image_url,
            description=section.description, access=section.access, has_seasons=section.has_seasons,
            site_position=position,
        )
        for position, section in enumerate(details.sections)
    ]
    s.add(channel)
    s.flush()
    sections = {section.ref: section for section in channel.sections}
    kept = sections_in_library(s, source_key, details.ref, details.sections)
    order = {ref: position for position, ref in enumerate(claim_order(list(details.sections)))}
    wanted = [plan for plan in plans if plan.target is not SectionTarget.SKIP and plan.ref not in kept]

    groups: list[tuple[SectionRef | None, list[SectionPlan]]] = []
    main = [plan for plan in wanted if plan.target is SectionTarget.MAIN]
    if main:
        groups.append((None, main))
    groups += [(by_ref[plan.ref], [plan]) for plan in wanted if plan.target is SectionTarget.OWN]

    collections = []
    for own, group in groups:
        group = sorted(group, key=lambda plan: order[plan.ref])
        first = by_ref[group[0].ref]
        if own is None:
            # The collection is the channel's own uploads, when it takes them.
            feeds = [by_ref[plan.ref] for plan in group if by_ref[plan.ref].kind is SectionKind.FEED]
            main_feed = next((feed for feed in feeds if feed.role is SectionRole.MAIN), feeds[0] if feeds else first)
            title, slug, url, description = details.title, details.ref, main_feed.url, details.description
            image = details.avatar_url
        else:
            title = own.title if own.kind is not SectionKind.FEED else f"{details.title} {own.title}"
            slug, url, description, image = section_collection_slug(details.ref, own), own.url, own.description, own.image_url
        collection = Collection(
            uuid=generate_uuid(), slug=_unique_slug(s, Collection, slug), source_key=source_key, title=title,
            description=description, sharing_url=url, membership_level=settings.membership_level,
            type=settings.type.value, episode_identifier=settings.episode_identifier.value, author_name=details.title,
            author_slug=slugify(details.handle or details.title) or details.ref, thumbnail_landscape_path=image,
            links=[
                CollectionLink(
                    url=by_ref[plan.ref].url, title=by_ref[plan.ref].title, placement=plan.placement.value,
                    position=order[plan.ref], section=sections[plan.ref],
                )
                for plan in group
            ],
        )
        collection.channel = channel
        add_collection(s, collection, added_by_id=added_by_id)
        collections.append(collection)
    for collection in collections:
        index_new_collection(s, collection)
    return channel, collections


def _site_key_of(source_key: str) -> str:
    # A channel without a page of its own, such as a Daily Wire host, is on its Source's one Site.
    sites = get_source(source_key).sites
    if len(sites) != 1:
        raise ServiceError("This channel has no link, and its Site could not be told")
    return sites[0].key
