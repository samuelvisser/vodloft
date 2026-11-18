from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.source import SiteAPIRead
from backend.types.channel_types import NewSectionAction, SectionTarget
from backend.types.collection_types import CollectionType, EpisodeIdentifier
from backend.types.dailywire_user_info import DwMembershipLevel
from sources import ChannelPreset


class ChannelLookupAPIRequest(RequestBase):
    """A channel to look up: its link, or for a channel without one, such as a Daily Wire host, its Site's id for it."""

    source_key: str = Field(min_length=1)
    url: Optional[str] = None
    ref: Optional[str] = None


class ChannelSectionAPIRead(ResponseBase):
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
    status: Literal["known", "new", "ignored"] = "known"
    """For a channel in the Library: "new" when the daily look found it and it waits for a choice."""


class SectionPlanAPIRead(ResponseBase):
    ref: str
    target: SectionTarget


class ChannelPresetAPIRead(ResponseBase):
    key: ChannelPreset
    plan: list[SectionPlanAPIRead]


class ChannelLookupAPIRead(ResponseBase):
    """A channel at its Site, before it is added: who it is, its sections and what each preset does with them."""

    source_key: str
    site_key: str
    site_name: str
    channel_label: str
    link_seasons: bool = False
    """The channel's lists can be seasons of its own collection."""
    ref: str
    url: Optional[str] = None
    title: str
    handle: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    banner_url: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    sections: list[ChannelSectionAPIRead]
    presets: list[ChannelPresetAPIRead]
    channel_slug: Optional[str] = None
    """The channel's slug, when it is already in the Library."""
    music: bool = False
    """A music artist, whose lists are albums and whose collections are Music collections."""


class SectionPlanAPIIn(RequestBase):
    ref: str
    target: SectionTarget


class ChannelAPICreate(RequestBase):
    """Add a channel, and a collection for each place its sections go."""

    source_key: str = Field(min_length=1)
    url: Optional[str] = None
    ref: Optional[str] = None
    sections: list[SectionPlanAPIIn] = Field(max_length=500)
    type: CollectionType = CollectionType.SERIES
    episode_identifier: EpisodeIdentifier = EpisodeIdentifier.SEASONAL
    membership_level: DwMembershipLevel = DwMembershipLevel.HIGHEST_ALLOWED
    new_sections: NewSectionAction = NewSectionAction.ASK


class ChannelCollectionAPIRead(ResponseBase):
    slug: str
    title: str
    type: str
    thumbnail_landscape_path: Optional[str] = None
    episode_count: int = 0
    links: list[str] = Field(default_factory=list)
    """The titles of the channel's sections it takes."""


class ChannelAPIRead(ResponseBase):
    """A channel in the Library."""

    id: int
    slug: str
    source_key: str
    site: SiteAPIRead
    channel_label: str
    site_ref: str
    url: Optional[str] = None
    title: str
    handle: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("avatar_path", "avatar_url"))
    banner_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("banner_path", "banner_url"))
    links: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    created_at: datetime
    collection_count: int = 0
    episode_count: int = 0
    new_sections: NewSectionAction
    genre: Optional[str] = None
    content_rating: Optional[str] = None
    checked_at: Optional[datetime] = None
    """When VODLoft last looked for new sections."""


class ChannelPageAPIRead(ChannelAPIRead):
    """A channel's page: its collections, and its sections with the collection that keeps each."""

    collections: list[ChannelCollectionAPIRead]
    sections: list[ChannelSectionAPIRead]
    main_collection_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("main_collection", "slug"))
    reassigned_count: int = 0
    """The downloaded videos that the channel places in another of its collections than the one they are in."""


class ChannelSectionMoveAPIIn(RequestBase):
    """Where one of the channel's playlists goes now, with its videos."""

    target: Literal["main", "own", "skip"]


class ChannelAPIUpdate(RequestBase):
    """Change how VODLoft follows a channel."""

    new_sections: NewSectionAction
    genre: Optional[str] = Field(default=None, max_length=200)
    content_rating: Optional[str] = Field(default=None, max_length=50)


class ChannelSectionsAPIAdd(RequestBase):
    """Add sections of a channel to its collections, or ignore them."""

    sections: list[SectionPlanAPIIn] = Field(min_length=1, max_length=500)


class CollectionChannelMatchAPIRead(ResponseBase):
    """The channel behind a collection's link, before the collection is added to it."""

    site_name: str
    channel_label: str
    ref: str
    url: Optional[str] = None
    title: str
    handle: Optional[str] = None
    avatar_url: Optional[str] = None
    channel_slug: Optional[str] = None
    """The channel's slug, when it is already in the Library."""
    section_title: Optional[str] = Field(default=None, validation_alias=AliasPath("section", "title"))
    """The channel's section the collection is, when it is one."""
    section_kind_label: Optional[str] = Field(default=None, validation_alias=AliasPath("section", "kind_label"))
    kept_by: Optional[str] = None
    """The title of another of the channel's collections that keeps this section already, which can't let it go."""
    overlaps: list["JoinOverlapAPIRead"] = Field(default_factory=list)
    """The lists that would be in two places once the collection joins: each stays in one, as the user chooses."""


class JoinOverlapAPIRead(ResponseBase):
    ref: str
    title: str
    kept_by: str = Field(validation_alias=AliasPath("kept_by", "title"))
    can_move_here: bool
    """The channel's own collection keeps it, and can let it go; a collection of its own keeps what it has."""


class CollectionChannelJoinAPIIn(RequestBase):
    move_here: list[str] = Field(default_factory=list, max_length=5000)
    """The lists, by ref, that leave the channel's own collection for the joining one."""
    channel_slug: Optional[str] = Field(default=None, max_length=255)
    """A channel in the Library to join instead of the one behind the collection's link, such as an artist whose
    music videos are on their label's channel."""


class CollectionChannelLeaveAPIRead(ResponseBase):
    """What removing a collection from its channel changes."""

    channel_title: str
