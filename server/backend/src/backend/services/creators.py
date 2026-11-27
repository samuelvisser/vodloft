"""Creators: who made the work, with an account on one or more Sites.

A creator groups its collections, possibly of several Sites, such as a YouTube channel, one of their playlists and a
SoundCloud account, and its movies, under one card in the Library. It plays no part in what a collection holds: joining or leaving
a creator never changes a collection's episodes. Its page also shows what else the creator has at their Sites that is
not in the Library yet, such as a Daily Wire host's other shows and movies.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.db.models import Creator, CreatorAccount, Collection, Movie
from backend.services.errors import ServiceError
from backend.services.sites import collection_site, site_record
from backend.types.collection_contracts import DEFAULT_WORDS, MUSIC, CollectionWords, collection_contract
from backend.types.collection_types import CollectionType
from backend.utils.helpers import generate_uuid, slugify, name_in_text
from sources import CreatorDetails, Feature, Names, SectionKind, SectionRef, Site, UnknownSourceError, get_source, site_of

logger = logging.getLogger(__name__)


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


def takes_creators(source_key: str, site: Site) -> bool:
    """Whether a collection with a link on ``site`` can be in a creator: the Site has creators, and the collection's
    Source knows them."""
    return site.creators and get_source(source_key).has(Feature.CREATORS)


def site_takes_creators(source_key: str, site_key: str) -> bool:
    """``takes_creators`` for the Site with the key, as the collection's Source knows it."""
    return takes_creators(source_key, _site(source_key, site_key))


def can_join(collection: Collection) -> bool:
    """Whether the collection can be in a creator: one with a link on a Site with creators, a channel or a list, or
    one without a link of its own, which joins a creator in the Library by hand."""
    return collection.sharing_url is None or takes_creators(collection.source_key, collection_site(collection))


def check_joins(collection: Collection) -> None:
    """Refuses a collection that can't be in a creator."""
    if not can_join(collection):
        site = collection_site(collection)
        raise ServiceError(f"{site.name or 'Its Site'} has no {site.creator_names.plural} VODLoft can add", field="creator_slug")


def check_has_link(collection: Collection) -> None:
    """Refuses to look up the creator behind a collection without a link of its own."""
    if collection.sharing_url is None:
        raise ServiceError(
            f"{name_in_text(collection.title)} has no link of its own to find a creator behind: pick one in your library",
            field="creator_slug",
        )


def account_in_library(s: Session, site_key: str, ref: str) -> CreatorAccount | None:
    return s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == site_key, CreatorAccount.site_ref == ref))


def takes_movies(source_key: str) -> bool:
    """Whether the creator's single items are movies VODLoft can add, such as a Daily Wire host's movies."""
    return get_source(source_key).has(Feature.MOVIES)


def has_offerings(account: CreatorAccount) -> bool:
    """Whether the account's Site has more of the creator's work than their channel to offer: shows, or movies VODLoft
    can add."""
    site = account_site(account)
    return bool(site.types_of(SectionKind.SHOW)) or (bool(site.types_of(SectionKind.ITEM)) and takes_movies(account.source_key))


def offered(details: CreatorDetails, source_key: str) -> list[SectionRef]:
    """What the creator has at their Site that is a collection or a movie of its own beside their channel: a Daily
    Wire host's shows and movies. A channel's feeds and lists are its collection's to hold."""
    movies = takes_movies(source_key)
    return [
        section for section in details.sections
        if section.kind is SectionKind.SHOW or (section.kind is SectionKind.ITEM and movies)
    ]


def collections_of(s: Session, source_key: str, site_key: str, sections: Sequence[SectionRef]) -> dict[str, Collection]:
    """The collections in the Library of the creator's shows, by the show's ref: the collection of its link, or the
    one the Site knows by its id."""
    by_url = {section.url: section.ref for section in sections}
    by_ref = {section.ref for section in sections}
    found: dict[str, Collection] = {}
    for collection in s.scalars(select(Collection).where(or_(
        Collection.sharing_url.in_(by_url), (Collection.site_key == site_key) & Collection.site_ref.in_(by_ref),
    ))):
        ref = by_url.get(collection.sharing_url or "") or (collection.site_ref if collection.source_key == source_key else None)
        if ref is not None:
            found.setdefault(ref, collection)
    return found


