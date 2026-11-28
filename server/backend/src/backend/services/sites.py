"""The Sites VODLoft knows, and which Site a collection or video is on.

A Site is a website as the user knows it, such as YouTube, whichever Source
fetches it. VODLoft keeps a row per Site it has seen, with the domains it saw and
the Source to ask first for the Site's links. A collection is added once per Site:
the Site's own id for it is unique per Site.
"""
from __future__ import annotations

from backend.utils.helpers import name_in_text
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, CreatorAccount, Episode, LocalMediaProfileBase, Movie, Site, Video
from backend.security.access import Access
from backend.types.download_profile_types import EpIdType
from backend.types.collection_contracts import DEFAULT_WORDS, CollectionWords, collection_contract
from backend.types.link_season_types import CollectionKind, OutsideVideos
from backend.types.resource_names import CUSTOM_COLLECTION_NAMES
from backend.services.errors import ServiceError
from backend.services.local_media_profile_sites import add_upcoming_site
from sources import EpisodeTag, Names, Site as SourceSite, collection_on_site, get_source, has_site_contract, site_for, site_of, source_site, sources_for


class CollectionAlreadyAddedError(ValueError):
    """The collection is already in VODLoft, possibly through another Source."""

    def __init__(self, existing: Collection, site: Site):
        super().__init__(f"{name_in_text(existing.title)} is already in VODLoft, as a collection on {site.name}")
        self.existing = existing


def site_record(s: Session, site: SourceSite) -> Site:
    """The row of a Site, made when VODLoft sees the Site for the first time, with the domain seen added."""
    record = s.get(Site, site.key)
    if record is None:
        last = s.scalar(select(func.max(Site.position))) or 0
        record = Site(key=site.key, name=site.name, domains=list(site.domains), position=last + 1)
        s.add(record)
        s.flush()
        add_upcoming_site(s, site.key)
    elif any(domain not in record.domains for domain in site.domains):
        record.domains = [*record.domains, *(domain for domain in site.domains if domain not in record.domains)]
    return record


def collection_on_site_taken(s: Session, site_key: str, site_ref: str, *, other_than: Optional[int] = None) -> Optional[Collection]:
    query = select(Collection).where(Collection.site_key == site_key, Collection.site_ref == site_ref)
    if other_than is not None:
        query = query.where(Collection.id != other_than)
    return s.scalars(query.limit(1)).first()


def place_collection(s: Session, collection: Collection) -> None:
    """Give a new collection its Site and the Site's id for it.

    Raises CollectionAlreadyAddedError when the Site's collection is already in VODLoft,
    whichever Source it came through. The database refuses it too.
    """
    if collection.sharing_url is None:
        # A collection of the links the user picks is on no Site of its own, and can't be added twice.
        collection.site_key, collection.site_ref = None, None
        return
    site, ref = collection_on_site(collection.sharing_url, collection.source_key, collection.slug)
    record = site_record(s, site)
    existing = collection_on_site_taken(s, record.key, ref, other_than=collection.id)
    if existing is not None:
        raise CollectionAlreadyAddedError(existing, record)
    collection.site_key, collection.site_ref = record.key, ref


def collection_kind(url: str | None, source_key: str) -> CollectionKind:
    """What a collection's link is: a channel, a creator's page of all their uploads or one of its feeds, or one
    list. Every collection on a Site without creators is a list: it holds what its link lists, and takes no lists of a
    channel. A collection without a link is a custom collection."""
    if url is None:
        return CollectionKind.CUSTOM
    source = get_source(source_key)
    if not _site_of(url, source_key).creators or source.is_list(url):
        return CollectionKind.LIST
    return CollectionKind.CHANNEL


NO_SITE = SourceSite("", "Several sites")
"""What a collection without a link of its own is on before it has any links."""


