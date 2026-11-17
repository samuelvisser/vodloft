"""Channels: a creator on one Site, whose sections go into collections.

A channel never indexes anything itself. Adding one makes a collection for each place its sections go, and each
section becomes a link of that collection. A video several sections list is kept by the link highest in the
channel's order: lists first, the newest first, then Live, Shorts and Videos. Videos holds all of a channel's
uploads, so it keeps only what the sections above it leave.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Channel, ChannelSection, Collection, CollectionLink, CollectionLinkItem, Episode
from backend.services.collections import add_collection, index_new_collection, reindex_collection
from backend.services.errors import ServiceError
from backend.services.sites import site_record
from backend.types.channel_types import NewSectionAction, SectionStatus, SectionTarget
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.collection_link_types import LinkPlacement
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.utils.helpers import generate_uuid, slugify
from task_manager.scheduler.transactional import queue_task_after_commit
from sources import (
    ChannelDetails, ChannelPreset, Feature, SectionKind, SectionRef, SectionRole, Site, UnknownSourceError, get_source,
)


RECLAIM_TASK_KEY = "reclaim_channel_videos"
FOLLOW_TASK_KEY = "follow_channels"


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
    """What every collection made from a channel starts with."""

    type: CollectionType
    episode_identifier: EpisodeIdentifier
    membership_level: str


def _section_record(section: SectionRef, position: int, status: SectionStatus = SectionStatus.KNOWN) -> ChannelSection:
    return ChannelSection(
        ref=section.ref, url=section.url, title=section.title, kind=section.kind.value, role=section.role.value,
        kind_label=section.kind_label, item_count=section.item_count, image_path=section.image_url,
        description=section.description, access=section.access, has_seasons=section.has_seasons,
        site_position=position, status=status.value,
    )


def _new_channel(
    s: Session, source_key: str, site_key: str, details: ChannelDetails, *, added_by_id: int | None,
    new_sections: NewSectionAction = NewSectionAction.ASK,
) -> Channel:
    channel = Channel(
        uuid=generate_uuid(), slug=_unique_slug(s, Channel, slugify(details.handle or details.title) or details.ref), source_key=source_key,
        site_key=site_key, site_ref=details.ref, url=details.url, title=details.title, handle=details.handle,
        description=details.description, avatar_path=details.avatar_url, banner_path=details.banner_url,
        links=list(details.links), facts=list(details.facts), added_by_id=added_by_id, new_sections=new_sections.value,
    )
    channel.sections = [_section_record(section, position) for position, section in enumerate(details.sections)]
    s.add(channel)
    s.flush()
    return channel


def add_channel(
    s: Session, *, source_key: str, details: ChannelDetails, plans: list[SectionPlan], settings: NewCollectionSettings,
    added_by_id: int | None = None, new_sections: NewSectionAction = NewSectionAction.ASK,
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
    channel = _new_channel(s, source_key, record.key, details, added_by_id=added_by_id, new_sections=new_sections)
    order = {ref: position for position, ref in enumerate(claim_order(list(details.sections)))}
    collections = _place(s, channel, plans, order, settings, added_by_id=added_by_id)
    return channel, collections


def _place(
    s: Session, channel: Channel, plans: list[SectionPlan], order: dict[str, int], settings: NewCollectionSettings, *,
    added_by_id: int | None,
) -> list[Collection]:
    """Give the channel's sections to the collections the plans say, with links at ``order`` in the channel's order:
    the channel's own collection, made when it has none yet, or a new collection each. Starts indexing what changed.
    Returns the collections it made."""
    sections = {section.ref: section for section in channel.sections}
    kept = sections_in_library(s, channel.source_key, channel.site_ref, list(sections.values()))
    wanted = [plan for plan in plans if plan.target is not SectionTarget.SKIP and plan.ref not in kept]
    groups: list[tuple[ChannelSection | None, list[SectionPlan]]] = []
    main = [plan for plan in wanted if plan.target is SectionTarget.MAIN]
    if main:
        groups.append((None, main))
    groups += [(sections[plan.ref], [plan]) for plan in wanted if plan.target is SectionTarget.OWN]

    def link(plan: SectionPlan) -> CollectionLink:
        section = sections[plan.ref]
        section.status = SectionStatus.KNOWN.value
        return CollectionLink(
            url=section.url, title=section.title, placement=plan.placement.value, position=order[plan.ref], section=section,
        )

    made, changed = [], []
    for own, group in groups:
        group = sorted(group, key=lambda plan: order[plan.ref])
        if own is None and channel.main_collection is not None:
            channel.main_collection.links.extend(link(plan) for plan in group)
            changed.append(channel.main_collection)
            continue
        first = sections[group[0].ref]
        if own is None:
            # The collection is the channel's own uploads, when it takes them.
            feeds = [sections[plan.ref] for plan in group if sections[plan.ref].kind == SectionKind.FEED]
            main_feed = next((feed for feed in feeds if feed.role == SectionRole.MAIN), feeds[0] if feeds else first)
            title, slug, url, description = channel.title, channel.site_ref, main_feed.url, channel.description
            image = channel.avatar_path
        else:
            title = own.title if own.kind != SectionKind.FEED else f"{channel.title} {own.title}"
            slug, url, description, image = section_collection_slug(channel.site_ref, own), own.url, own.description, own.image_path
        collection = Collection(
            uuid=generate_uuid(), slug=_unique_slug(s, Collection, slug), source_key=channel.source_key, title=title,
            description=description, sharing_url=url, membership_level=settings.membership_level,
            type=settings.type.value, episode_identifier=settings.episode_identifier.value, author_name=channel.title,
            author_slug=slugify(channel.handle or channel.title) or channel.site_ref, thumbnail_landscape_path=image,
            genre=channel.genre, content_rating=channel.content_rating,
            links=[link(plan) for plan in group],
        )
        add_collection(s, collection, added_by_id=added_by_id)
        collection.channel = channel
        if own is None:
            channel.main_collection = collection
        made.append(collection)
    s.flush()
    for collection in made:
        index_new_collection(s, collection)
    for collection in changed:
        reindex_collection(s, collection)
    return made


def _settings_of(channel: Channel) -> NewCollectionSettings:
    """What a collection added to the channel later starts with: the same as the channel's own collection."""
    model = channel.main_collection or next(iter(channel.collections), None)
    if model is None:
        return NewCollectionSettings(CollectionType.SERIES, EpisodeIdentifier.SEASONAL, DwMembershipLevel.HIGHEST_ALLOWED.value)
    return NewCollectionSettings(CollectionType(model.type), EpisodeIdentifier(model.episode_identifier), model.membership_level)


