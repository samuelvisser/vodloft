"""Channels: a creator on one Site, whose sections go into collections.

A channel never indexes anything itself. Adding one makes the channel's own collection, which takes all its uploads
from its Videos page, and a collection of its own for each section that goes elsewhere. On a Site whose lists can be
seasons, a list, such as a playlist, that goes into the channel's own collection becomes one of its seasons. The
channel alone decides where each section goes: its daily look finds new sections, also new playlists, and its one
setting says what happens with them. A show, with seasons of its own, is always a collection of its own.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Channel, ChannelSection, Collection, CollectionList
from backend.services.link_seasons import is_season
from backend.services.collections import add_collection, index_new_collection, reindex_collection
from backend.services.errors import ServiceError
from backend.services.sites import collection_site, site_record
from backend.types.channel_types import NewSectionAction, SectionStatus, SectionTarget
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.link_season_types import NewLinkSeasonAction, LinkSeasons, ListStatus
from backend.utils.helpers import generate_uuid, slugify
from sources import (
    ChannelDetails, ChannelPreset, Feature, SectionKind, SectionRef, SectionRole, Site, UnknownSourceError, get_source,
)


FOLLOW_TASK_KEY = "follow_channels"


@dataclass(frozen=True)
class SectionPlan:
    """Where one section goes."""

    ref: str
    target: SectionTarget


def channel_site(source_key: str, url_or_site_key: str) -> Site:
    """The Site of a channel, which must offer channels."""
    try:
        source = get_source(source_key)
    except UnknownSourceError as exc:
        raise ServiceError(str(exc)) from exc
    site = source.site_for(url_or_site_key) if url_or_site_key.startswith("http") else source.site_of(url_or_site_key)
    if not source.has(Feature.CHANNELS) or site is None or not site.channels:
        raise ServiceError(f"{site.name if site else source.name} has no channels VODLoft can add")
    return site


def _usable(section: SectionRef) -> bool:
    # A section only some members can watch is left for the user to pick; a single item is added on its own page.
    return section.access is None and section.kind is not SectionKind.ITEM


def preset_plan(details: ChannelDetails, preset: ChannelPreset) -> list[SectionPlan]:
    """What a preset does with each section. The user can change any of it before the channel is added."""
    plans = []
    for section in details.sections:
        target = SectionTarget.SKIP
        if preset is not ChannelPreset.PICK and _usable(section):
            # The channel's own collection lists its Shorts and Live too, tagged, so they need no collection of their own.
            if section.kind is SectionKind.FEED:
                target = SectionTarget.MAIN
            elif section.kind is SectionKind.SHOW or preset is ChannelPreset.PER_LIST:
                target = SectionTarget.OWN
            else:
                target = SectionTarget.MAIN
        plans.append(SectionPlan(section.ref, target))
    return plans


def section_collection_slug(channel_ref: str, section: SectionRef | ChannelSection) -> str:
    """The slug a section's own collection gets: its own id for a list or a show, such as a playlist or a Daily Wire
    show, whose collection is known by it, and the channel's id with the feed's for a feed."""
    return f"{channel_ref}-{section.ref}" if section.kind == SectionKind.FEED else section.ref


def _main_feed(sections: Sequence[SectionRef | ChannelSection]) -> SectionRef | ChannelSection | None:
    return next((section for section in sections if section.kind == SectionKind.FEED and section.role == SectionRole.MAIN), None)


def lists_are_seasons(site: Site | None) -> bool:
    """Whether a list of the channel can be a season of the channel's own collection."""
    return site is not None and site.link_seasons


def _takes_uploads(collection: Collection) -> bool:
    """Whether the collection lists all of a channel's uploads: its Videos page, which has its Shorts and Live too."""
    return collection.sharing_url is not None and get_source(collection.source_key).is_channel_page(collection.sharing_url)


