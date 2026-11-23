"""A collection's Seasons dialog: its seasons in order, which feeds of its channel it takes, and whether the channel's
playlists are seasons."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.collection_contract import CollectionWordsAPIRead
from backend.api.models.source import ListKindAPIRead, NamesAPIRead, SectionTypeAPIRead
from backend.types.link_season_types import (
    ChannelSeason, CollectionKind, ListLayout, LooseVideos, NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos, RepeatVideos,
)


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
    removable: bool = False
    """VODLoft or the user made it, so the user can remove it: its videos go where the settings put them."""
    year: int | None = None
    """The year it holds, when VODLoft made it for the videos of one year."""


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
    as_season: bool = True
    """Whether the list is a season of its own when it is on; one that is not adds its videos to the other seasons."""
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
    channel."""
    is_default: bool = False
    """For a collection without a link of its own: its default link, such as the one its picture comes from. Such a
    collection always has one."""


class CollectionFeedAPIRead(ResponseBase):
    """One feed of a channel collection's channel, such as YouTube's Shorts."""

    ref: str
    names: NamesAPIRead
    """What the Site calls the feed's videos, such as shorts; the feed is named after them."""
    on: bool


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
    kind: CollectionKind
    """What the collection's own link is: a channel, or one list."""
    feeds: list[CollectionFeedAPIRead]
    """For a channel collection: the feeds of its channel, and whether it takes each."""
    channel_season: ChannelSeason
    """What the season of the channel's own videos holds: everything, or only the videos in no list."""
    channel_season_names: dict[str, str]
    """What that season is called with each choice, such as Channel and Videos."""
    channel_names: NamesAPIRead
    """What the collection's Site calls a channel, such as channel, or account on SoundCloud."""
    link_seasons: LinkSeasons
    new_lists: list[CollectionNewListAPIRead]
    """What happens with a list the channel adds, for each kind of list of the collection's Site."""
    list_layout: ListLayout
    loose_videos: LooseVideos
    repeat_videos: RepeatVideos
    """Whether a video that belongs in several seasons has an episode in the first of them, or in each."""
    repeated_count: int = 0
    """The episodes of videos the collection has in another season already, which leave when it keeps one season."""
    outside_videos: OutsideVideos
    outside_count: int = 0
    """The videos the collection added from its playlists that its own link does not list, which all leave, files and
    all, when it stops adding them or its playlists stop being seasons."""
    outside_with_files: int = 0
    only_leaving_count: int = 0
    """The videos that no playlist that is a season has now, which leave, files and all, when the collection is set
    to hold only what its playlists have."""
    only_leaving_with_files: int = 0
    list_types: list[SectionTypeAPIRead]
    """The types of list of the collection's Site, which its link seasons come from, such as playlists, or albums and
    playlists on SoundCloud."""
    section_list_names: NamesAPIRead
    """Those types of list named together, such as albums and playlists."""
    creator_list_names: NamesAPIRead
    """The same lists as the creator's, such as creator playlists or artist albums, so they read apart from the
    collection's own seasons, which a YouTube channel collection also calls playlists."""
    loose_season: str
    """The name of the season of the videos in none of the lists, such as Videos, Singles or Tracks."""
    site_order: bool = False
    """The link seasons keep the order the Site gives the lists, as an artist's albums do, instead of by date."""
    words: CollectionWordsAPIRead
    """What the collection calls its seasons and episodes."""
    creator_names: NamesAPIRead
    """What the collection calls the creator behind it, such as artist in a Music collection."""
    media_names: NamesAPIRead
    """What the collection calls what its lists hold: the Site's videos, tracks on a Site with sound only, or the
    music videos of a Music collection."""
    playlists: list[CollectionListAPIRead]


class SeasonsPreviewAPIRead(ResponseBase):
    seasons: list[CollectionSeasonAPIRead]
    """The collection's seasons as saving the dialog leaves them, in their order."""


class MovedEpisodesAPIRead(ResponseBase):
    episode_slugs: list[str]
    """The episodes that belong in another season now, by slug."""


class SeasonChangeAPIIn(RequestBase):
    id: int
    name: str = Field(min_length=1, max_length=200)


class CollectionListChangeAPIIn(RequestBase):
    id: int
    enabled: bool
    as_season: bool = True
    """False adds the list's videos to the collection's other seasons, without a season of its own."""
    season_id: Optional[int] = None
    """The season the list is in: its own, or that of another of the collection's lists, which it then shares. None
    gives it a season of its own."""
    is_default: bool = False
    """For a collection without a link of its own: the user's default link. One link at most; without one, the first
    link that stays is the default."""


class CollectionSeasonsAPIUpdate(RequestBase):
    """The seasons in the order the user wants them, with their names, and how the playlists are seasons."""

    seasons: list[SeasonChangeAPIIn] = Field(max_length=2000)
    """Every season of the collection, in its new order."""
    custom_season_order: bool
    """False puts the seasons back in VODLoft's order by date, whatever ``seasons`` says about their order."""
    feeds: Optional[list[str]] = Field(default=None, max_length=20)
    """For a channel collection: the refs of the feeds it takes; None takes all of them."""
    channel_season: Optional[ChannelSeason] = None
    """None keeps the collection's setting."""
    link_seasons: LinkSeasons = LinkSeasons.OFF
    new_lists: dict[str, NewLinkSeasonAction] = Field(default_factory=dict, max_length=20)
    """What happens with a list the channel adds, by the key of its kind; a kind left out keeps its setting."""
    list_layout: ListLayout = ListLayout.SEASON_EACH
    loose_videos: LooseVideos = LooseVideos.ONE_SEASON
    repeat_videos: Optional[RepeatVideos] = None
    """None keeps the collection's setting."""
    outside_videos: OutsideVideos = OutsideVideos.LEAVE_OUT
    playlists: list[CollectionListChangeAPIIn] = Field(default_factory=list, max_length=5000)
    removed_links: list[int] = Field(default_factory=list, max_length=5000)
    """Links the user added that they remove again, by id."""
    removed_seasons: list[int] = Field(default_factory=list, max_length=2000)
    """Seasons the user removes, by id. Their videos go where the settings put them, which can be a season like it."""


class CollectionListAddAPIIn(RequestBase):
    """A link the user adds to a collection that holds only its link seasons: a playlist, channel or video."""

    url: str = Field(min_length=1, max_length=2000, pattern=r"^https?://")