def channel_order(channel: Channel) -> list[CollectionLink]:
    """The links of the channel's sections, in the channel's order."""
    links = [link for collection in channel.collections for link in collection.links if link.channel_section_id is not None]
    return sorted(links, key=lambda link: (link.position, link.id or 0))


def _make_room(channel: Channel, adding: Sequence[ChannelSection], *, after: Sequence[CollectionLink] = ()) -> dict[str, int]:
    """Renumber the channel's order with the sections in ``adding`` that it does not keep yet: a list goes above
    everything, as the newest list, and a feed to its place among the feeds. Returns their positions by ref. Links of
    the channel's collections that list no section of it go last, after them the links in ``after``."""
    existing = channel_order(channel)
    loose = sorted(
        (link for collection in channel.collections for link in collection.links if link.channel_section_id is None),
        key=lambda link: (link.position, link.id or 0),
    )
    placed = {link.channel_section_id for link in existing}
    by_ref = {section.ref: section for section in adding}
    new_refs = [ref for ref in claim_order([_as_ref(section) for section in adding]) if by_ref[ref].id not in placed]
    new_lists = [ref for ref in new_refs if by_ref[ref].kind != SectionKind.FEED]
    new_feeds = [ref for ref in new_refs if by_ref[ref].kind == SectionKind.FEED]
    entries: list[CollectionLink | str] = [*new_lists, *existing]
    for ref in new_feeds:
        rank = _FEED_ORDER[SectionRole(by_ref[ref].role)]
        at = next(
            (index for index, entry in enumerate(entries) if isinstance(entry, CollectionLink) and entry.section is not None
             and entry.section.kind == SectionKind.FEED and _FEED_ORDER[SectionRole(entry.section.role)] > rank),
            len(entries),
        )
        entries.insert(at, ref)
    entries += [link for link in loose if link not in after] + list(after)
    order: dict[str, int] = {}
    for position, entry in enumerate(entries):
        if isinstance(entry, str):
            order[entry] = position
        else:
            entry.position = position
    return order


