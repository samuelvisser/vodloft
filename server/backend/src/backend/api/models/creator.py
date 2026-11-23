"""A creator in the Library: who made the work, with an account on one or more Sites, grouping their channel
collections and movies."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.episode import EpisodeAPIReadView
from backend.api.models.pagination import CursorPageRead
from backend.api.models.profile_bulk import BulkSelectionIn
from backend.api.models.collection_contract import CollectionWordsAPIRead
from backend.api.models.source import NamesAPIRead, SiteAPIRead


class CreatorCollectionAPIRead(ResponseBase):
    id: int
    slug: str
    title: str
    type: str
    source_key: str
    thumbnail_landscape_path: Optional[str] = None
    thumbnail_portrait_path: Optional[str] = None
    thumbnail_square_path: Optional[str] = None
    logo_image_path: Optional[str] = None
    author_headshot_path: Optional[str] = None
    episode_count: int = 0
    years: str = ""
    """The years of its oldest and newest episode, such as 2015-2026, as the Library shows them."""
    first_published_date: Optional[datetime] = None
    """When its oldest episode came out."""
    loose_season: Optional[str] = None
    """The one season the videos in none of its lists share, such as Singles; None when they get a season per year,
    or it has no lists as seasons."""
    site: Optional[SiteAPIRead] = None
    """The website the collection is on, which tells whether its music is tracks or music videos."""


class CreatorAccountAPIRead(ResponseBase):
    """A creator's account on one Site, such as their YouTube channel."""

    id: int
    source_key: str
    site: SiteAPIRead
    """The account's Site, with what it calls a creator."""
    site_ref: str
    url: Optional[str] = None
    handle: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("avatar_path", "avatar_url"))
    """The account's own picture on its Site."""
    offers: bool = False
    """The account's Site has more of the creator's work than their channel, such as a Daily Wire host's shows and
    movies, which the creator's page offers to add."""


class CreatorAPIRead(ResponseBase):
    """A creator in the Library."""

    id: int
    slug: str
    creator_names: NamesAPIRead
    """What VODLoft calls the creator: the word of their one Site, such as host, or artist for a music artist."""
    music: bool = False
    """A music artist: they have a Music collection."""
    kind: str
    """The label with their Site, when they are on one only, such as "The Daily Wire host"."""
    words: CollectionWordsAPIRead
    """What the creator's page calls their seasons and episodes, such as albums and tracks for an artist."""
    accounts: list[CreatorAccountAPIRead]
    title: str
    description: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("avatar_path", "avatar_url"))
    banner_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("banner_path", "banner_url"))
    links: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    created_at: datetime
    collection_count: int = 0
    episode_count: int = 0
    open_count: int = 0
    """How often its page and its collections' pages were opened, for the Library's Often used order."""
    last_opened_at: Optional[datetime] = None
    """When its page or one of its collections' pages was last opened, for the Library's Recently used order."""
    genre: Optional[str] = None
    content_rating: Optional[str] = None


class CreatorMovieAPIRead(ResponseBase):
    """One of the creator's movies in the Library."""

    slug: str
    title: str
    thumbnail_portrait_path: Optional[str] = None
    thumbnail_landscape_path: Optional[str] = None
    background_image_path: Optional[str] = None
    logo_image_path: Optional[str] = None
    release_date: Optional[date] = None
    published_at: Optional[datetime] = None
    drm_protected: bool = False


class CreatorEpisodeAPIRead(EpisodeAPIReadView):
    """One of the newest episodes on a creator's page, with the collection it is in."""

    collection_slug: str
    collection_title: str


class CreatorEpisodePageAPIRead(CursorPageRead[CreatorEpisodeAPIRead]):
    """One page of the episodes of all of a creator's collections, newest first."""


class CreatorPageAPIRead(CreatorAPIRead):
    """A creator's page: their collections and movies."""

    collections: list[CreatorCollectionAPIRead]
    movies: list[CreatorMovieAPIRead] = Field(default_factory=list)
    last_published_date: Optional[datetime] = None
    """When the newest episode of all of the creator's collections came out."""


class CreatorOfferingAPIRead(ResponseBase):
    """A show or movie of the creator at one of their Sites, with what the Library has of it."""

    ref: str
    url: str
    title: str
    kind: Literal["show", "item"]
    names: NamesAPIRead = Field(validation_alias=AliasPath("section_type", "names"))
    """What the Site calls it, such as show or movie."""
    item_count: Optional[int] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    access: Optional[str] = None
    year: Optional[str] = None
    collection_slug: Optional[str] = None
    """For a show: its collection in the Library, when it is in it."""
    collection_title: Optional[str] = None
    collection_joined: bool = False
    """That collection is one of this creator's already."""
    movie_slug: Optional[str] = None
    """For a movie: the movie in the Library, when it is in it."""
    movie_title: Optional[str] = None
    movie_joined: bool = False
    """That movie is one of this creator's already."""


class CreatorAccountOfferingsAPIRead(ResponseBase):
    """What one of the creator's accounts offers at its Site."""

    account_id: int
    site: SiteAPIRead
    offerings: list[CreatorOfferingAPIRead]


class CreatorOfferingsAPIRead(ResponseBase):
    accounts: list[CreatorAccountOfferingsAPIRead]


class CreatorMoviesAPIAdd(RequestBase):
    """Movies of one of the creator's accounts to add to the Library, or to the creator when they are in it."""

    refs: list[str] = Field(min_length=1, max_length=500)


class CreatorAPIUpdate(RequestBase):
    """Change a creator's name and what their collections get."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    """The creator's name, which their collections take as author; left out, it stays as it is. A name given here
    is kept when the Site's name changes."""
    genre: Optional[str] = Field(default=None, max_length=200)
    content_rating: Optional[str] = Field(default=None, max_length=50)


class CreatorCombineAPIIn(RequestBase):
    """Another creator in the Library who is the same person or group, whose accounts and collections move over."""

    other_slug: str = Field(min_length=1, max_length=255)


class CollectionCreatorMatchAPIRead(ResponseBase):
    """The creator behind a channel collection's link, before the collection joins them."""

    lookup_id: Optional[str] = None
    """Joining with this id uses what this lookup found, instead of asking the Site again."""

    site_name: str
    creator_names: NamesAPIRead
    ref: str
    url: Optional[str] = None
    title: str
    handle: Optional[str] = None
    avatar_url: Optional[str] = None
    creator_slug: Optional[str] = None
    """The creator's slug, when they are in the Library already."""
    creator_title: Optional[str] = None


class CollectionCreatorJoinAPIIn(RequestBase):
    lookup_id: Optional[str] = Field(default=None, max_length=64)
    """The match's id, to use what it found instead of asking the Site again."""
    creator_slug: Optional[str] = Field(default=None, max_length=255)
    """A creator in the Library to join instead of the one behind the collection's link, such as an artist whose
    music videos are on their label's channel."""


class CreatorBulkDeleteIn(BulkSelectionIn):
    """The creators the Library's bulk edit deletes."""

    delete_collections: bool = False
    """Delete their collections too, instead of keeping them as they are."""
