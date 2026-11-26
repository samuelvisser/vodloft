"""A collection's Seasons dialog: its seasons in order, which feeds of its channel it takes, and whether the channel's
playlists are seasons."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.collection_contract import CollectionWordsAPIRead
from backend.api.models.reconcile import MoveCauseAPIRead, MovePreviewAPIRead
from backend.api.models.source import ListKindAPIRead, NamesAPIRead, SectionTypeAPIRead
from backend.services.list_previews import ListingState
from backend.types.link_season_types import (
    CollectionKind, LooseVideos, NewLinkSeasonAction, LinkSeasons, ListStatus, OutsideVideos, RepeatVideos,
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
    type_key: Optional[str] = None
    """The key of the list's type on its Site, such as album or playlist; None for a link the user added, or a list
    VODLoft has not listed since it learned types."""
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
    listed: bool = False
    """VODLoft knows what the list holds, as it listed it before; the dialog lists one that is switched on otherwise,
    so its review can say what saving moves."""


class CollectionFeedAPIRead(ResponseBase):
    """One feed of a channel collection's channel, such as YouTube's Shorts."""

    ref: str
    names: NamesAPIRead
    """What the Site calls the feed's videos, such as shorts; the feed is named after them."""
    on: bool
    as_season: bool = False
    """The feed is a season of its own; otherwise its videos are part of the collection."""
    season_id: Optional[int] = None
    """The feed's own season, once it has one, which lists or other feeds may share."""


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
    made_from_list: bool
    """The collection is made from one list: the list is its one season, or its videos go in a season per year."""
    feeds: list[CollectionFeedAPIRead]
    """For a channel collection: the feeds of its channel, and whether it takes each."""
    channel_season_offered: bool
    """The videos of the collection's feeds can be in one season of their own rather than a season per year."""
    channel_season_names: dict[str, str]
    """What that season is called by how the collection groups its videos (``loose_videos``), such as Channel while
    it holds everything and Videos while it holds what is in no list."""
    channel_names: NamesAPIRead
    """What the collection's Site calls a channel, such as channel, or account on SoundCloud."""
    link_seasons: LinkSeasons
    new_lists: list[CollectionNewListAPIRead]
    """What happens with a list the channel adds, for each kind of list of the collection's Site."""
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
    collection's own seasons, which a YouTube channel collection also calls playlists. A collection without a link of
    its own calls them links: the ones the user gave it."""
    collection_names: NamesAPIRead
    """What VODLoft calls a collection, for the badge of a season that holds what is part of the collection."""
    link_names: NamesAPIRead
    """What VODLoft calls the links the user gives a collection, for the badge of a season they are in."""
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


class WaitingSeasonAPIRead(ResponseBase):
    list_id: int
    title: str
    """The name its season gets: its list's title."""


class SeasonsPreviewAPIRead(ResponseBase):
    seasons: list[CollectionSeasonAPIRead]
    """The collection's seasons as saving the dialog leaves them, in their order."""
    waiting: list[WaitingSeasonAPIRead] = Field(default_factory=list)
    """The lists that become a season of their own once VODLoft has listed their videos, which it does after saving:
    the preview shows their season without fetching a list that may be long."""


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
    """False makes the list's videos part of the collection, without a season of its own."""
    season_id: Optional[int] = None
    """The season the list is in: its own, or that of another of the collection's lists or feeds, which it then
    shares. None gives it a season of its own."""
    is_default: bool = False
    """For a collection without a link of its own: the user's default link. One link at most; without one, the first
    link that stays is the default."""


TOKEN_PATTERN = r"^[A-Za-z0-9-]+$"
"""The open Seasons dialog's token, such as a UUID."""


class AddedLinkAPIIn(RequestBase):
    """A link the user adds in the Seasons dialog, as the dialog looked it up."""

    url: str = Field(min_length=1, max_length=2000, pattern=r"^https?://")
    title: str = Field(default="", max_length=1000)
    as_season: bool = True
    """A season of its own; otherwise its videos are part of the collection."""