def place_sections(s: Session, channel: Channel, plans: list[SectionPlan], *, added_by_id: int | None = None) -> list[Collection]:
    """Add sections of a channel that is in the Library to its collections, or ignore them. A list goes above
    everything in the channel's order, as the newest list; a feed goes to its place among the feeds.

    ``s`` is a write transaction's session."""
    sections = {section.ref: section for section in channel.sections}
    unknown = [plan.ref for plan in plans if plan.ref not in sections]
    if unknown:
        raise ServiceError(f"{channel.title} has no section {unknown[0]}", field="sections")
    for plan in plans:
        if plan.target is SectionTarget.SKIP:
            sections[plan.ref].status = SectionStatus.IGNORED.value
    adding = [plan for plan in plans if plan.target is not SectionTarget.SKIP]
    if not adding:
        return []
    order = _make_room(channel, [sections[plan.ref] for plan in adding])
    return _place(s, channel, [plan for plan in adding if plan.ref in order], order, _settings_of(channel), added_by_id=added_by_id)


def _as_ref(section: ChannelSection) -> SectionRef:
    return SectionRef(
        ref=section.ref, url=section.url, title=section.title, kind=SectionKind(section.kind), role=SectionRole(section.role),
    )


def set_channel_order(s: Session, channel: Channel, refs: list[str]) -> None:
    """Put the channel's sections that are in its collections in the order ``refs`` gives, which decides which
    collection and link keep a video several of them list. Videos with files stay where they are.

    ``s`` is a write transaction's session."""
    links = channel_order(channel)
    by_ref = {link.section.ref: link for link in links if link.section is not None}
    if sorted(refs) != sorted(by_ref):
        raise ServiceError("The order must name each section the channel keeps exactly once", field="order")
    if [link.section.ref for link in links if link.section is not None] == refs:
        return
    for position, ref in enumerate(refs):
        by_ref[ref].position = position
    s.flush()
    # The videos the links already list move to the link that keeps them now.
    queue_task_after_commit(s, def_key=RECLAIM_TASK_KEY, resource_type="channel", resource_id=channel.id)


@dataclass(frozen=True)
class ChannelSettings:
    new_sections: NewSectionAction
    genre: str | None
    content_rating: str | None


def update_channel_settings(s: Session, channel: Channel, settings: ChannelSettings) -> None:
    """Change what happens with the channel's new sections, and the genre and rating its collections get. A
    collection that had the channel's old genre or rating gets the new one; one with its own keeps it.

    ``s`` is a write transaction's session."""
    channel.new_sections = settings.new_sections.value
    for field in ("genre", "content_rating"):
        old, new = getattr(channel, field), getattr(settings, field) or None
        if old == new:
            continue
        for collection in channel.collections:
            if getattr(collection, field) in (old, None):
                setattr(collection, field, new)
        setattr(channel, field, new)


@dataclass(frozen=True)
class FollowResult:
    """What the daily look found on a channel."""

    asked: list[ChannelSection]
    added: list[ChannelSection]
    ignored: list[ChannelSection]


