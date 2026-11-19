"""Creators: who made the work, with an account on one or more Sites, whose sections go into collections.

A creator never indexes anything itself. Adding an account makes the creator's own collection for it, which takes all
its uploads from its Videos page, and a collection of its own for each section that goes elsewhere. On a Site whose
lists can be seasons, a list, such as a playlist, that goes into that collection becomes one of its seasons. The
creator alone decides where each section goes: the daily look at each account finds new sections, also new
playlists, and the creator's one setting says what happens with them. A show, with seasons of its own, is always a
collection of its own. A creator can have accounts on several Sites, such as a YouTube channel and a page as a Daily
Wire host, and collections from any other link can join them too.
"""
from __future__ import annotations

from collections.abc import Collection as Refs, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.db.models import Creator, CreatorAccount, CreatorSection, Collection, CollectionList, Movie
from backend.services.link_seasons import is_season
from backend.services.collections import add_collection, index_new_collection, reindex_collection
from backend.services.errors import ServiceError
from backend.services.sites import collection_site, site_record
from backend.types.creator_types import NewSectionAction, SectionStatus, SectionTarget
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.link_season_types import NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos
from backend.utils.helpers import generate_uuid, slugify
from sources import (
    CreatorDetails, CreatorPreset, CreatorSectionNames, Feature, SectionKind, SectionRef, SectionRole, Site, UnknownSourceError, get_source, site_of,
)


FOLLOW_TASK_KEY = "follow_creators"


@dataclass(frozen=True)
class SectionPlan:
    """Where one section goes. A section that becomes a collection of its own takes ``type`` and
    ``episode_identifier`` when they are given, and otherwise those every collection of the creator starts with."""

    ref: str
    target: SectionTarget
    type: CollectionType | None = None
    episode_identifier: EpisodeIdentifier | None = None


def creator_site(source_key: str, url_or_site_key: str) -> Site:
    """The Site of a creator, which must offer creators."""
    try:
        source = get_source(source_key)
    except UnknownSourceError as exc:
        raise ServiceError(str(exc)) from exc
    site = source.site_for(url_or_site_key) if url_or_site_key.startswith("http") else source.site_of(url_or_site_key)
    if not source.has(Feature.CREATORS) or site is None or not site.creators:
        raise ServiceError(f"{site.name if site else source.name} has no creators VODLoft can add")
    return site


def _usable(section: SectionRef) -> bool:
    # A section only some members can watch is left for the user to pick; a single item is added on its own page,
    # unless it is a movie (see preset_plan).
    return section.access is None and section.kind is not SectionKind.ITEM


def takes_movies(source_key: str) -> bool:
    """Whether the creator's single items are movies VODLoft can add, such as a Daily Wire host's movies."""
    return get_source(source_key).has(Feature.MOVIES)


def preset_plan(
    details: CreatorDetails, preset: CreatorPreset, *, feeds: bool = True, movies: bool = False,
    movies_in_library: Refs[str] = (),
) -> list[SectionPlan]:
    """What a preset does with each section. The user can change any of it before the creator is added. Without
    ``feeds``, such as for a music artist on a video site, whose uploads are much more than their albums, the feeds
    start skipped, so the artist's collection holds only what their lists give it.

    With ``movies``, the creator's single items are movies: the presets add them, and a movie already in the library,
    by its ref in ``movies_in_library``, joins the creator with every preset."""
    plans = []
    for section in details.sections:
        target = SectionTarget.SKIP
        if movies and section.kind is SectionKind.ITEM:
            if section.ref in movies_in_library or (preset is not CreatorPreset.PICK and section.access is None):
                target = SectionTarget.OWN
        elif preset is not CreatorPreset.PICK and _usable(section):
            # The creator's own collection lists its Shorts and Live too, tagged, so they need no collection of their own.
            if section.kind is SectionKind.FEED:
                target = SectionTarget.MAIN if feeds else SectionTarget.SKIP
            elif section.kind is SectionKind.SHOW or preset is CreatorPreset.PER_LIST:
                target = SectionTarget.OWN
            else:
                target = SectionTarget.MAIN
        plans.append(SectionPlan(section.ref, target))
    return plans


def section_collection_slug(creator_ref: str, section: SectionRef | CreatorSection) -> str:
    """The slug a section's own collection gets: its own id for a list or a show, such as a playlist or a Daily Wire
    show, whose collection is known by it, and the creator's id with the feed's for a feed."""
    return f"{creator_ref}-{section.ref}" if section.kind == SectionKind.FEED else section.ref


def _main_feed(sections: Sequence[SectionRef | CreatorSection]) -> SectionRef | CreatorSection | None:
    return next((section for section in sections if section.kind == SectionKind.FEED and section.role == SectionRole.MAIN), None)