def sections_in_library(
    s: Session, source_key: str, channel_ref: str, sections: Sequence[SectionRef | ChannelSection],
    main: Collection | None = None,
) -> dict[str, str]:
    """The slugs of the collections that already keep a section, by the section's ref: a collection made from its
    link, one known by the slug its own collection would get, or the channel's own collection ``main``, which keeps
    the feeds its Videos page lists and the playlists that are its seasons. Works on a channel being looked up and
    on a saved one."""
    urls = {section.url: section.ref for section in sections}
    slugs = {section_collection_slug(channel_ref, section): section.ref for section in sections}
    main_feed = _main_feed(sections)
    slugs[channel_ref] = main_feed.ref if main_feed is not None else ""
    found: dict[str, str] = {}
    for url, slug in s.execute(
        select(Collection.sharing_url, Collection.slug).where(Collection.source_key == source_key, Collection.sharing_url.in_(urls))
    ):
        found.setdefault(urls[url], slug)
    for slug in s.scalars(select(Collection.slug).where(Collection.source_key == source_key, Collection.slug.in_(slugs))):
        if slugs[slug]:
            found.setdefault(slugs[slug], slug)
    if main is not None:
        uploads = _takes_uploads(main)
        on = main.link_seasons != LinkSeasons.OFF.value
        seasons = {link.ref for link in main.lists if on and is_season(main, link)}
        for section in sections:
            if section.ref in seasons:
                # The channel placed the list in its own collection; a collection of the list left from before keeps
                # only what the list no longer has.
                found[section.ref] = main.slug
            elif section.kind == SectionKind.FEED and uploads:
                # A collection of its own, such as one of the channel's Shorts, keeps it before the channel's.
                found.setdefault(section.ref, main.slug)
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
        description=section.description, access=section.access,
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
    collections = _place(s, channel, plans, settings, added_by_id=added_by_id)
    return channel, collections


def new_link_seasons(channel: Channel) -> NewLinkSeasonAction:
    """What the channel's own collection does with a new playlist: what the channel does with a new section. The
    channel's daily look finds them and places them; the collection only follows."""
    match NewSectionAction(channel.new_sections):
        case NewSectionAction.ASK:
            return NewLinkSeasonAction.ASK
        case NewSectionAction.SEASON:
            return NewLinkSeasonAction.ADD
        case _:
            return NewLinkSeasonAction.IGNORE


def _make_seasons(channel: Channel, main: Collection, refs: set[str]) -> None:
    """Make the lists ``refs`` seasons of the channel's own collection, which then knows all the channel's lists."""
    # The channel decides which of its lists are seasons, the ones to come too, so the collection only takes the ones
    # the channel gives it.
    main.link_seasons = LinkSeasons.SELECTED.value
    main.new_link_seasons = new_link_seasons(channel).value
    known = {playlist.ref: playlist for playlist in main.lists}
    for section in channel.sections:
        if section.kind != SectionKind.LIST:
            continue
        playlist = known.get(section.ref)
        if playlist is None:
            main.lists.append(CollectionList(
                ref=section.ref, url=section.url, title=section.title, image_path=section.image_path,
                item_count=section.item_count, site_position=section.site_position, enabled=section.ref in refs,
                status=ListStatus.KNOWN.value,
            ))
        elif section.ref in refs:
            playlist.enabled, playlist.status = True, ListStatus.KNOWN.value


