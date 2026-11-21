"""The Sites VODLoft knows, and which Site a collection or video is on.

A Site is a website as the user knows it, such as YouTube, whichever Source
fetches it. VODLoft keeps a row per Site it has seen, with the domains it saw and
the Source to ask first for the Site's links. A collection is added once per Site:
the Site's own id for it is unique per Site.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from functools import lru_cache
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, CreatorAccount, Episode, LocalMediaProfileBase, Movie, Site, Video
from backend.types.collection_contracts import CollectionWords, collection_contract
from backend.types.link_season_types import OutsideVideos
from backend.services.errors import ServiceError
from backend.services.local_media_profile_sites import add_upcoming_site, builtin_sites
from sources import EpisodeTag, Names, Site as SourceSite, collection_on_site, get_source, site_for, source_site, sources_for


class CollectionAlreadyAddedError(ValueError):
    """The collection is already in VODLoft, possibly through another Source."""

    def __init__(self, existing: Collection, site: Site):
        super().__init__(f"{existing.title} is already in VODLoft, as a collection on {site.name}")
        self.existing = existing


def site_record(s: Session, site: SourceSite) -> Site:
    """The row of a Site, made when VODLoft sees the Site for the first time, with the domain seen added."""
    record = s.get(Site, site.key)
    if record is None:
        record = Site(key=site.key, name=site.name, domains=list(site.domains))
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


NO_SITE = SourceSite("", "Several sites")
"""What a collection without a link of its own is on before it has any links."""


def collection_site(collection: Collection) -> SourceSite:
    """The Site a collection is on, with what the collection's own Source offers there. A collection without a link of
    its own, which holds what its link seasons have, is on the Site of the first link it got; what each of its
    episodes does on its own Site, such as a download, follows the episode's Site (``episode_site``)."""
    url = collection.sharing_url or next(
        (link.url for link in sorted(collection.lists, key=lambda link: link.id or 0)), None,
    )
    return _site_of(url, collection.source_key) if url else NO_SITE


def collection_creator_names(collection: Collection) -> Names:
    """What the collection's Site calls the creator behind it, such as host on The Daily Wire, or artist when the
    collection is a Music collection."""
    return collection_contract(collection.type).creator_names_on(collection_site(collection))


def collection_words(collection: Collection, *, audio: bool | None = None) -> CollectionWords:
    """What a collection calls its seasons and episodes, by its type's contract: the tracks of a Music collection on a
    Site with sound only, such as Bandcamp, and its music videos elsewhere. Pass ``audio`` where the files are meant,
    which a profile for Music tracks keeps as sound."""
    return collection_contract(collection.type).words_for(collection_site(collection).audio_only if audio is None else audio)


def collection_episode_tags(collection: Collection) -> tuple[EpisodeTag, ...]:
    """The tags of a collection's episodes, the main one named as the collection names its episodes
    (``collection_words``), such as tracks in a Music collection on Bandcamp."""
    tags = get_source(collection.source_key).episode_tags_for(collection.sharing_url)
    return episode_tags_named(tags, collection_words(collection))


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


def site_removable(site_key: str, in_use: set[str]) -> bool:
    """Whether the user can remove a Site: one they added, or VODLoft saw, that has nothing in VODLoft. A Site a
    Source is made for, such as The Daily Wire, always stays."""
    return site_key not in in_use and site_key not in {site.key for site in builtin_sites()}


def remove_site(s: Session, site_key: str) -> None:
    """Forget a Site that has nothing in VODLoft, and take it out of the profiles that store media from it. Its
    settings under ``siteSettings`` stay, so adding it again brings them back."""
    if not site_removable(site_key, sites_in_use(s)):
        raise ServiceError("This site has collections, videos or creators in VODLoft, so it can't be removed", status_code=409)
    record = s.get(Site, site_key)
    if record is not None:
        s.delete(record)
    for profile in s.scalars(select(LocalMediaProfileBase)):
        if site_key in profile.site_keys:
            profile.site_keys = [key for key in profile.site_keys if key != site_key]