_NO_SEASONS = "{site} has no lists that can be seasons, so new {sections} can't be added as seasons"


def new_sections_can_be_seasons(creator: Creator) -> bool:
    """Whether "Add it as a season" fits the creator: one of their accounts is on a Site whose lists can be seasons
    of the account's own collection, such as YouTube, and unlike The Daily Wire."""
    return any(lists_are_seasons(_site(account.source_key, account.site_key)) for account in creator.accounts)


def lists_are_seasons(site: Site | None) -> bool:
    """Whether a list of the creator can be a season of the creator's own collection."""
    return site is not None and site.link_seasons


def _takes_uploads(collection: Collection) -> bool:
    """Whether the collection lists all of a creator's uploads: its Videos page, which has its Shorts and Live too,
    unless it holds only what its link seasons give it."""
    return (
        collection.sharing_url is not None and collection.outside_videos != OutsideVideos.ONLY.value
        and get_source(collection.source_key).is_creator_page(collection.sharing_url)
    )


def sections_in_library(
    s: Session, source_key: str, creator_ref: str, sections: Sequence[SectionRef | CreatorSection],
    main: Collection | None = None,
) -> dict[str, str]:
    """The slugs of the collections that already keep a section, by the section's ref: a collection made from its
    link, one known by the slug its own collection would get, or the creator's own collection ``main``, which keeps
    the feeds its Videos page lists and the playlists that are its seasons. Works on a creator being looked up and
    on a saved one."""
    urls = {section.url: section.ref for section in sections}
    slugs = {section_collection_slug(creator_ref, section): section.ref for section in sections}
    main_feed = _main_feed(sections)
    slugs[creator_ref] = main_feed.ref if main_feed is not None else ""
    found: dict[str, str] = {}
    for url, slug, outside in s.execute(
        select(Collection.sharing_url, Collection.slug, Collection.outside_videos)
        .where(Collection.source_key == source_key, Collection.sharing_url.in_(urls))
    ):
        # A collection that holds only what its lists give it, such as an artist's albums, doesn't keep its link's feed.
        if outside != OutsideVideos.ONLY.value:
            found.setdefault(urls[url], slug)
    for slug, outside in s.execute(
        select(Collection.slug, Collection.outside_videos).where(Collection.source_key == source_key, Collection.slug.in_(slugs))
    ):
        if slugs[slug] and not (slug == creator_ref and outside == OutsideVideos.ONLY.value):
            found.setdefault(slugs[slug], slug)
    if main is not None:
        uploads = _takes_uploads(main)
        on = main.link_seasons != LinkSeasons.OFF.value
        seasons = {link.ref for link in main.lists if on and is_season(main, link)}
        for section in sections:
            if section.ref in seasons:
                # The creator placed the list in its own collection; a collection of the list left from before keeps
                # only what the list no longer has.
                found[section.ref] = main.slug
            elif section.kind == SectionKind.FEED and uploads:
                # A collection of its own, such as one of the creator's Shorts, keeps it before the creator's.
                found.setdefault(section.ref, main.slug)
    return found


def account_in_library(s: Session, site_key: str, ref: str) -> CreatorAccount | None:
    return s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == site_key, CreatorAccount.site_ref == ref))


def movies_in_library(s: Session, source_key: str, sections: Sequence[SectionRef | CreatorSection]) -> dict[str, Movie]:
    """The movies in the library that are the creator's single items, by the section's ref: the movie known by the
    item's id or made from its link. Empty where the creator's single items aren't movies."""
    items = [section for section in sections if section.kind == SectionKind.ITEM]
    if not items or not takes_movies(source_key):
        return {}
    by_slug = {section.ref: section.ref for section in items}
    by_url = {section.url: section.ref for section in items}
    found: dict[str, Movie] = {}
    for movie in s.scalars(select(Movie).where(
        Movie.source_key == source_key, or_(Movie.slug.in_(by_slug), Movie.sharing_url.in_(by_url)),
    )):
        ref = by_slug.get(movie.slug) or by_url.get(movie.sharing_url or "")
        if ref is not None:
            found.setdefault(ref, movie)
    return found


def movies_to_add(
    s: Session, source_key: str, sections: Sequence[SectionRef | CreatorSection], plans: Sequence[SectionPlan],
) -> list[str]:
    """The refs of the creator's movies that the plans add and that aren't in the library yet, which the Source
    looks up before the write transaction."""
    if not takes_movies(source_key):
        return []
    items = {section.ref for section in sections if section.kind == SectionKind.ITEM}
    kept = movies_in_library(s, source_key, sections)
    return [plan.ref for plan in plans if plan.target is not SectionTarget.SKIP and plan.ref in items and plan.ref not in kept]


