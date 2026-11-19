"""A collection's Seasons dialog: its seasons in order, and whether its creator's playlists are seasons."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.source import ListKindAPIRead
from backend.types.link_season_types import ListLayout, LooseVideos, NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos


class CollectionSeasonAPIRead(ResponseBase):
    id: int
    slug: str
    name: str
    season_number: int
    index: int
    season_type: str
    loose: bool
    """Holds the videos in none of the playlists that are seasons."""
    episode_count: int = 0
    list_titles: list[str] = Field(default_factory=list)
    """The lists the season holds, when it is a season of lists, in the order their videos go."""


class CollectionListAPIRead(ResponseBase):
    id: int
    ref: str
    url: str
    title: str
    image_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("image_path", "image_url"))
    item_count: Optional[int] = None
    enabled: bool
    status: ListStatus
    """new while it waits for the user's choice."""
    season_id: Optional[int] = None
    """The list's season, which other lists may share."""
    season_name: Optional[str] = Field(default=None, validation_alias=AliasPath("season", "name"))
    first_video_at: Optional[datetime] = None
    """When the first of the collection's videos the playlist has came out, which orders the playlists."""
    leaving_count: int = 0
    """The videos from outside the collection's own link that only this playlist lists, which leave the collection,
    files and all, when it stops being a season."""
    leaving_with_files: int = 0
    """How many of those have files."""
    added_by_user: bool = False
    """A link the user added, which they can remove again, rather than one of the playlists of the collection's
    creator."""


class ListNamesAPIRead(ResponseBase):
    one: str
    many: str
    loose_season: str


class CollectionNewListAPIRead(ListKindAPIRead):
    """What the collection does with a new list of one kind, when only selected lists are seasons."""

    action: NewLinkSeasonAction


class CollectionSeasonsAPIRead(ResponseBase):
    seasons: list[CollectionSeasonAPIRead]
    custom_season_order: bool
    """The user put the seasons in their own order; otherwise VODLoft orders them by date."""
    link_seasons_offered: bool
    """The collection is a whole channel on a Site whose playlists can be seasons, or holds only its link seasons."""
    has_own_link: bool
    """The collection has a link of its own; one that only holds its link seasons may go without."""
    lists_playlists: bool
    """The collection's own link is a whole channel, whose playlists are listed for it."""
    links_only_offered: bool
    """The collection can hold only what its link seasons have, with links the user adds from any Site of its
    Source."""
    link_seasons: LinkSeasons
    new_lists: list[CollectionNewListAPIRead]
    """What happens with a list the creator adds, for each kind of list of the collection's Site."""
    list_layout: ListLayout
    loose_videos: LooseVideos
    outside_videos: OutsideVideos
    outside_count: int = 0
    """The videos the collection added from its playlists that its own link does not list, which all leave, files and
    all, when it stops adding them or its playlists stop being seasons."""
    outside_with_files: int = 0
    only_leaving_count: int = 0
    """The videos that no playlist that is a season has now, which leave, files and all, when the collection is set
    to hold only what its playlists have."""
    only_leaving_with_files: int = 0
    names: ListNamesAPIRead
    creator_slug: Optional[str] = None
    """For a creator's own collection: the creator, which finds its new lists and decides what happens with them."""
    creator_title: Optional[str] = None
    """What the collection's Site calls its link seasons, such as playlists or albums."""
    music: bool = False
    creator_label: str
    """What the collection's Site calls the creator behind it, such as artist in a Music collection."""
    """A Music collection, of an artist's tracks rather than a creator's videos."""
    playlists: list[CollectionListAPIRead]


class MovedEpisodesAPIRead(ResponseBase):
    episode_slugs: list[str]
    """The episodes that belong in another season now, by slug."""


class ReassignedEpisodeAPIRead(ResponseBase):
    """A downloaded video that its creator places in another of its collections now."""

    episode_slug: str = Field(validation_alias=AliasPath("episode", "slug"))
    collection_slug: str = Field(validation_alias=AliasPath("target", "collection", "slug"))
    collection_title: str = Field(validation_alias=AliasPath("target", "collection", "title"))


class ReassignedEpisodesAPIRead(ResponseBase):
    episodes: list[ReassignedEpisodeAPIRead]


class ReassignedMoveAPIRead(ResponseBase):
    """What moving reassigned videos did."""

    episodes: int
    renamed: int
    """Downloads whose files move to their new collection."""
    downloading: int
    """Downloads that the new collection makes again with its own Local Media Profile; the old files go once they
    succeed."""
    operation_ids: list[str]
    episode_slug: Optional[str] = None
    """For one episode: the episode in its new collection."""
    collection_slug: Optional[str] = None


class SeasonChangeAPIIn(RequestBase):
    id: int
    name: str = Field(min_length=1, max_length=200)


class CollectionListChangeAPIIn(RequestBase):
    id: int
    enabled: bool
    season_id: Optional[int] = None
    """The season the list is in: its own, or that of another of the collection's lists, which it then shares. None
    gives it a season of its own."""


class CollectionSeasonsAPIUpdate(RequestBase):
    """The seasons in the order the user wants them, with their names, and how the playlists are seasons."""

    seasons: list[SeasonChangeAPIIn] = Field(max_length=2000)
    """Every season of the collection, in its new order."""
    custom_season_order: bool
    """False puts the seasons back in VODLoft's order by date, whatever ``seasons`` says about their order."""
    link_seasons: LinkSeasons = LinkSeasons.OFF
    new_lists: dict[str, NewLinkSeasonAction] = Field(default_factory=dict, max_length=20)
    """What happens with a list the creator adds, by the key of its kind; a kind left out keeps its setting."""
    list_layout: ListLayout = ListLayout.SEASON_EACH
    loose_videos: LooseVideos = LooseVideos.ONE_SEASON
    outside_videos: OutsideVideos = OutsideVideos.LEAVE_OUT
    playlists: list[CollectionListChangeAPIIn] = Field(default_factory=list, max_length=5000)
    removed_links: list[int] = Field(default_factory=list, max_length=5000)
    """Links the user added that they remove again, by id."""


class CollectionListAddAPIIn(RequestBase):
    """A link the user adds to a collection that holds only its link seasons: a playlist, channel or video."""

    url: str = Field(min_length=1, max_length=2000, pattern=r"^https?://")