def collection_site(collection: Collection) -> SourceSite:
    """The Site a collection is on, with what the collection's own Source offers there. A collection without a link of
    its own, which holds what its link seasons have, is on the Site of the first link it got; what each of its
    episodes does on its own Site, such as a download, follows the episode's Site (``episode_site``)."""
    if collection.sharing_url is not None:
        return _site_of(collection.sharing_url, collection.source_key)
    first = next(iter(sorted(collection.lists, key=lambda link: link.id or 0)), None)
    return _site_of(first.url, first.source_key or collection.source_key) if first is not None else NO_SITE


def collection_creator_names(collection: Collection) -> Names:
    """What the collection's Site calls the creator behind it, such as host on The Daily Wire, or artist when the
    collection is a Music collection."""
    return collection_contract(collection.type).creator_names_on(collection_site(collection))


def collection_words(collection: Collection, *, audio: bool | None = None) -> CollectionWords:
    """What a collection calls its seasons and episodes, by its type's contract: the tracks of a Music collection on a
    Site with sound only, such as Bandcamp, and its music videos elsewhere. Pass ``audio`` where the files are meant,
    which a profile for Music that downloads audio only keeps as sound."""
    site = collection_site(collection)
    words = collection_contract(collection.type).words_for(site.audio_only if audio is None else audio)
    seasons = site_season_names(site, collection.type, collection.kind)
    return replace(words, season=seasons) if seasons is not None else words


def site_season_names(site: SourceSite, collection_type: str, kind: str | None) -> Names | None:
    """What the Site calls the seasons of a collection of its kind, such as playlists in a YouTube channel collection
    or lists in a custom collection, or None where the collection type's own word stands: in a type that names its
    seasons itself, such as an artist's albums. A custom collection is on the Site of its first list, or on none."""
    if kind is None or collection_contract(collection_type).words.season != DEFAULT_WORDS.season:
        return None
    if kind == CollectionKind.CUSTOM.value:
        return site.custom_season_names
    return site.channel_season_names if kind == CollectionKind.CHANNEL.value else site.list_season_names


def collection_names(collection: Collection) -> Names:
    """What the collection's Site calls a collection of its kind, such as a channel or a playlist on YouTube."""
    if collection.kind == CollectionKind.CUSTOM.value:
        return CUSTOM_COLLECTION_NAMES
    site = collection_site(collection)
    if collection.kind == CollectionKind.CHANNEL.value:
        return site.channel_collection_names
    return site.list_collection_names_of(collection.list_type)


def collection_episode_tags(collection: Collection) -> tuple[EpisodeTag, ...]:
    """The tags of a collection's episodes, the main one named as the collection names its episodes
    (``collection_words``), such as tracks in a Music collection on Bandcamp."""
    tags = get_source(collection.source_key).episode_tags_for(collection.sharing_url)
    return episode_tags_named(tags, collection_words(collection))


def main_tag_of_type(collection: Collection, episode_type: str) -> str:
    """The episode type as the collection's Site tells types apart. An auxiliary episode on a Site that has no such
    type, as a collection numbered by date gives a second video of one date or a video's episode in a second
    playlist, is of the Site's main type there."""
    if episode_type != EpIdType.AUX:
        return episode_type
    tags = collection_episode_tags(collection)
    if any(tag.key == episode_type for tag in tags):
        return episode_type
    return next((tag.key for tag in tags if tag.main), episode_type)


def with_main_type(collection: Collection, episode_types: Iterable[str]) -> set[str]:
    """Episode types picked from a collection's Site's types, with the auxiliary episodes the Site counts as its main
    type (``main_tag_of_type``) when that type is picked."""
    picked = set(episode_types)
    if main_tag_of_type(collection, EpIdType.AUX) in picked:
        picked.add(EpIdType.AUX.value)
    return picked


def episode_tags_named(tags: Iterable[EpisodeTag], words: CollectionWords) -> tuple[EpisodeTag, ...]:
    """A Site's episode tags with the main one named by a collection's ``words``. Its key stays the Site's, so
    profiles select it the same everywhere."""
    episode = words.episode
    return tuple(
        replace(tag, label=episode.singular.capitalize(), help=f"{episode.a.capitalize()} of the collection", names=episode)
        if tag.main else tag
        for tag in tags
    )