def join_movies(s: Session, account: CreatorAccount, plans: Sequence[SectionPlan]) -> list[Movie]:
    """Make the movies the plans pick, which are in the library now, the account's creator's. A movie the plans skip
    stays as it is. Returns the movies that joined.

    ``s`` is a write transaction's session."""
    picked = {plan.ref for plan in plans if plan.target is not SectionTarget.SKIP}
    joined = []
    for ref, movie in movies_in_library(s, account.source_key, account.sections).items():
        if ref in picked and movie.creator_id != account.creator.id:
            movie.creator = account.creator
            joined.append(movie)
    s.flush()
    return joined


def _unique_slug(s: Session, model, wanted: str) -> str:
    """``wanted`` itself while it is free, since a Source may know a collection by it; else a slug made from it."""
    if wanted and s.scalar(select(model.id).where(model.slug == wanted)) is None:
        return wanted
    base = slugify(wanted) or "creator"
    slug, suffix = base, 2
    while s.scalar(select(model.id).where(model.slug == slug)) is not None:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    return slug


@dataclass(frozen=True)
class NewCollectionSettings:
    """What every collection made from a creator starts with."""

    type: CollectionType
    episode_identifier: EpisodeIdentifier
    membership_level: str


def _section_record(section: SectionRef, position: int, status: SectionStatus = SectionStatus.KNOWN) -> CreatorSection:
    return CreatorSection(
        ref=section.ref, url=section.url, title=section.title, kind=section.kind.value, role=section.role.value,
        kind_label=section.kind_label, item_count=section.item_count, image_path=section.image_url,
        description=section.description, access=section.access,
        site_position=position, status=status.value,
    )


def _new_account(s: Session, creator: Creator, source_key: str, site_key: str, details: CreatorDetails) -> CreatorAccount:
    account = CreatorAccount(
        source_key=source_key, site_key=site_key, site_ref=details.ref, url=details.url, handle=details.handle,
    )
    account.sections = [_section_record(section, position) for position, section in enumerate(details.sections)]
    creator.accounts.append(account)
    s.flush()
    return account


def _new_creator(
    s: Session, source_key: str, site_key: str, details: CreatorDetails, *, added_by_id: int | None,
    new_sections: NewSectionAction = NewSectionAction.ASK,
) -> CreatorAccount:
    """A new creator with their first account, which is returned."""
    creator = Creator(
        uuid=generate_uuid(), slug=_unique_slug(s, Creator, slugify(details.handle or details.title) or details.ref),
        title=details.title, description=details.description, avatar_path=details.avatar_url,
        banner_path=details.banner_url, links=list(details.links), facts=list(details.facts), added_by_id=added_by_id,
        new_sections=new_sections.value,
    )
    s.add(creator)
    return _new_account(s, creator, source_key, site_key, details)


def add_creator(
    s: Session, *, source_key: str, details: CreatorDetails, plans: list[SectionPlan], settings: NewCollectionSettings,
    added_by_id: int | None = None, new_sections: NewSectionAction = NewSectionAction.ASK, into: Creator | None = None,
) -> tuple[Creator, list[Collection]]:
    """Put a creator in the Library with the collections their sections go to, and start indexing them. With
    ``into``, the account joins that creator in the Library instead, such as a host's YouTube channel joining the
    host, and follows that creator's settings.

    ``details`` was looked up before the write transaction. Sections already kept by a collection are left where they
    are. Returns the creator and the collections it made."""
    site = creator_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    existing = account_in_library(s, record.key, details.ref)
    if existing is not None:
        raise ServiceError(f"{details.title} is already in your library, as {existing.creator.title}", field="into")
    by_ref = {section.ref: section for section in details.sections}
    unknown = [plan.ref for plan in plans if plan.ref not in by_ref]
    if unknown:
        raise ServiceError(f"{details.title} has no section {unknown[0]}")
    if into is not None:
        account = _new_account(s, into, source_key, record.key, details)
    else:
        if new_sections is NewSectionAction.SEASON and not lists_are_seasons(site):
            raise ServiceError(_NO_SEASONS.format(site=site.name, sections=site.creator_sections.many), field="new_sections")
        account = _new_creator(s, source_key, record.key, details, added_by_id=added_by_id, new_sections=new_sections)
    collections = _place(s, account, plans, settings, added_by_id=added_by_id)
    join_movies(s, account, plans)
    return account.creator, collections


def new_link_seasons(creator: Creator) -> NewLinkSeasonAction:
    """What the creator's own collection does with a new playlist: what the creator does with a new section. The
    creator's daily look finds them and places them; the collection only follows."""
    match NewSectionAction(creator.new_sections):
        case NewSectionAction.ASK:
            return NewLinkSeasonAction.ASK
        case NewSectionAction.SEASON:
            return NewLinkSeasonAction.ADD
        case _:
            return NewLinkSeasonAction.IGNORE