def _place(
    s: Session, channel: Channel, plans: list[SectionPlan], settings: NewCollectionSettings, *, added_by_id: int | None,
) -> list[Collection]:
    """Give the channel's sections to the collections the plans say: the channel's own collection, made when it has
    none yet, or a new collection each. Starts indexing what changed. Returns the collections it made."""
    sections = {section.ref: section for section in channel.sections}
    kept = sections_in_library(s, channel.source_key, channel.site_ref, list(sections.values()), channel.main_collection)
    site = get_source(channel.source_key).site_of(channel.site_key)
    wanted = []
    for plan in plans:
        if plan.target is SectionTarget.SKIP or plan.ref in kept:
            continue
        section = sections[plan.ref]
        section.status = SectionStatus.KNOWN.value
        # A list goes into the channel's own collection only as one of its seasons, and a show, with seasons of its
        # own, always has a collection of its own.
        if plan.target is SectionTarget.MAIN and (
            section.kind == SectionKind.SHOW or (section.kind == SectionKind.LIST and not lists_are_seasons(site))
        ):
            plan = SectionPlan(plan.ref, SectionTarget.OWN)
        wanted.append(plan)
    main_plans = [plan for plan in wanted if plan.target is SectionTarget.MAIN]
    made, changed = [], []
    if main_plans:
        main = channel.main_collection
        if main is None:
            main_feed = _main_feed(list(sections.values()))
            url = main_feed.url if main_feed is not None else channel.url
            if not url:
                raise ServiceError(f"{channel.title} has no page that lists all of its videos")
            # An artist without a picture of their own shows their newest album's cover.
            image = channel.avatar_path or next((sections[plan.ref].image_path for plan in main_plans if sections[plan.ref].image_path), None)
            main = _new_collection(
                s, channel, settings, title=channel.title, slug=channel.site_ref, url=url, description=channel.description,
                image=image, added_by_id=added_by_id,
            )
            channel.main_collection = main
            made.append(main)
        else:
            changed.append(main)
        lists = {plan.ref for plan in main_plans if sections[plan.ref].kind == SectionKind.LIST}
        if lists:
            _make_seasons(channel, main, lists)
    for plan in wanted:
        if plan.target is not SectionTarget.OWN:
            continue
        own = sections[plan.ref]
        title = own.title if own.kind != SectionKind.FEED else f"{channel.title} {own.title}"
        made.append(_new_collection(
            s, channel, settings, title=title, slug=section_collection_slug(channel.site_ref, own), url=own.url,
            description=own.description, image=own.image_path, added_by_id=added_by_id,
        ))
    s.flush()
    for collection in made:
        index_new_collection(s, collection)
    for collection in changed:
        reindex_collection(s, collection)
    return made


def _new_collection(
    s: Session, channel: Channel, settings: NewCollectionSettings, *, title: str, slug: str, url: str,
    description: str | None, image: str | None, added_by_id: int | None,
) -> Collection:
    collection = Collection(
        uuid=generate_uuid(), slug=_unique_slug(s, Collection, slug), source_key=channel.source_key, title=title,
        description=description, sharing_url=url, membership_level=settings.membership_level,
        type=settings.type.value, episode_identifier=settings.episode_identifier.value, author_name=channel.title,
        author_slug=slugify(channel.handle or channel.title) or channel.site_ref, thumbnail_landscape_path=image,
        genre=channel.genre, content_rating=channel.content_rating,
    )
    add_collection(s, collection, added_by_id=added_by_id)
    collection.channel = channel
    return collection


def _settings_of(channel: Channel) -> NewCollectionSettings:
    """What a collection added to the channel later starts with: the same as the channel's own collection."""
    model = channel.main_collection or next(iter(channel.collections), None)
    if model is None:
        return NewCollectionSettings(CollectionType.SERIES, EpisodeIdentifier.SEASONAL, DwMembershipLevel.HIGHEST_ALLOWED.value)
    return NewCollectionSettings(CollectionType(model.type), EpisodeIdentifier(model.episode_identifier), model.membership_level)