def follow_channel(s: Session, channel: Channel, details: ChannelDetails, *, now: datetime) -> FollowResult:
    """Take in what the Site says about a channel now: its name, pictures and facts, its sections' titles and counts,
    and the sections it did not have before, which the channel's setting adds, ignores or asks about. Sections the Site
    no longer lists stay, with what they hold.

    ``details`` was looked up before the write transaction; ``s`` is a write transaction's session."""
    for field, value in (
        ("title", details.title), ("handle", details.handle), ("description", details.description),
        ("avatar_path", details.avatar_url), ("banner_path", details.banner_url),
        ("links", list(details.links)), ("facts", list(details.facts)),
    ):
        if value and getattr(channel, field) != value:
            setattr(channel, field, value)
    channel.checked_at = now
    known = {section.ref: section for section in channel.sections}
    found: list[ChannelSection] = []
    for position, section in enumerate(details.sections):
        record = known.get(section.ref)
        if record is None:
            record = _section_record(section, position, SectionStatus.NEW)
            channel.sections.append(record)
            found.append(record)
            continue
        for field, value in (
            ("title", section.title), ("url", section.url), ("item_count", section.item_count),
            ("image_path", section.image_url), ("description", section.description), ("site_position", position),
            ("access", section.access), ("kind_label", section.kind_label),
        ):
            if getattr(record, field) != value:
                setattr(record, field, value)
    s.flush()
    # A section that is already in the library, such as a show added before the channel, needs no choice, and a
    # single item, such as a movie, is added from its own page.
    kept = sections_in_library(s, channel.source_key, channel.site_ref, found)
    for record in found:
        if record.ref in kept or record.kind == SectionKind.ITEM:
            record.status = SectionStatus.KNOWN.value
    found = [record for record in found if record.ref not in kept and record.kind != SectionKind.ITEM]
    if not found:
        return FollowResult([], [], [])
    action = NewSectionAction(channel.new_sections)
    # A single item, or a section only some members can watch, is never added by itself.
    addable = [record for record in found if _usable(_as_ref(record)) and record.access is None]
    if action is NewSectionAction.IGNORE:
        for record in found:
            record.status = SectionStatus.IGNORED.value
        return FollowResult([], [], found)
    if action is NewSectionAction.ASK or not addable:
        return FollowResult(found, [], [])
    target = SectionTarget.OWN if action is NewSectionAction.OWN else SectionTarget.MAIN
    plans = [
        SectionPlan(
            record.ref, target if record.kind != SectionKind.FEED or target is SectionTarget.OWN else SectionTarget.MAIN,
            LinkPlacement.ONE_SEASON if target is SectionTarget.MAIN and record.kind == SectionKind.LIST and not record.has_seasons
            else LinkPlacement.SITE_SEASONS,
        )
        for record in addable
    ]
    if target is SectionTarget.MAIN:
        # A show with its own seasons keeps them, so it becomes a collection of its own.
        seasons = {record.ref for record in addable if record.has_seasons}
        plans = [SectionPlan(plan.ref, SectionTarget.OWN, plan.placement) if plan.ref in seasons else plan for plan in plans]
    place_sections(s, channel, plans)
    return FollowResult([record for record in found if record not in addable], addable, [])


def _site_key_of(source_key: str) -> str:
    # A channel without a page of its own, such as a Daily Wire host, is on its Source's one Site.
    sites = get_source(source_key).sites
    if len(sites) != 1:
        raise ServiceError("This channel has no link, and its Site could not be told")
    return sites[0].key


@dataclass(frozen=True)
class LinkMatch:
    """Which section of a channel one of a collection's links is, if any, and the collection that keeps that section
    already, when another one does."""

    link: CollectionLink
    section: SectionRef | ChannelSection | None
    kept_by: str | None = None