def _make_seasons(account: CreatorAccount, main: Collection, refs: set[str]) -> None:
    """Make the lists ``refs`` seasons of the account's own collection, which then knows all the account's lists."""
    # The creator decides which of their lists are seasons, the ones to come too, so the collection only takes the
    # ones the creator gives it.
    main.link_seasons = LinkSeasons.SELECTED.value
    main.new_link_seasons = new_link_seasons(account.creator).value
    known = {playlist.ref: playlist for playlist in main.lists}
    for section in account.sections:
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
    s: Session, account: CreatorAccount, plans: list[SectionPlan], settings: NewCollectionSettings, *,
    added_by_id: int | None,
) -> list[Collection]:
    """Give the account's sections to the collections the plans say: the account's own collection, made when it has
    none yet, or a new collection each. Starts indexing what changed. Returns the collections it made."""
    creator = account.creator
    sections = {section.ref: section for section in account.sections}
    kept = sections_in_library(s, account.source_key, account.site_ref, list(sections.values()), account.main_collection)
    site = get_source(account.source_key).site_of(account.site_key)
    wanted = []
    for plan in plans:
        if plan.target is SectionTarget.SKIP or plan.ref in kept:
            continue
        section = sections[plan.ref]
        section.status = SectionStatus.KNOWN.value
        if section.kind == SectionKind.ITEM:
            # A single item, such as a movie, is never a collection: join_movies takes the movies.
            continue
        # A list goes into the creator's own collection only as one of its seasons, and a show, with seasons of its
        # own, always has a collection of its own.
        if plan.target is SectionTarget.MAIN and (
            section.kind == SectionKind.SHOW or (section.kind == SectionKind.LIST and not lists_are_seasons(site))
        ):
            plan = replace(plan, target=SectionTarget.OWN)
        wanted.append(plan)
    main_plans = [plan for plan in wanted if plan.target is SectionTarget.MAIN]
    made, changed = [], []
    if main_plans:
        main = account.main_collection
        if main is None:
            main_feed = _main_feed(list(sections.values()))
            url = main_feed.url if main_feed is not None else account.url
            if not url:
                raise ServiceError(f"{creator.title} has no page that lists all of its videos")
            # An artist without a picture of their own shows their newest album's cover.
            image = creator.avatar_path or next((sections[plan.ref].image_path for plan in main_plans if sections[plan.ref].image_path), None)
            main = _new_collection(
                s, account, settings, title=creator.title, slug=account.site_ref, url=url,
                description=creator.description, image=image, added_by_id=added_by_id,
            )
            account.main_collection = main
            made.append(main)
        else:
            changed.append(main)
        # Without a feed, the creator's collection holds only what its lists give it; a feed brings its uploads back.
        if any(sections[plan.ref].kind == SectionKind.FEED for plan in main_plans):
            if main.outside_videos == OutsideVideos.ONLY.value:
                main.outside_videos = OutsideVideos.LEAVE_OUT.value
        elif main in made:
            main.outside_videos = OutsideVideos.ONLY.value
        lists = {plan.ref for plan in main_plans if sections[plan.ref].kind == SectionKind.LIST}
        if lists:
            _make_seasons(account, main, lists)
    for plan in wanted:
        if plan.target is not SectionTarget.OWN:
            continue
        own = sections[plan.ref]
        title = own.title if own.kind != SectionKind.FEED else f"{creator.title} {own.title}"
        made.append(_new_collection(
            s, account, _own_settings(settings, plan, own), title=title, slug=section_collection_slug(account.site_ref, own), url=own.url,
            description=own.description, image=own.image_path, added_by_id=added_by_id,
        ))
    s.flush()
    for collection in made:
        index_new_collection(s, collection)
    for collection in changed:
        reindex_collection(s, collection)
    return made


def belong_to(collection: Collection, creator: Creator | None) -> None:
    """Make the collection one of the creator's, or a plain one again with None. A creator's collection takes the
    creator's name as its author."""
    collection.creator = creator
    if creator is not None:
        collection.author_name = creator.title


def rename_creator(creator: Creator, title: str) -> None:
    """Give the creator a new name, which its collections take as their author."""
    creator.title = title
    for collection in creator.collections:
        collection.author_name = title


def _own_settings(settings: NewCollectionSettings, plan: SectionPlan, section: CreatorSection) -> NewCollectionSettings:
    """What a section's collection of its own starts with: the plan's type and identification, where it gives them.
    An artist's collections always hold music, and only an artist's do."""
    if settings.type is CollectionType.MUSIC:
        return settings
    if plan.type is CollectionType.MUSIC:
        raise ServiceError(f"{section.title} can only be a Music collection when the creator is a music artist", field="sections")
    return replace(
        settings, type=plan.type or settings.type, episode_identifier=plan.episode_identifier or settings.episode_identifier,
    )


