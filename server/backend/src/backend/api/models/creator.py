from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.episode import EpisodeAPIReadView
from backend.api.models.pagination import CursorPageRead
from backend.api.models.source import CreatorSectionNamesAPIRead, ListKindAPIRead, SiteAPIRead
from backend.types.creator_types import NewSectionAction, SectionTarget
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.dailywire_user_info import DwMembershipLevel
from sources import CreatorPreset


class CreatorLookupAPIRequest(RequestBase):
    """A creator to look up: its link, or for a creator without one, such as a Daily Wire host, its Site's id for it."""

    source_key: str = Field(min_length=1)
    url: Optional[str] = None
    ref: Optional[str] = None


class CreatorSectionAPIRead(ResponseBase):
    ref: str
    url: str
    title: str
    kind: Literal["feed", "list", "show", "item"]
    role: str
    kind_label: Optional[str] = None
    item_count: Optional[int] = None
    image_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("image_path", "image_url"))
    description: Optional[str] = None
    access: Optional[str] = None
    year: Optional[str] = None
    """The year an album came out."""
    collection_slug: Optional[str] = None
    """The collection that keeps the section, when one does."""
    collection_title: Optional[str] = None
    movie_slug: Optional[str] = None
    """The movie in the Library that this single item is, when it is one."""
    movie_title: Optional[str] = None
    movie_joined: bool = False
    """The movie is one of this creator's already."""
    status: Literal["known", "new", "ignored"] = "known"
    """For a creator in the Library: "new" when the daily look found it and it waits for a choice."""


class SectionPlanAPIRead(ResponseBase):
    ref: str
    target: SectionTarget


class CreatorNewListAPIRead(ListKindAPIRead):
    """What the creator does with a new list of one kind, such as a new playlist."""

    action: NewSectionAction


class CreatorPresetAPIRead(ResponseBase):
    key: CreatorPreset
    plan: list[SectionPlanAPIRead]
    music_plan: list[SectionPlanAPIRead]
    """The plan when the creator is added as a music artist."""


class CreatorLookupAPIRead(ResponseBase):
    """A creator at its Site, before it is added: who it is, its sections and what each preset does with them."""

    lookup_id: Optional[str] = None
    """Adding the creator with this id uses what this lookup found, instead of asking the Site again."""

    source_key: str
    site_key: str
    site_name: str
    creator_label: str
    music_creator_label: str
    """What the Site calls the creator when they are added as a music artist."""
    creator_sections: CreatorSectionNamesAPIRead
    """What the Site calls the things its creators add, such as playlists on YouTube or shows on The Daily Wire."""
    link_seasons: bool = False
    """The creator's lists can be seasons of its own collection."""
    movies: bool = False
    """The creator's single items are movies, which VODLoft adds to the Library and joins to the creator."""
    ref: str
    url: Optional[str] = None
    title: str
    handle: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    banner_url: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    sections: list[CreatorSectionAPIRead]
    presets: list[CreatorPresetAPIRead]
    new_lists: list[CreatorNewListAPIRead]
    """What the creator does with a new list of each kind of its Site until the user chooses otherwise."""
    music_new_lists: list[CreatorNewListAPIRead]
    """The same, when the creator is added as a music artist: their albums are added, and where the Site tells albums
    from other lists, those others are skipped."""
    creator_slug: Optional[str] = None
    """The creator's slug, when it is already in the Library."""
    music: bool = False
    """A music artist, whose lists are albums and whose collections are Music collections. Unless ``music_known``, it
    is a guess the user can change by adding the creator with ``type`` music or another type."""
    music_known: bool = False
    """The Site makes ``music`` certain, so the user isn't asked."""
    music_reason: Optional[str] = None
    """Why the creator was taken for a music artist, when that was a guess."""


class SectionPlanAPIIn(RequestBase):
    ref: str
    target: SectionTarget
    type: Optional[CollectionType] = None
    """For a section that becomes a collection of its own: its type; left out, the creator's."""
    episode_identifier: Optional[EpisodeIdentifier] = None
    """For a section that becomes a collection of its own: how it identifies its episodes; left out, the creator's."""


class CreatorAPICreate(RequestBase):
    """Add a creator, and a collection for each place its sections go."""

    source_key: str = Field(min_length=1)
    url: Optional[str] = None
    ref: Optional[str] = None
    sections: list[SectionPlanAPIIn] = Field(max_length=500)
    type: CollectionType = CollectionType.SERIES
    """The type of the creator's own collection, and of each collection of its own whose plan gives none."""
    episode_identifier: EpisodeIdentifier = EpisodeIdentifier.SEASONAL
    """How the creator's own collection identifies its episodes, and each collection whose plan says nothing."""
    membership_level: DwMembershipLevel = DwMembershipLevel.HIGHEST_ALLOWED
    new_lists: dict[str, NewSectionAction] = Field(default_factory=dict, max_length=20)
    """What the creator does with a new list, by the key of its kind; a kind left out takes its default."""
    lookup_id: Optional[str] = Field(default=None, max_length=64)
    """The lookup's id, to use what it found instead of asking the Site again."""
    into: Optional[str] = Field(default=None, max_length=255)
    """The slug of a creator in the Library whose account this is too, such as a host's YouTube channel: the account
    joins that creator instead of becoming a creator of its own."""


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
    links: list[str] = Field(default_factory=list)
    """The titles of the creator's sections it takes."""