def movies_in_library(s: Session, source_key: str, refs: Iterable[str], urls: Mapping[str, str] | None = None) -> dict[str, Movie]:
    """The movies in the Library among the creator's single items ``refs``, by ref: the movie known by the item's id,
    or made from its link, by ``urls``, the ref of each item's link. Empty where the creator's single items aren't
    movies."""
    refs, urls = set(refs), dict(urls or {})
    if not refs or not takes_movies(source_key):
        return {}
    found: dict[str, Movie] = {}
    for movie in s.scalars(select(Movie).where(
        Movie.source_key == source_key, or_(Movie.slug.in_(refs), Movie.sharing_url.in_(urls)),
    )):
        ref = movie.slug if movie.slug in refs else urls.get(movie.sharing_url or "")
        if ref is not None:
            found.setdefault(ref, movie)
    return found


def movies_offered(s: Session, source_key: str, sections: Sequence[SectionRef]) -> dict[str, Movie]:
    """The movies in the Library of the creator's single items among ``sections``, by the section's ref."""
    items = [section for section in sections if section.kind is SectionKind.ITEM]
    return movies_in_library(s, source_key, [item.ref for item in items], {item.url: item.ref for item in items})


def join_movies(s: Session, creator: Creator, source_key: str, refs: Iterable[str]) -> list[Movie]:
    """Make the movies of ``refs`` that are in the Library the creator's. Returns the movies that joined.

    ``s`` is a write transaction's session."""
    joined = []
    for movie in movies_in_library(s, source_key, refs).values():
        if movie.creator_id != creator.id:
            movie.creator = creator
            joined.append(movie)
    s.flush()
    return joined


def _unique_slug(s: Session, model, wanted: str) -> str:
    """``wanted`` itself while it is free; else a slug made from it."""
    if wanted and s.scalar(select(model.id).where(model.slug == wanted)) is None:
        return wanted
    base = slugify(wanted) or "creator"
    slug, suffix = base, 2
    while s.scalar(select(model.id).where(model.slug == slug)) is not None:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    return slug


def _site_key_of(source_key: str) -> str:
    # A creator without a page of its own, such as a Daily Wire host, is on its Source's one Site.
    sites = get_source(source_key).sites
    if len(sites) != 1:
        raise ServiceError("This creator has no link, and its Site could not be told")
    return sites[0].key


def account_of(s: Session, source_key: str, details: CreatorDetails) -> CreatorAccount | None:
    """The creator's account in the Library, when the creator is in it."""
    site = creator_site(source_key, details.url or _site_key_of(source_key))
    return account_in_library(s, site_record(s, site).key, details.ref)


def new_creator(s: Session, source_key: str, details: CreatorDetails, *, added_by_id: int | None) -> Creator:
    """Put a creator in the Library with their account at the Site of ``details``, which was looked up before the
    write transaction. They have no collections yet.

    ``s`` is a write transaction's session."""
    site = creator_site(source_key, details.url or _site_key_of(source_key))
    record = site_record(s, site)
    existing = account_in_library(s, record.key, details.ref)
    if existing is not None:
        raise ServiceError(f"{name_in_text(details.title)} is already in your library, as {name_in_text(existing.creator.title)}", field="creator_slug")
    creator = Creator(
        uuid=generate_uuid(), slug=_unique_slug(s, Creator, slugify(details.handle or details.title) or details.ref),
        title=details.title, description=details.description, avatar_path=details.avatar_url,
        banner_path=details.banner_url, links=list(details.links), facts=list(details.facts), added_by_id=added_by_id,
    )
    creator.accounts.append(CreatorAccount(
        source_key=source_key, site_key=record.key, site_ref=details.ref, url=details.url, handle=details.handle,
        avatar_path=details.avatar_url, banner_path=details.banner_url,
    ))
    s.add(creator)
    s.flush()
    return creator