def _new_collection(
    s: Session, account: CreatorAccount, settings: NewCollectionSettings, *, title: str, slug: str, url: str,
    description: str | None, image: str | None, added_by_id: int | None,
) -> Collection:
    creator = account.creator
    collection = Collection(
        uuid=generate_uuid(), slug=_unique_slug(s, Collection, slug), source_key=account.source_key, title=title,
        description=description, sharing_url=url, membership_level=settings.membership_level,
        type=settings.type.value, episode_identifier=settings.episode_identifier.value, author_name=creator.title,
        author_slug=slugify(account.handle or creator.title) or account.site_ref, thumbnail_landscape_path=image,
        genre=creator.genre, content_rating=creator.content_rating,
    )
    add_collection(s, collection, added_by_id=added_by_id)
    belong_to(collection, creator)
    return collection


def _settings_of(creator: Creator) -> NewCollectionSettings:
    """What a collection added to the creator later starts with: the same as the creator's own collection."""
    model = next((account.main_collection for account in creator.accounts if account.main_collection is not None), None)
    model = model or next(iter(creator.collections), None)
    if model is None:
        return NewCollectionSettings(CollectionType.SERIES, EpisodeIdentifier.SEASONAL, DwMembershipLevel.HIGHEST_ALLOWED.value)
    return NewCollectionSettings(CollectionType(model.type), EpisodeIdentifier(model.episode_identifier), model.membership_level)


def place_sections(
    s: Session, account: CreatorAccount, plans: list[SectionPlan], *, added_by_id: int | None = None,
    type: CollectionType | None = None, episode_identifier: EpisodeIdentifier | None = None,
) -> list[Collection]:
    """Add sections of a creator's account that is in the Library to the creator's collections, or ignore them.

    A section that becomes a collection of its own gets ``type`` and ``episode_identifier`` when they are given, and
    otherwise those of the creator's own collection. ``s`` is a write transaction's session."""
    creator = account.creator
    sections = {section.ref: section for section in account.sections}
    unknown = [plan.ref for plan in plans if plan.ref not in sections]
    if unknown:
        raise ServiceError(f"{creator.title} has no section {unknown[0]}", field="sections")
    for plan in plans:
        if plan.target is SectionTarget.SKIP:
            sections[plan.ref].status = SectionStatus.IGNORED.value
    adding = [plan for plan in plans if plan.target is not SectionTarget.SKIP]
    if not adding:
        return []
    settings = _settings_of(creator)
    settings = replace(
        settings, type=type or settings.type, episode_identifier=episode_identifier or settings.episode_identifier,
    )
    made = _place(s, account, adding, settings, added_by_id=added_by_id)
    join_movies(s, account, adding)
    return made


def _as_ref(section: CreatorSection) -> SectionRef:
    return SectionRef(
        ref=section.ref, url=section.url, title=section.title, kind=SectionKind(section.kind), role=SectionRole(section.role),
    )


@dataclass(frozen=True)
class CreatorSettings:
    new_sections: NewSectionAction
    genre: str | None
    content_rating: str | None


def update_creator_settings(s: Session, creator: Creator, settings: CreatorSettings) -> None:
    """Change what happens with the creator's new sections, and the genre and rating its collections get. A
    collection that had the creator's old genre or rating gets the new one; one with its own keeps it.

    ``s`` is a write transaction's session."""
    if settings.new_sections is NewSectionAction.SEASON and not new_sections_can_be_seasons(creator):
        raise ServiceError(
            _NO_SEASONS.format(site=" or ".join(sorted({site.name for site in _sites(creator).values()})),
                               sections=creator_sections(creator).many),
            field="new_sections",
        )
    creator.new_sections = settings.new_sections.value
    for account in creator.accounts:
        if account.main_collection is not None:
            account.main_collection.new_link_seasons = new_link_seasons(creator).value
    for field in ("genre", "content_rating"):
        old, new = getattr(creator, field), getattr(settings, field) or None
        if old == new:
            continue
        for collection in creator.collections:
            if getattr(collection, field) in (old, None):
                setattr(collection, field, new)
        setattr(creator, field, new)


@dataclass(frozen=True)
class FollowResult:
    """What the daily look found on a creator."""

    asked: list[CreatorSection]
    added: list[CreatorSection]
    ignored: list[CreatorSection]