def episode_site(episode: Episode) -> SourceSite:
    """The Site an episode's video is on. Only a collection that holds what its link seasons have can hold links of
    several Sites, so there each episode is on its own Site; everywhere else it is on the collection's."""
    collection = episode.collection
    if collection.outside_videos == OutsideVideos.ONLY and episode.sharing_url:
        return _site_of(episode.sharing_url, episode.source_key)
    return collection_site(collection)


def episode_site_key(episode: Episode) -> Optional[str]:
    """The key of the Site an episode is on, as ``episode_site`` tells it, from the stored key where it can."""
    if episode.collection.outside_videos == OutsideVideos.ONLY:
        return episode_site(episode).key or None
    return episode.collection.site_key


def video_site(video: Video) -> SourceSite:
    return _site_of(video.sharing_url, video.source_key)


def collection_site_key(collection: Collection) -> Optional[str]:
    """The key of the Site a collection is on, told from its link while VODLoft has not stored it yet; None for a
    collection without a link of its own or any link seasons yet."""
    return collection.site_key or collection_site(collection).key or None


def video_site_key(video: Video) -> str:
    return video.site_key or video_site(video).key


def movie_site_key(movie: Movie) -> Optional[str]:
    """The key of the Site a movie is on; None for a movie without a link."""
    return _site_of(movie.sharing_url, movie.source_key).key if movie.sharing_url else None


@lru_cache(maxsize=1024)
def _site_of(url: str, source_key: str) -> SourceSite:
    # Telling a yt-dlp link's Site tries every extractor, and a feed asks once per episode.
    return source_site(url, source_key)


def place_video(s: Session, video: Video) -> None:
    """Give a video the Site its link is on."""
    video.site_key = site_record(s, site_for(video.sharing_url, video.source_key)).key


def preferred_sources(s: Session) -> dict[str, str]:
    """The Source the user asks first, per Site key."""
    return dict(s.execute(select(Site.key, Site.preferred_source_key).where(Site.preferred_source_key.is_not(None))).all())


class SiteLinkError(ValueError):
    pass


def site_of_link(s: Session, url: str) -> SourceSite:
    """The Site of a link, as the Source VODLoft asks first for it tells, without a network request."""
    candidates = sources_for(url, preferred_sources(s))
    if not candidates or not url.lower().startswith(("http://", "https://")) or "." not in (urlsplit(url).hostname or ""):
        raise SiteLinkError("Type the site's address, such as twitch.tv, or paste a link to a page on it")
    return site_for(url, candidates[0].id)


def media_links(s: Session, access: Access, urls: Iterable[str]) -> list[str]:
    """The links, of ``urls``, that are on a Site VODLoft knows for media: one a Source has a contract of its own for,
    such as YouTube, or one in VODLoft's Sites, which the user added or VODLoft has media from. Only links the user may
    look up count. Telling a link's Site needs no network request."""
    preferred = preferred_sources(s)
    added = set(s.scalars(select(Site.key)))
    found = []
    for url in dict.fromkeys(urls):
        if not url.lower().startswith(("http://", "https://")):
            continue
        candidates = [source for source in sources_for(url, preferred) if access.allows_link(source.id, url)]
        if not candidates:
            continue
        key = site_for(url, candidates[0].id).key
        if key in added or has_site_contract(key):
            found.append(url)
    return found


SUGGESTED_SITES = (
    "https://www.youtube.com", "https://www.twitch.tv", "https://www.dailywire.com", "https://soundcloud.com",
    "https://www.tiktok.com", "https://vimeo.com",
)
"""The popular Sites VODLoft suggests where the user picks the Sites they use, such as in onboarding, by their
address, in the order they are shown. What VODLoft says of each comes from its contract."""

FIRST_PICKED_SITE = "https://www.youtube.com"
"""The suggested Site that starts picked, by its address: the one most people use."""


