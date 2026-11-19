from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import AliasChoices, AliasPath, Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.source import SiteAPIRead
from backend.types.channel_types import NewSectionAction, SectionTarget
from backend.types.collection_link_types import LinkPlacement
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
    kind: Literal["feed", "list", "item"]
    role: str
    kind_label: Optional[str] = None
    item_count: Optional[int] = None
    image_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("image_path", "image_url"))
    description: Optional[str] = None
    access: Optional[str] = None
    has_seasons: bool = False
    collection_slug: Optional[str] = None
    """The collection that keeps the section, when one does."""
    collection_title: Optional[str] = None
    status: Literal["known", "new", "ignored"] = "known"
    """For a channel in the Library: "new" when the daily look found it and it waits for a choice."""


class SectionPlanAPIRead(ResponseBase):
    ref: str
    target: SectionTarget
    placement: LinkPlacement


class ChannelPresetAPIRead(ResponseBase):
    key: ChannelPreset
    plan: list[SectionPlanAPIRead]


class ChannelLookupAPIRead(ResponseBase):
    """A channel at its Site, before it is added: who it is, its sections and what each preset does with them."""

    source_key: str
    site_key: str
    site_name: str
    channel_label: str
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
    claim_order: list[str]
    """The section refs in the order that decides which keeps a video several of them list."""
    presets: list[ChannelPresetAPIRead]
    channel_slug: Optional[str] = None
    """The channel's slug, when it is already in the Library."""


class SectionPlanAPIIn(RequestBase):
    ref: str
    target: SectionTarget
    placement: LinkPlacement = LinkPlacement.SITE_SEASONS


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


class ChannelOrderEntryAPIRead(ResponseBase):
    """A section a collection of the channel takes, in the channel's order."""

    ref: str
    title: str
    kind: Literal["feed", "list", "item"]
    kind_label: Optional[str] = None
    collection_slug: str
    collection_title: str
    placement: LinkPlacement
    video_count: int = 0
    """How many videos the section lists."""


class ChannelPageAPIRead(ChannelAPIRead):
    """A channel's page: its collections, and the sections no collection keeps."""

    collections: list[ChannelCollectionAPIRead]
    sections: list[ChannelSectionAPIRead]
    order: list[ChannelOrderEntryAPIRead]
    main_collection_slug: Optional[str] = Field(default=None, validation_alias=AliasPath("main_collection", "slug"))


class ChannelAPIUpdate(RequestBase):
    """Change how VODLoft follows a channel."""

    new_sections: NewSectionAction
    genre: Optional[str] = Field(default=None, max_length=200)
    content_rating: Optional[str] = Field(default=None, max_length=50)
    order: Optional[list[str]] = Field(default=None, max_length=500)
    """The refs of the sections the channel's collections take, highest first."""


class ChannelSectionsAPIAdd(RequestBase):
    """Add sections of a channel to its collections, or ignore them."""

    sections: list[SectionPlanAPIIn] = Field(min_length=1, max_length=500)