def follow_account(s: Session, account: CreatorAccount, details: CreatorDetails, *, now: datetime) -> FollowResult:
    """Take in what the Site says about a creator's account now: its handle and its sections' titles and counts, the
    sections it did not have before, which the creator's setting adds, ignores or asks about, new playlists too, and
    for the creator's first account the creator's name (unless the user gave it one), pictures and facts. Sections the Site no longer lists stay,
    with what they hold.

    ``details`` was looked up before the write transaction; ``s`` is a write transaction's session."""
    creator = account.creator
    if creator.accounts[0] is account:
        # A name the user gave stays.
        if details.title and details.title != creator.title and not creator.title_from_user:
            rename_creator(creator, details.title)
        for field, value in (
            ("description", details.description),
            ("avatar_path", details.avatar_url), ("banner_path", details.banner_url),
            ("links", list(details.links)), ("facts", list(details.facts)),
        ):
            if value and getattr(creator, field) != value:
                setattr(creator, field, value)
    for field, value in (("handle", details.handle), ("url", details.url)):
        if value and getattr(account, field) != value:
            setattr(account, field, value)
    account.checked_at = now
    known = {section.ref: section for section in account.sections}
    found: list[CreatorSection] = []
    for position, section in enumerate(details.sections):
        record = known.get(section.ref)
        if record is None:
            record = _section_record(section, position, SectionStatus.NEW)
            account.sections.append(record)
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
    main = account.main_collection
    # A section that is already in the library, such as a show added before the creator, needs no choice, and a
    # single item, such as a movie, is added from its own page.
    kept = sections_in_library(s, account.source_key, account.site_ref, found, main)
    for record in found:
        if record.ref in kept or record.kind == SectionKind.ITEM:
            record.status = SectionStatus.KNOWN.value
    found = [record for record in found if record.status == SectionStatus.NEW.value]
    if not found:
        return FollowResult([], [], [])
    action = NewSectionAction(creator.new_sections)
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
    place_sections(s, account, plans)
    return FollowResult([record for record in found if record not in addable], addable, [])


def _site_key_of(source_key: str) -> str:
    # A creator without a page of its own, such as a Daily Wire host, is on its Source's one Site.
    sites = get_source(source_key).sites
    if len(sites) != 1:
        raise ServiceError("This creator has no link, and its Site could not be told")
    return sites[0].key


def collection_section(
    s: Session, collection: Collection, source_key: str, details: CreatorDetails, account: CreatorAccount | None,
) -> tuple[SectionRef | CreatorSection | None, Collection | None]:
    """The section of the creator's account the collection is: the section at its link, the account's Videos page
    for a collection of all its uploads, or the section it is known by, such as a playlist added by its own link
    before. Also another of the creator's collections that keeps that section already, when one does."""
    sections: Sequence[SectionRef | CreatorSection] = account.sections if account is not None else details.sections
    section = next((section for section in sections if section.url == collection.sharing_url), None)
    if section is None and _takes_uploads(collection):
        section = _main_feed(sections)
    if section is None:
        kept = sections_in_library(s, source_key, details.ref, list(sections))
        ref = next((ref for ref, slug in kept.items() if slug == collection.slug), None)
        section = next((section for section in sections if section.ref == ref), None)
    if section is None or account is None:
        return section, None
    for other in account.creator.collections:
        if other.id == collection.id:
            continue
        if other.id == account.main_collection_id:
            keeps = (section.kind == SectionKind.FEED and _takes_uploads(other)) or _season_of_main(account, section.ref) is not None
        else:
            keeps = other.sharing_url == section.url or other.slug == section_collection_slug(account.site_ref, section)
        if keeps:
            return section, other
    return section, None


@dataclass(frozen=True)
class Overlap:
    """A list that a collection joining a creator holds, which another of the creator's collections holds already."""

    ref: str
    title: str
    kept_by: Collection
    can_move_here: bool
    """The other collection is the creator's own, which can let the list go; a collection of its own can't."""


def _season_of_main(account: CreatorAccount, ref: str) -> CollectionList | None:
    main = account.main_collection
    if main is None or main.link_seasons == LinkSeasons.OFF.value:
        return None
    return next((link for link in main.lists if link.ref == ref and is_season(main, link)), None)


def join_overlaps(
    s: Session, collection: Collection, source_key: str, details: CreatorDetails, account: CreatorAccount | None,
) -> list[Overlap]:
    """The lists that would be in two places once the collection joins the creator: the section it is, when the
    creator's own collection has it as a season, and the lists that are its seasons that another of the creator's
    collections holds. Once it joins, each is in one place, as the user chooses."""
    if account is None:
        return []
    section, keeper = collection_section(s, collection, source_key, details, account)
    overlaps: list[Overlap] = []
    if section is not None and keeper is not None and _season_of_main(account, section.ref) is not None:
        overlaps.append(Overlap(section.ref, section.title, keeper, True))
    if collection.link_seasons == LinkSeasons.OFF.value:
        return overlaps
    sections = {section.ref: section for section in account.sections if section.kind == SectionKind.LIST}
    for link in collection.lists:
        if link.ref not in sections or not is_season(collection, link):
            continue
        if _season_of_main(account, link.ref) is not None and account.main_collection_id != collection.id:
            overlaps.append(Overlap(link.ref, link.title, account.main_collection, True))
            continue
        kept = sections_in_library(s, account.source_key, account.site_ref, [sections[link.ref]])
        other = next((other for other in account.creator.collections if other.slug == kept.get(link.ref) and other.id != collection.id), None)
        if other is not None:
            overlaps.append(Overlap(link.ref, link.title, other, False))
    return overlaps