class CollectionSeasonsAPIUpdate(RequestBase):
    """The seasons in the order the user wants them, with their names, and how the playlists are seasons."""

    seasons: list[SeasonChangeAPIIn] = Field(max_length=2000)
    """Every season of the collection, in its new order."""
    custom_season_order: bool
    """False puts the seasons back in VODLoft's order by date, whatever ``seasons`` says about their order."""
    feeds: Optional[list[str]] = Field(default=None, max_length=20)
    """For a channel collection: the refs of the feeds it takes; None takes all of them."""
    feed_seasons: Optional[dict[str, Optional[int]]] = Field(default=None, max_length=20)
    """For a channel collection: the feeds it takes that are a season of their own, by ref, each with the season it
    is in: its own, or that of a list or another feed, which it then shares. None gives it a season of its own. The
    whole setting left out keeps the collection's."""
    link_seasons: LinkSeasons = LinkSeasons.OFF
    new_lists: dict[str, NewLinkSeasonAction] = Field(default_factory=dict, max_length=20)
    """What happens with a list the channel adds, by the key of its kind; a kind left out keeps its setting."""
    loose_videos: LooseVideos = LooseVideos.ONE_SEASON
    repeat_videos: Optional[RepeatVideos] = None
    """None keeps the collection's setting."""
    outside_videos: OutsideVideos = OutsideVideos.LEAVE_OUT
    playlists: list[CollectionListChangeAPIIn] = Field(default_factory=list, max_length=5000)
    removed_links: list[int] = Field(default_factory=list, max_length=5000)
    """Links the user added that they remove again, by id."""
    added_links: list[AddedLinkAPIIn] = Field(default_factory=list, max_length=200)
    """Links the user adds, saved with the rest."""
    removed_seasons: list[int] = Field(default_factory=list, max_length=2000)
    """Seasons the user removes, by id. Their videos go where the settings put them, which can be a season like it."""
    listing_token: Optional[str] = Field(default=None, max_length=64, pattern=TOKEN_PATTERN)
    """The open dialog's token: what it listed (``SeasonsListingsAPIIn``) is what the review plans with and what
    saving takes along."""
    renumber: bool = True
    """Saving: whether the collection numbers its episodes again after the downloads moved."""


class CollectionListAddAPIIn(RequestBase):
    """A link the user adds to a collection: a playlist, channel or video."""

    url: str = Field(min_length=1, max_length=2000, pattern=r"^https?://")


class AddedLinkAPIRead(ResponseBase):
    """A link the user adds, as VODLoft found it. Nothing is saved until the Seasons dialog is."""

    url: str
    title: str
    image_url: Optional[str] = None


class SeasonsListingsAPIIn(RequestBase):
    """The lists the open Seasons dialog wants listed for its review: lists of the collection VODLoft has not listed,
    by id, and links the user adds. One it listed or is listing already is not listed again."""

    token: str = Field(min_length=8, max_length=64, pattern=TOKEN_PATTERN)
    list_ids: list[int] = Field(default_factory=list, max_length=5000)
    links: list[Annotated[str, Field(min_length=1, max_length=2000, pattern=r"^https?://")]] = Field(
        default_factory=list, max_length=200,
    )


class SeasonsListingAPIRead(ResponseBase):
    list_id: Optional[int] = None
    link: Optional[str] = None
    """For a link the user adds: the link as the user gave it."""
    state: ListingState
    count: int = 0
    """How many videos it lists, once listed."""


class SeasonsListingsAPIRead(ResponseBase):
    listings: list[SeasonsListingAPIRead]


class ReviewVideosAPIRead(ResponseBase):
    count: int = 0
    examples: list[str] = Field(default_factory=list)
    """Their titles, newest first, up to a few dozen."""


class ReviewFilesAPIRead(ReviewVideosAPIRead):
    profiles: list[str] = Field(default_factory=list)
    """The Local Media Profiles their files are in."""


class SeasonsReviewAPIRead(ResponseBase):
    """What saving the Seasons dialog does, for its review: nothing is saved until the user agrees to it."""

    busy: Optional[str] = None
    """What the review waits for, such as a list VODLoft is still listing; the rest is empty meanwhile."""
    seasons: list[CollectionSeasonAPIRead] = Field(default_factory=list)
    waiting: list[WaitingSeasonAPIRead] = Field(default_factory=list)
    causes: list[MoveCauseAPIRead] = Field(default_factory=list)
    """The settings saving changes that decide where videos go, each as it was and as it becomes."""
    new_seasons: list[str] = Field(default_factory=list)
    deleted_seasons: list[str] = Field(default_factory=list)
    moves: Optional[MovePreviewAPIRead] = None
    """What moves where, and the numbering after it, as the Move dialog says it."""
    leaving: ReviewVideosAPIRead = Field(default_factory=ReviewVideosAPIRead)
    """The videos that leave the collection."""
    extra: ReviewVideosAPIRead = Field(default_factory=ReviewVideosAPIRead)
    """The episodes that go while their video stays in another season, such as when a list stops being a season of
    its own in a collection that holds every video in one season too."""
    deleted_files: ReviewFilesAPIRead = Field(default_factory=ReviewFilesAPIRead)
    """The downloaded files of the episodes that go, which are deleted."""
    joining: int = 0
    """New videos that join the collection from its lists, which its Download Profiles then download as they say."""