def join_creator(s: Session, collection: Collection, creator: Creator) -> None:
    """Group a collection under a creator in the Library. Nothing it holds changes.

    ``s`` is a write transaction's session."""
    if collection.creator_id is not None:
        raise ServiceError(f"{name_in_text(collection.title)} is already in {name_in_text(collection.creator.title)}", field="creator_slug")
    check_joins(collection)
    belong_to(collection, creator)
    s.flush()


def join_creator_of(
    s: Session, collection: Collection, source_key: str, details: CreatorDetails, *, added_by_id: int | None,
) -> Creator:
    """Group a collection under the creator behind its link, looked up as ``details``: the one in the Library, or a
    new one made from ``details``. A playlist's is the channel that made it.

    ``s`` is a write transaction's session."""
    check_has_link(collection)
    check_joins(collection)
    account = account_of(s, source_key, details)
    creator = account.creator if account is not None else new_creator(s, source_key, details, added_by_id=added_by_id)
    join_creator(s, collection, creator)
    return creator


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


def update_creator_settings(
    creator: Creator, *, genre: str | None, content_rating: str | None, ytdlp_options: str | None = None,
) -> None:
    """Change the genre and rating the creator's collections get, and the yt-dlp options they use. A collection that
    had the creator's old genre or rating gets the new one; one with its own keeps it. ``ytdlp_options`` None leaves
    them as they are."""
    for field, new in (("genre", genre or None), ("content_rating", content_rating or None)):
        old = getattr(creator, field)
        if old == new:
            continue
        for collection in creator.collections:
            if getattr(collection, field) in (old, None):
                setattr(collection, field, new)
        setattr(creator, field, new)
    if ytdlp_options is not None and ytdlp_options != creator.ytdlp_options:
        if ytdlp_options and not takes_ytdlp_options(creator):
            raise ServiceError(f"{creator.title} has no collection that takes yt-dlp options", field="ytdlp_options")
        creator.ytdlp_options = ytdlp_options


def leave_creator(s: Session, collection: Collection) -> None:
    """Take a collection out of its creator. Nothing it holds changes.

    ``s`` is a write transaction's session."""
    if collection.creator is None:
        raise ServiceError(f"{name_in_text(collection.title)} is not in {collection_site(collection).creator_names.a}")
    collection.creator = None
    s.flush()


def delete_creator(s: Session, creator: Creator) -> None:
    """Take a creator out of the Library. Its collections and movies stay, with their episodes, files and settings.

    ``s`` is a write transaction's session."""
    for collection in list(creator.collections):
        collection.creator = None
    for movie in list(creator.movies):
        movie.creator = None
    s.delete(creator)
    s.flush()


_ANY_SITE = Site("", "")
"""VODLoft's own defaults for any Site, for a creator whose accounts and collections are on more than one Site."""


def _site(source_key: str, site_key: str) -> Site:
    """The Site as the Source that looks it up knows it, or as the Source made for it does."""
    try:
        site = get_source(source_key).site_of(site_key)
    except UnknownSourceError:
        site = None
    return site or site_of(site_key)


def account_site(account: CreatorAccount) -> Site:
    """The Site of one of a creator's accounts."""
    return _site(account.source_key, account.site_key)


def _sites(creator: Creator) -> dict[str, Site]:
    """The Sites of the creator's accounts and collections, by key."""
    sites = {account.site_key: _site(account.source_key, account.site_key) for account in creator.accounts}
    for collection in creator.collections:
        if collection.site_key and collection.site_key not in sites:
            sites[collection.site_key] = _site(collection.source_key, collection.site_key)
    return sites


def takes_ytdlp_options(creator: Creator) -> bool:
    """Whether the creator can have yt-dlp options of their own: one of their accounts or collections comes from a
    Source that takes yt-dlp options."""
    keys = {account.source_key for account in creator.accounts} | {collection.source_key for collection in creator.collections}
    return any(get_source(key).has(Feature.YTDLP_OPTIONS) for key in keys if _known_source(key))