def join_creator(
    s: Session, collection: Collection, *, source_key: str, details: CreatorDetails, added_by_id: int | None = None,
    move_here: frozenset[str] = frozenset(),
) -> Creator:
    """Make a collection one of a creator's, adding the creator when it is not in the Library yet. Nothing is indexed
    again and no file moves. A list that would be in two places stays in one: in the collection when its ref is in
    ``move_here`` and the creator's own collection can let it go, and otherwise where it was.

    ``details`` was looked up before the write transaction. ``s`` is a write transaction's session."""
    if collection.creator_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.creator.title}")
    site = creator_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    account = account_in_library(s, record.key, details.ref)
    if account is None:
        account = _new_creator(s, source_key, record.key, details, added_by_id=added_by_id)
    creator = account.creator
    section, keeper = collection_section(s, collection, source_key, details, account)
    if not isinstance(section, CreatorSection):
        raise ServiceError(f"{collection.title} is not a playlist, show or the videos of {creator.title}")
    overlaps = join_overlaps(s, collection, source_key, details, account)
    if keeper is not None and not any(overlap.ref == section.ref and overlap.ref in move_here for overlap in overlaps):
        raise ServiceError(f"{keeper.title} already keeps this part of {creator.title}")
    changed: set[int] = set()
    for overlap in overlaps:
        if overlap.ref in move_here and overlap.can_move_here:
            _switch_off(overlap.kept_by, overlap.ref)
            changed.add(overlap.kept_by.id)
        else:
            _switch_off(collection, overlap.ref)
            changed.add(collection.id)
    section.status = SectionStatus.KNOWN.value
    belong_to(collection, creator)
    if section.kind == SectionKind.FEED and section.role == SectionRole.MAIN and account.main_collection is None:
        account.main_collection = collection
    s.flush()
    for collection_id in changed:
        from backend.services.link_seasons import place_in_link_seasons

        place_in_link_seasons(s, s.get(Collection, collection_id), by_user=True)
    return creator


def _switch_off(collection: Collection, ref: str) -> None:
    """Stop a list being a season of the collection. One that made every list a season keeps the others on."""
    if collection.link_seasons == LinkSeasons.ALL.value:
        for link in collection.lists:
            link.enabled = True
        collection.link_seasons = LinkSeasons.SELECTED.value
    for link in collection.lists:
        if link.ref == ref:
            link.enabled = False


def leave_creator(s: Session, collection: Collection) -> None:
    """Make a creator's collection a plain one again. It keeps its episodes, files and settings.

    ``s`` is a write transaction's session."""
    creator = collection.creator
    if creator is None:
        raise ServiceError(f"{collection.title} is not in a {collection_site(collection).creator_label}")
    for account in creator.accounts:
        if account.main_collection_id == collection.id:
            account.main_collection = None
    collection.creator = None
    s.flush()


def delete_creator(s: Session, creator: Creator) -> None:
    """Take a creator out of the Library. Its collections stay, as plain collections with their episodes, files and
    settings; VODLoft stops looking for the creator's new sections.

    ``s`` is a write transaction's session."""
    for collection in list(creator.collections):
        leave_creator(s, collection)
    for movie in list(creator.movies):
        movie.creator = None
    s.delete(creator)
    s.flush()


ARTIST_LABEL = "artist"
"""What VODLoft calls a creator that has a Music collection."""


CREATOR_LABEL = "creator"
"""What VODLoft calls a creator whose accounts and collections are on more than one Site."""


def _site(source_key: str, site_key: str) -> Site:
    """The Site as the Source that looks it up knows it, or as the Source made for it does."""
    try:
        site = get_source(source_key).site_of(site_key)
    except UnknownSourceError:
        site = None
    return site or site_of(site_key)


def _sites(creator: Creator) -> dict[str, Site]:
    """The Sites of the creator's accounts and collections, by key."""
    sites = {account.site_key: _site(account.source_key, account.site_key) for account in creator.accounts}
    for collection in creator.collections:
        if collection.site_key and collection.site_key not in sites:
            sites[collection.site_key] = _site(collection.source_key, collection.site_key)
    return sites


