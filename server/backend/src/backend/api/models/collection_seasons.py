"""A collection's Seasons dialog: its seasons in order, and whether its channel's playlists are seasons."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.types.link_season_types import LooseVideos, NewLinkSeasonAction, LinkSeasons, LinkSeasonStatus, OutsideVideos


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
    link_title: Optional[str] = None
    """The playlist the season is, when it is one."""


class LinkSeasonAPIRead(ResponseBase):
    id: int
    ref: str
    url: str
    title: str
    image_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("image_path", "image_url"))
    item_count: Optional[int] = None
    enabled: bool
    status: LinkSeasonStatus
    """new while it waits for the user's choice."""
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
    channel."""


class LinkSeasonNamesAPIRead(ResponseBase):
    one: str
    many: str
    loose_season: str


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
    new_link_seasons: NewLinkSeasonAction
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
    names: LinkSeasonNamesAPIRead
    """What the collection's Site calls its link seasons, such as playlists or albums."""
    music: bool = False
    """A Music collection, of an artist's tracks rather than a channel's videos."""
    playlists: list[LinkSeasonAPIRead]


class MovedEpisodesAPIRead(ResponseBase):
    episode_slugs: list[str]
    """The episodes that belong in another season now, by slug."""


class SeasonChangeAPIIn(RequestBase):
    id: int
    name: str = Field(min_length=1, max_length=200)


class LinkSeasonChangeAPIIn(RequestBase):
    id: int
    enabled: bool


class CollectionSeasonsAPIUpdate(RequestBase):
    """The seasons in the order the user wants them, with their names, and how the playlists are seasons."""

    seasons: list[SeasonChangeAPIIn] = Field(max_length=2000)
    """Every season of the collection, in its new order."""
    custom_season_order: bool
    """False puts the seasons back in VODLoft's order by date, whatever ``seasons`` says about their order."""
    link_seasons: LinkSeasons = LinkSeasons.OFF
    new_link_seasons: NewLinkSeasonAction = NewLinkSeasonAction.ASK
    loose_videos: LooseVideos = LooseVideos.ONE_SEASON
    outside_videos: OutsideVideos = OutsideVideos.LEAVE_OUT
    playlists: list[LinkSeasonChangeAPIIn] = Field(default_factory=list, max_length=5000)
    removed_links: list[int] = Field(default_factory=list, max_length=5000)
    """Links the user added that they remove again, by id."""


class LinkSeasonAddAPIIn(RequestBase):
    """A link the user adds to a collection that holds only its link seasons: a playlist, channel or video."""

    url: str = Field(min_length=1, max_length=2000, pattern=r"^https?://")