def _known_source(key: str) -> bool:
    try:
        get_source(key)
    except UnknownSourceError:
        return False
    return True


def is_music_creator(creator: Creator) -> bool:
    """Whether the creator is a music artist: they have a Music collection."""
    return any(collection.type == CollectionType.MUSIC.value for collection in creator.collections)


def creator_names(creator: Creator) -> Names:
    """What the creator is called, as their Site calls them when all their accounts and collections are on one Site,
    such as host on The Daily Wire, or artist for one with a Music collection; and otherwise as any Site does."""
    sites = list(_sites(creator).values())
    site = sites[0] if len(sites) == 1 else _ANY_SITE
    return MUSIC.creator_names_on(site) if is_music_creator(creator) else site.creator_names


def creator_words(creator: Creator) -> CollectionWords:
    """What the creator's page calls their seasons and episodes: as their collections' type does when all of them are
    of one type, such as albums and tracks for an artist on Bandcamp, and otherwise VODLoft's own words."""
    types = {collection.type for collection in creator.collections}
    if len(types) != 1:
        return DEFAULT_WORDS
    audio = bool(creator.accounts) and all(_site(account.source_key, account.site_key).audio_only for account in creator.accounts)
    return collection_contract(types.pop()).words_for(audio)


def creator_kind(creator: Creator) -> str:
    """What the creator is, with their Site when they are on one only: "YouTube creator", "The Daily Wire host" or
    "Bandcamp artist", and otherwise "creator" or "artist"."""
    sites = list(_sites(creator).values())
    label = creator_names(creator).singular
    return f"{sites[0].name} {label}" if len(sites) == 1 else label


def combine_creators(s: Session, creator: Creator, other: Creator) -> None:
    """Make ``other`` a part of ``creator``: the same person or group, such as a Daily Wire host and their YouTube
    channel added apart. Their accounts, collections and movies move over, and ``other`` leaves the Library.

    ``s`` is a write transaction's session."""
    if other.id == creator.id:
        raise ServiceError(f"{name_in_text(creator.title)} can't be combined with themselves", field="other_slug")
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
    if not creator.ytdlp_options:
        creator.ytdlp_options = other.ytdlp_options
    creator.links = list(dict.fromkeys([*creator.links, *other.links]))
    s.flush()
    s.delete(other)
    s.flush()


def split_account(s: Session, account: CreatorAccount, details: CreatorDetails | None) -> Creator:
    """Make one of a creator's accounts a creator of their own again, with the collections and movies on its Site.
    Returns the new creator, named after ``details`` when the account could be looked up, and after the creator
    otherwise.

    ``details`` was looked up before the write transaction; ``s`` is a write transaction's session."""
    creator = account.creator
    if len(creator.accounts) < 2:
        raise ServiceError(f"{name_in_text(creator.title)} has only this account", field="account_id")
    own = Creator(
        uuid=generate_uuid(),
        slug=_unique_slug(s, Creator, slugify((details.handle or details.title) if details else account.handle or creator.title) or account.site_ref),
        title=details.title if details else creator.title,
        description=details.description if details else creator.description,
        avatar_path=details.avatar_url if details else account.avatar_path or creator.avatar_path,
        banner_path=details.banner_url if details else account.banner_path or creator.banner_path,
        links=list(details.links) if details else [], facts=list(details.facts) if details else [],
        added_by_id=creator.added_by_id, genre=creator.genre, content_rating=creator.content_rating,
        ytdlp_options=creator.ytdlp_options,
    )
    s.add(own)
    creator.accounts.remove(account)
    own.accounts.append(account)
    # What is on the account's Site goes with it, unless another of the creator's accounts is on that Site too.
    shared = any(other.site_key == account.site_key for other in creator.accounts)
    if not shared:
        for collection in list(creator.collections):
            if collection.site_key == account.site_key:
                belong_to(collection, own)
        for movie in list(creator.movies):
            if movie.source_key == account.source_key:
                movie.creator = own
    s.flush()
    return own