def creator_label(creator: Creator) -> str:
    """What the creator is called: an artist when they have a Music collection; otherwise what their Site calls
    them, when all their accounts and collections are on one Site, such as host on The Daily Wire; and otherwise a
    creator."""
    if any(collection.type == CollectionType.MUSIC.value for collection in creator.collections):
        return ARTIST_LABEL
    sites = list(_sites(creator).values())
    return sites[0].creator_label if len(sites) == 1 else CREATOR_LABEL


def creator_sections(creator: Creator) -> CreatorSectionNames:
    """What the creator adds, which VODLoft looks for: what their Site calls it, such as playlists on YouTube, when
    all their accounts and collections are on one Site, and otherwise playlists and shows."""
    sites = list(_sites(creator).values())
    return sites[0].creator_sections if len(sites) == 1 else CreatorSectionNames()


def creator_kind(creator: Creator) -> str:
    """What the creator is, with their Site when they are on one only: "YouTube creator", "The Daily Wire host" or
    "Bandcamp artist", and otherwise "creator" or "artist"."""
    sites = list(_sites(creator).values())
    label = creator_label(creator)
    return f"{sites[0].name} {label}" if len(sites) == 1 else label


def add_to_creator(s: Session, collection: Collection, creator: Creator) -> None:
    """Make a collection one of a creator's although its link is somewhere else, such as an artist's music videos
    on a channel or playlist of their label. It keeps its own link, and the creator's look for new sections leaves
    it alone. Nothing is indexed again and no file moves.

    ``s`` is a write transaction's session."""
    if collection.creator_id is not None:
        raise ServiceError(f"{collection.title} is already in {collection.creator.title}")
    if collection.sharing_url is not None and any(section.url == collection.sharing_url for section in creator.sections):
        raise ServiceError(
            f"{collection.title} is a part of {creator.title}'s own page: add it to the {creator_label(creator)} "
            "behind its link instead", field="creator_slug",
        )
    belong_to(collection, creator)
    s.flush()


def combine_creators(s: Session, creator: Creator, other: Creator) -> None:
    """Make ``other`` a part of ``creator``: the same person or group, such as a Daily Wire host and their YouTube
    channel added apart. Their accounts and collections move over, and ``other`` leaves the Library. Each collection
    keeps its genre and rating, episodes and files; nothing is indexed again.

    ``s`` is a write transaction's session."""
    if other.id == creator.id:
        raise ServiceError(f"{creator.title} can't be combined with themselves", field="other_slug")
    for account in list(other.accounts):
        other.accounts.remove(account)
        creator.accounts.append(account)
    for collection in list(other.collections):
        belong_to(collection, creator)
    for movie in list(other.movies):
        movie.creator = creator
    for field in ("description", "avatar_path", "banner_path", "genre", "content_rating"):
        if getattr(creator, field) is None and getattr(other, field) is not None:
            setattr(creator, field, getattr(other, field))
    creator.links = list(dict.fromkeys([*creator.links, *other.links]))
    s.flush()
    s.delete(other)
    s.flush()
    for account in creator.accounts:
        if account.main_collection is not None:
            account.main_collection.new_link_seasons = new_link_seasons(creator).value


def split_account(s: Session, account: CreatorAccount, details: CreatorDetails | None) -> Creator:
    """Make one of a creator's accounts a creator of their own again, with the collections it keeps: its own
    collection and those of its sections. Collections that joined the creator by another link stay. Returns the new
    creator, named after ``details`` when the account could be looked up, and after the creator otherwise.

    ``details`` was looked up before the write transaction; ``s`` is a write transaction's session."""
    creator = account.creator
    if len(creator.accounts) < 2:
        raise ServiceError(f"{creator.title} has only this account", field="account_id")
    kept = set(sections_in_library(s, account.source_key, account.site_ref, account.sections, account.main_collection).values())
    if account.main_collection is not None:
        kept.add(account.main_collection.slug)
    own = Creator(
        uuid=generate_uuid(),
        slug=_unique_slug(s, Creator, slugify((details.handle or details.title) if details else account.handle or creator.title) or account.site_ref),
        title=details.title if details else creator.title,
        description=details.description if details else creator.description,
        avatar_path=details.avatar_url if details else creator.avatar_path,
        banner_path=details.banner_url if details else creator.banner_path,
        links=list(details.links) if details else [], facts=list(details.facts) if details else [],
        added_by_id=creator.added_by_id, new_sections=creator.new_sections, genre=creator.genre,
        content_rating=creator.content_rating,
    )
    s.add(own)
    creator.accounts.remove(account)
    own.accounts.append(account)
    for collection in list(creator.collections):
        if collection.slug in kept:
            belong_to(collection, own)
    # The account's movies go with it.
    for movie in movies_in_library(s, account.source_key, account.sections).values():
        if movie.creator_id == creator.id:
            movie.creator = own
    s.flush()
    return own