class CreatorAccountAPIRead(ResponseBase):
    """A creator's account on one Site, such as their YouTube channel."""

    id: int
    source_key: str
    site: SiteAPIRead
    """The account's Site, with what it calls a creator and whether their lists can be seasons."""
    site_ref: str
    url: Optional[str] = None
    handle: Optional[str] = None
    checked_at: Optional[datetime] = None
    """When VODLoft last looked for new sections."""
    main_collection_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("main_collection", "slug"))
    """The collection named after the creator that takes this account's uploads."""


class CreatorAPIRead(ResponseBase):
    """A creator in the Library."""

    id: int
    slug: str
    creator_label: str
    """What VODLoft calls the creator: the word of their one Site, such as host, or artist for a music artist."""
    music: bool = False
    """A music artist: they have a Music collection."""
    section_names: CreatorSectionNamesAPIRead
    """What VODLoft looks for: what their one Site calls it, such as playlists, or playlists and shows."""
    kind: str
    """The label with their Site, when they are on one only, such as "The Daily Wire host"."""
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
    new_lists: list[CreatorNewListAPIRead]
    """What the creator does with a new list, for each kind of list of their Sites."""
    genre: Optional[str] = None
    content_rating: Optional[str] = None


class CreatorPageAccountAPIRead(CreatorAccountAPIRead):
    """An account on the creator's page, with its sections and the collection that keeps each."""

    sections: list[CreatorSectionAPIRead]
    movies: bool = False
    """The account's single items are movies, which VODLoft adds to the Library and joins to the creator."""


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
    """A creator's page: their collections, and the sections of each account with the collection that keeps each."""

    collections: list[CreatorCollectionAPIRead]
    movies: list[CreatorMovieAPIRead] = Field(default_factory=list)
    last_published_date: Optional[datetime] = None
    """When the newest episode of all of the creator's collections came out."""
    accounts: list[CreatorPageAccountAPIRead]
    reassigned_count: int = 0
    """The downloaded videos that the creator places in another of its collections than the one they are in."""


class CreatorSectionMoveAPIIn(RequestBase):
    """Where one of the creator's playlists goes now, with its videos."""

    target: Literal["main", "own", "skip"]


class CreatorAPIUpdate(RequestBase):
    """Change how VODLoft follows a creator."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    """The creator's name, which their collections take as author; left out, it stays as it is. A name given here
    is kept when the Site's name changes."""
    new_lists: dict[str, NewSectionAction] = Field(default_factory=dict, max_length=20)
    """What the creator does with a new list, by the key of its kind; a kind left out keeps its setting."""
    genre: Optional[str] = Field(default=None, max_length=200)
    content_rating: Optional[str] = Field(default=None, max_length=50)


class CreatorCombineAPIIn(RequestBase):
    """Another creator in the Library who is the same person or group, whose accounts and collections move over."""

    other_slug: str = Field(min_length=1, max_length=255)


class CreatorSectionsAPIAdd(RequestBase):
    """Add sections of a creator to its collections, or ignore them."""

    sections: list[SectionPlanAPIIn] = Field(min_length=1, max_length=500)
    type: Optional[CollectionType] = None
    """The type of the sections that become a collection of their own; left out, that of the creator's collection."""
    episode_identifier: Optional[EpisodeIdentifier] = None
    """How those collections number their episodes; left out, like the creator's collection."""


class CollectionCreatorMatchAPIRead(ResponseBase):
    """The creator behind a collection's link, before the collection is added to it."""

    lookup_id: Optional[str] = None
    """Adding the collection with this id uses what this lookup found, instead of asking the Site again."""

    site_name: str
    creator_label: str
    section_names: CreatorSectionNamesAPIRead
    ref: str
    url: Optional[str] = None
    title: str
    handle: Optional[str] = None
    avatar_url: Optional[str] = None
    creator_slug: Optional[str] = None
    """The creator's slug, when it is already in the Library."""
    section_title: Optional[str] = Field(default=None, validation_alias=AliasPath("section", "title"))
    """The creator's section the collection is, when it is one."""
    section_kind_label: Optional[str] = Field(default=None, validation_alias=AliasPath("section", "kind_label"))
    kept_by: Optional[str] = None
    """The title of another of the creator's collections that keeps this section already, which can't let it go."""
    overlaps: list["JoinOverlapAPIRead"] = Field(default_factory=list)
    """The lists that would be in two places once the collection joins: each stays in one, as the user chooses."""


class JoinOverlapAPIRead(ResponseBase):
    ref: str
    title: str
    kept_by: str = Field(validation_alias=AliasPath("kept_by", "title"))
    can_move_here: bool
    """The creator's own collection keeps it, and can let it go; a collection of its own keeps what it has."""


class CollectionCreatorJoinAPIIn(RequestBase):
    lookup_id: Optional[str] = Field(default=None, max_length=64)
    """The match's id, to use what it found instead of asking the Site again."""
    move_here: list[str] = Field(default_factory=list, max_length=5000)
    """The lists, by ref, that leave the creator's own collection for the joining one."""
    creator_slug: Optional[str] = Field(default=None, max_length=255)
    """A creator in the Library to join instead of the one behind the collection's link, such as an artist whose
    music videos are on their label's channel."""


class CollectionCreatorLeaveAPIRead(ResponseBase):
    """What removing a collection from its creator changes."""

    creator_title: str