@dataclass(frozen=True)
class SiteChoice:
    """A Site the user can pick: a suggested one, or one already added."""

    key: str
    name: str
    pitch: str | None
    added: bool
    suggested: bool
    picked: bool
    """The Site starts picked, whatever VODLoft knows already."""


def site_choices(s: Session) -> list[SiteChoice]:
    """The suggested Sites, then every other Site VODLoft knows, such as one the user added by its address, each
    with whether it is added."""
    known = {record.key: record.name for record in s.scalars(select(Site).order_by(Site.position, Site.name))}
    first = site_of_link(s, FIRST_PICKED_SITE).key
    suggested = [site_of_link(s, address) for address in SUGGESTED_SITES]
    choices = [
        SiteChoice(site.key, site.name, site.pitch, site.key in known, True, site.key == first) for site in suggested
    ]
    taken = {site.key for site in suggested}
    choices += [
        SiteChoice(key, name, site_of(key).pitch, True, False, False) for key, name in known.items() if key not in taken
    ]
    return choices


def add_suggested_sites(s: Session, keys: Iterable[str]) -> None:
    """Add the suggested Sites with the keys that VODLoft does not know yet."""
    known = set(s.scalars(select(Site.key)))
    for address in SUGGESTED_SITES:
        site = site_of_link(s, address)
        if site.key in keys and site.key not in known:
            add_site(s, site)


def add_site(s: Session, site: SourceSite) -> Site:
    """Remember a Site before VODLoft has anything from it, so it can get its own settings and sign-in."""
    record = site_record(s, site)
    s.flush()
    return record


def sites_in_use(s: Session) -> set[str]:
    """The keys of the Sites VODLoft has something from: a collection, a video, a creator, a movie, or an episode
    of a collection that holds the links of several Sites."""
    keys = set(s.scalars(union(
        select(Collection.site_key).where(Collection.site_key.is_not(None)),
        select(Video.site_key).where(Video.site_key.is_not(None)),
        select(CreatorAccount.site_key),
    )))
    keys.update(
        _site_of(url, source_key).key
        for url, source_key in s.execute(select(Movie.sharing_url, Movie.source_key).where(Movie.sharing_url.is_not(None)).distinct())
    )
    keys.update(
        _site_of(url, source_key).key
        for url, source_key in s.execute(
            select(Episode.sharing_url, Episode.source_key).join(Episode.collection)
            .where(Collection.outside_videos == OutsideVideos.ONLY).distinct()
        )
    )
    return keys


def sites_kept(s: Session) -> set[str]:
    """The Sites the user can't remove: the ones with something in VODLoft, and the last Site left, since VODLoft
    always keeps at least one."""
    kept = sites_in_use(s)
    known = set(s.scalars(select(Site.key)))
    if len(known) <= 1:
        kept |= known
    return kept


def site_removable(site_key: str, kept: set[str]) -> bool:
    """Whether the user can remove a Site, of the ones ``sites_kept`` keeps: any Site that has nothing in VODLoft,
    also one VODLoft starts with, such as The Daily Wire, while another Site stays. Adding it again brings back
    everything its Sources offer there."""
    return site_key not in kept


def remove_site(s: Session, site_key: str) -> None:
    """Forget a Site that has nothing in VODLoft, and take it out of the profiles that store media from it. Its
    settings under ``siteSettings`` stay, so adding it again brings them back. The last Site stays."""
    if site_key in sites_in_use(s):
        raise ServiceError("This site has collections, videos or creators in VODLoft, so it can't be removed", status_code=409)
    if not site_removable(site_key, sites_kept(s)):
        raise ServiceError("VODLoft needs at least one site, so the last one can't be removed. Add another site first", status_code=409)
    record = s.get(Site, site_key)
    if record is not None:
        s.delete(record)
    for profile in s.scalars(select(LocalMediaProfileBase)):
        if site_key in profile.site_keys:
            profile.site_keys = [key for key in profile.site_keys if key != site_key]