def place_sections(s: Session, channel: Channel, plans: list[SectionPlan], *, added_by_id: int | None = None) -> list[Collection]:
    """Add sections of a channel that is in the Library to its collections, or ignore them.

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
    return _place(s, channel, adding, _settings_of(channel), added_by_id=added_by_id)


def _as_ref(section: ChannelSection) -> SectionRef:
    return SectionRef(
        ref=section.ref, url=section.url, title=section.title, kind=SectionKind(section.kind), role=SectionRole(section.role),
    )


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
    if channel.main_collection is not None:
        channel.main_collection.new_link_seasons = new_link_seasons(channel).value
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
    and the sections it did not have before, which the channel's setting adds, ignores or asks about, new playlists
    too. Sections the Site no longer lists stay, with what they hold.

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
    main = channel.main_collection
    # A section that is already in the library, such as a show added before the channel, needs no choice, and a
    # single item, such as a movie, is added from its own page.
    kept = sections_in_library(s, channel.source_key, channel.site_ref, found, main)
    for record in found:
        if record.ref in kept or record.kind == SectionKind.ITEM:
            record.status = SectionStatus.KNOWN.value
    found = [record for record in found if record.status == SectionStatus.NEW.value]
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
    # A show keeps its own seasons, so it becomes a collection of its own; _place sees to that.
    plans = [SectionPlan(record.ref, target) for record in addable]
    place_sections(s, channel, plans)
    return FollowResult([record for record in found if record not in addable], addable, [])


def _site_key_of(source_key: str) -> str:
    # A channel without a page of its own, such as a Daily Wire host, is on its Source's one Site.
    sites = get_source(source_key).sites
    if len(sites) != 1:
        raise ServiceError("This channel has no link, and its Site could not be told")
    return sites[0].key


def collection_section(
    s: Session, collection: Collection, source_key: str, details: ChannelDetails, channel: Channel | None,
) -> tuple[SectionRef | ChannelSection | None, Collection | None]:
    """The section of the channel the collection is: the section at its link, the channel's Videos page for a
    collection of all its uploads, or the section it is known by, such as a playlist added by its own link before.
    Also another of the channel's collections that keeps that section already, when one does."""
    sections: Sequence[SectionRef | ChannelSection] = channel.sections if channel is not None else details.sections
    section = next((section for section in sections if section.url == collection.sharing_url), None)
    if section is None and _takes_uploads(collection):
        section = _main_feed(sections)
    if section is None:
        kept = sections_in_library(s, source_key, details.ref, list(sections))
        ref = next((ref for ref, slug in kept.items() if slug == collection.slug), None)
        section = next((section for section in sections if section.ref == ref), None)
    if section is None or channel is None:
        return section, None
    for other in channel.collections:
        if other.id == collection.id:
            continue
        if other.id == channel.main_collection_id:
            keeps = (section.kind == SectionKind.FEED and _takes_uploads(other)) or _season_of_main(channel, section.ref) is not None
        else:
            keeps = other.sharing_url == section.url or other.slug == section_collection_slug(channel.site_ref, section)
        if keeps:
            return section, other
    return section, None


@dataclass(frozen=True)
class Overlap:
    """A list that a collection joining a channel holds, which another of the channel's collections holds already."""

    ref: str
    title: str
    kept_by: Collection
    can_move_here: bool
    """The other collection is the channel's own, which can let the list go; a collection of its own can't."""


def _season_of_main(channel: Channel, ref: str) -> CollectionList | None:
    main = channel.main_collection
    if main is None or main.link_seasons == LinkSeasons.OFF.value:
        return None
    return next((link for link in main.lists if link.ref == ref and is_season(main, link)), None)


def join_overlaps(
    s: Session, collection: Collection, source_key: str, details: ChannelDetails, channel: Channel | None,
) -> list[Overlap]:
    """The lists that would be in two places once the collection joins the channel: the section it is, when the
    channel's own collection has it as a season, and the lists that are its seasons that another of the channel's
    collections holds. Once it joins, each is in one place, as the user chooses."""
    if channel is None:
        return []
    section, keeper = collection_section(s, collection, source_key, details, channel)
    overlaps: list[Overlap] = []
    if section is not None and keeper is not None and _season_of_main(channel, section.ref) is not None:
        overlaps.append(Overlap(section.ref, section.title, keeper, True))
    if collection.link_seasons == LinkSeasons.OFF.value:
        return overlaps
    sections = {section.ref: section for section in channel.sections if section.kind == SectionKind.LIST}
    for link in collection.lists:
        if link.ref not in sections or not is_season(collection, link):
            continue
        if _season_of_main(channel, link.ref) is not None and channel.main_collection_id != collection.id:
            overlaps.append(Overlap(link.ref, link.title, channel.main_collection, True))
            continue
        kept = sections_in_library(s, channel.source_key, channel.site_ref, [sections[link.ref]])
        other = next((other for other in channel.collections if other.slug == kept.get(link.ref) and other.id != collection.id), None)
        if other is not None:
            overlaps.append(Overlap(link.ref, link.title, other, False))
    return overlaps