def match_links(
    s: Session, collection: Collection, source_key: str, details: ChannelDetails, channel: Channel | None,
) -> list[LinkMatch]:
    """Match each of the collection's links to a section of the channel: the section at the same link, or the
    section the collection is known by, such as a playlist added by its own link before."""
    sections: Sequence[SectionRef | ChannelSection] = channel.sections if channel is not None else details.sections
    by_url = {section.url: section for section in sections}
    by_ref = {section.ref: section for section in sections}
    links = sorted(collection.links, key=lambda link: (link.position, link.id or 0))
    matched: dict[int, SectionRef | ChannelSection] = {
        id(link): by_url[link.url] for link in links if link.url in by_url
    }
    kept = sections_in_library(s, source_key, details.ref, list(sections))
    for ref, slug in kept.items():
        if slug != collection.slug or any(section.ref == ref for section in matched.values()):
            continue
        free = next((link for link in links if id(link) not in matched), None)
        if free is not None:
            matched[id(free)] = by_ref[ref]
    # A section another of the channel's collections keeps stays there.
    elsewhere: dict[int, str] = {}
    if channel is not None:
        for other in channel.collections:
            if other.id == collection.id:
                continue
            for link in other.links:
                if link.channel_section_id is not None:
                    elsewhere[link.channel_section_id] = other.title
    result = []
    for link in links:
        section = matched.get(id(link))
        taken = elsewhere.get(section.id) if isinstance(section, ChannelSection) else None
        result.append(LinkMatch(link, None if taken else section, taken))
    return result


def join_channel(
    s: Session, collection: Collection, *, source_key: str, details: ChannelDetails, added_by_id: int | None = None,
) -> Channel:
    """Make a collection one of a channel's, adding the channel when it is not in the Library yet. Each of its links
    that is a section of the channel becomes that section's link, in the channel's order. Nothing is indexed again
    and no file moves; videos without files that another of the channel's collections keeps move there.

    ``details`` was looked up before the write transaction. ``s`` is a write transaction's session."""
    if collection.channel_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.channel.title}")
    site = channel_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    channel = channel_in_library(s, record.key, details.ref)
    had_collections = channel is not None and bool(channel.collections)
    if channel is None:
        channel = _new_channel(s, source_key, record.key, details, added_by_id=added_by_id)
    matches = match_links(s, collection, source_key, details, channel)
    paired = [(match.link, match.section) for match in matches if isinstance(match.section, ChannelSection)]
    if not paired:
        raise ServiceError(f"None of the links of {collection.title} is a playlist or show of {channel.title}")
    order = _make_room(channel, [section for _link, section in paired], after=[m.link for m in matches if m.section is None])
    for link, section in paired:
        link.section = section
        link.position = order[section.ref]
        section.status = SectionStatus.KNOWN.value
    collection.channel = channel
    main = next((section for _link, section in paired if section.kind == SectionKind.FEED and section.role == SectionRole.MAIN), None)
    if main is not None and channel.main_collection is None:
        channel.main_collection = collection
    s.flush()
    if had_collections:
        queue_task_after_commit(s, def_key=RECLAIM_TASK_KEY, resource_type="channel", resource_id=channel.id)
    return channel


def leave_channel(s: Session, collection: Collection) -> None:
    """Make a channel's collection a plain one again. It keeps its links, episodes, files and settings.

    ``s`` is a write transaction's session."""
    channel = collection.channel
    if channel is None:
        raise ServiceError(f"{collection.title} is not in a channel")
    for link in collection.links:
        link.section = None
    if channel.main_collection_id == collection.id:
        channel.main_collection = None
    collection.channel = None
    s.flush()


def videos_kept_elsewhere(s: Session, collection: Collection) -> int:
    """How many videos the collection's links list that another of its channel's collections keeps. Once it leaves
    the channel, it adds them too."""
    if collection.channel_id is None:
        return 0
    others = select(Collection.id).where(Collection.channel_id == collection.channel_id, Collection.id != collection.id)
    listed = (
        select(CollectionLinkItem.source_slug).join(CollectionLink, CollectionLink.id == CollectionLinkItem.link_id)
        .where(CollectionLink.collection_id == collection.id)
    )
    return s.scalar(
        select(func.count(func.distinct(Episode.source_slug)))
        .where(Episode.collection_id.in_(others), Episode.source_slug.in_(listed))
    ) or 0