def join_channel(
    s: Session, collection: Collection, *, source_key: str, details: ChannelDetails, added_by_id: int | None = None,
    move_here: frozenset[str] = frozenset(),
) -> Channel:
    """Make a collection one of a channel's, adding the channel when it is not in the Library yet. Nothing is indexed
    again and no file moves. A list that would be in two places stays in one: in the collection when its ref is in
    ``move_here`` and the channel's own collection can let it go, and otherwise where it was.

    ``details`` was looked up before the write transaction. ``s`` is a write transaction's session."""
    if collection.channel_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.channel.title}")
    site = channel_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    channel = channel_in_library(s, record.key, details.ref)
    if channel is None:
        channel = _new_channel(s, source_key, record.key, details, added_by_id=added_by_id)
    section, keeper = collection_section(s, collection, source_key, details, channel)
    if not isinstance(section, ChannelSection):
        raise ServiceError(f"{collection.title} is not a playlist, show or the videos of {channel.title}")
    overlaps = join_overlaps(s, collection, source_key, details, channel)
    if keeper is not None and not any(overlap.ref == section.ref and overlap.ref in move_here for overlap in overlaps):
        raise ServiceError(f"{keeper.title} already keeps this part of {channel.title}")
    changed: set[int] = set()
    for overlap in overlaps:
        if overlap.ref in move_here and overlap.can_move_here:
            _switch_off(overlap.kept_by, overlap.ref)
            changed.add(overlap.kept_by.id)
        else:
            _switch_off(collection, overlap.ref)
            changed.add(collection.id)
    section.status = SectionStatus.KNOWN.value
    collection.channel = channel
    if section.kind == SectionKind.FEED and section.role == SectionRole.MAIN and channel.main_collection is None:
        channel.main_collection = collection
    s.flush()
    for collection_id in changed:
        from backend.services.link_seasons import place_in_link_seasons

        place_in_link_seasons(s, s.get(Collection, collection_id), by_user=True)
    return channel


def _switch_off(collection: Collection, ref: str) -> None:
    """Stop a list being a season of the collection. One that made every list a season keeps the others on."""
    if collection.link_seasons == LinkSeasons.ALL.value:
        for link in collection.lists:
            link.enabled = True
        collection.link_seasons = LinkSeasons.SELECTED.value
    for link in collection.lists:
        if link.ref == ref:
            link.enabled = False


def leave_channel(s: Session, collection: Collection) -> None:
    """Make a channel's collection a plain one again. It keeps its episodes, files and settings.

    ``s`` is a write transaction's session."""
    channel = collection.channel
    if channel is None:
        raise ServiceError(f"{collection.title} is not in a {collection_site(collection).channel_label}")
    if channel.main_collection_id == collection.id:
        channel.main_collection = None
    collection.channel = None
    s.flush()


ARTIST_LABEL = "artist"
"""What VODLoft calls a channel that has a Music collection."""


def channel_label(channel: Channel) -> str:
    """What the channel is called: an artist when it has a Music collection, and otherwise what its Site calls it."""
    if any(collection.type == CollectionType.MUSIC.value for collection in channel.collections):
        return ARTIST_LABEL
    site = get_source(channel.source_key).site_of(channel.site_key)
    return site.channel_label if site is not None else "channel"


def add_to_channel(s: Session, collection: Collection, channel: Channel) -> None:
    """Make a collection one of a channel's although its link is somewhere else, such as an artist's music videos
    on a channel or playlist of their label. It keeps its own link, and the channel's look for new sections leaves
    it alone. Nothing is indexed again and no file moves.

    ``s`` is a write transaction's session."""
    if collection.channel_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.channel.title}")
    if collection.sharing_url is not None and any(section.url == collection.sharing_url for section in channel.sections):
        raise ServiceError(
            f"{collection.title} is a part of {channel.title}'s own page: add it to the {channel_label(channel)} "
            "behind its link instead", field="channel_slug",
        )
    collection.channel = channel
    s.flush()
