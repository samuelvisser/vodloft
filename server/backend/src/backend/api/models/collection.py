from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Optional, Union
from datetime import date, datetime

from pydantic import AliasChoices, AliasPath, computed_field, Field, StringConstraints, ValidationInfo, field_validator, model_validator

from backend.api.models.base import RequestBase, ResponseBase, response_model_config
from backend.api.models.custom_metadata import CustomMetadataResponseBase
from backend.api.models.profile_bulk import BulkChangeIn, BulkChangesIn, BulkFieldSummaryRead, BulkSummaryRead
from backend.api.models.source import NamesAPIRead, SiteAPIRead, SourcedResponse
from backend.types.collection_contracts import collection_contract
from backend.types.collection_health_types import HealthIssueKind
from backend.types.collection_types import CheckFrequency, CollectionType, CookiesMode, EpisodeIdentifier, EpisodeOrder
from backend.types.link_season_types import CollectionKind, LinkSeasons, LooseVideos, OutsideVideos, SourceRole
from backend.types.resource_names import CUSTOM_COLLECTION_NAMES
from config.settings.cron_validation import CronExpressionError, validate_cron_expression
from backend.types.download_profile_types import EpisodeTagKey
from backend.utils.helpers import generate_uuid
from backend.api.models.source import checked_ytdlp_options
from backend.services.unplayable_formats import options_allow_unplayable_formats
from sources import Site, site_of
from sources.ytdlp_options import MAX_OPTIONS_LENGTH


# ---------- Strict input (create/update) ----------
class _CollectionAPIBaseIn(RequestBase):
    """Fields for requests: validate here if needed."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    description: Optional[str] = None
    sharing_url: Optional[str] = None
    """The collection's own link; only a collection that holds only what its link seasons have may go without."""
    membership_level: str
    author_name: str
    author_headshot_path: Optional[str] = None
    background_image_path: Optional[str] = None
    logo_image_path: Optional[str] = None
    thumbnail_landscape_path: Optional[str] = None
    thumbnail_portrait_path: Optional[str] = None
    thumbnail_square_path: Optional[str] = None


class CollectionAPICreate(_CollectionAPIBaseIn):
    """Request body for creating a collection."""

    sharing_url: str
    slug: str
    source_key: str = Field(min_length=1)
    membership_level: str = Field(min_length=1)
    type: CollectionType
    episode_identifier: EpisodeIdentifier
    author_slug: str
    list_type: Optional[str] = None
    """Which of its Site's types of list the link is, as looking the link up told."""

    @computed_field(return_type=str)
    @property
    def uuid(self) -> str:
        return generate_uuid()


class CollectionLinksOnlyAPICreate(RequestBase):
    """A new collection without a link of its own, which holds only what the links the user adds to it have."""

    title: str = Field(min_length=1, max_length=200)
    type: CollectionType = CollectionType.SERIES

    @field_validator("type")
    @classmethod
    def _series_or_music(cls, value: CollectionType) -> CollectionType:
        if CollectionType(value) not in (CollectionType.SERIES, CollectionType.MUSIC):
            raise ValueError("An empty collection is a Series or Music")
        return value


class CollectionAPIUpdate(_CollectionAPIBaseIn):
    """Request body for updating a collection.

    Collections from a Source without membership levels leave ``membership_level`` out.
    """

    membership_level: Optional[str] = None
    type: Optional[CollectionType] = None
    """Podcast, Series or Music; left out, it stays as it is."""
    ytdlp_options: Optional[str] = Field(default=None, max_length=MAX_OPTIONS_LENGTH)
    """Your own yt-dlp options for this Collection; left out, they stay as they are."""

    cookies_mode: Optional[CookiesMode] = None
    split_chapters: Optional[bool] = None
    """Whether each new video with chapters becomes a season with an episode per chapter; left out, it stays."""
    episode_order: Optional[EpisodeOrder] = None
    genre: Optional[str] = Field(default=None, max_length=200)
    """The show's genre in its NFO files; left out, it stays as it is, and empty removes it."""
    content_rating: Optional[str] = Field(default=None, max_length=50)
    """The show's content rating in its NFO files, such as TV-14; left out, it stays as it is."""
    check_frequency: Optional[CheckFrequency] = None
    check_cron: Optional[str] = Field(default=None, validate_default=True)
    """The Collection's own schedule, with ``check_frequency`` own."""

    @field_validator("ytdlp_options")
    @classmethod
    def _validate_ytdlp_options(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else checked_ytdlp_options(value)

    @field_validator("genre", "content_rating")
    @classmethod
    def _strip_metadata(cls, value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None

    @field_validator("check_cron")
    @classmethod
    def _validate_check_cron(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is None or not value.strip():
            if info.data.get("check_frequency") == CheckFrequency.OWN:
                raise ValueError("Enter the schedule to check this Collection on")
            return None
        value = " ".join(value.split())
        try:
            validate_cron_expression(value)
        except CronExpressionError as exc:
            raise ValueError(str(exc)) from exc
        return value


class CollectionCheckSuggestionAPIRead(ResponseBase):
    suggestion: Optional[str] = None


class CollectionLockedAPIRead(ResponseBase):
    """How many of the Collection's episodes the Source refused for lack of an access."""
    count: int


class CollectionFileRenameAPIRequest(RequestBase):
    """Select one Local Media Profile, or every profile with existing episode media."""

    local_media_profile_id: Optional[int] = Field(default=None, gt=0)
    season_folders: bool = True
    """Files move to their season's folder too. Without it each file keeps its folder and only its name changes.
    With it, a video with files also moves to the playlist season it belongs in now first."""


class CollectionDownloadAllAPIRequest(RequestBase):
    """Queue indexed episodes for one Local Media Profile and a collection-specific filter."""

    local_media_profile_id: int = Field(gt=0)
    season_ids: list[int] = Field(default_factory=list)
    episode_types: list[EpisodeTagKey] = Field(default_factory=list)
    download_days_in_past: int = Field(default=0, ge=0)
    download_episode_count: int = Field(default=0, ge=0)
    download_starting_from: date | None = None

    @model_validator(mode="after")
    def validate_podcast_limits(self):
        if self.download_days_in_past and self.download_episode_count:
            raise ValueError("Choose either a date limit or an episode-count limit, not both")
        if self.download_starting_from is not None and (
            self.download_days_in_past or self.download_episode_count
        ):
            raise ValueError("Download starting from can only be used when Limit by is set to No limits")
        return self


class _CollectionDownloadMaintenanceAPIRequest(RequestBase):
    """Scope collection download maintenance to selected profiles and older episodes."""

    local_media_profile_id: Optional[int] = Field(default=None, gt=0)
    delete_older_than: Literal["all", "days", "latest_downloads"] = "all"
    delete_older_than_days: int | None = Field(default=None, ge=1)
    delete_older_than_latest_downloads: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_older_than_limit(self):
        if self.delete_older_than == "all":
            if self.delete_older_than_days is not None or self.delete_older_than_latest_downloads is not None:
                raise ValueError("Delete all does not accept an age limit")
        elif self.delete_older_than == "days":
            if self.delete_older_than_days is None or self.delete_older_than_latest_downloads is not None:
                raise ValueError("Delete older than days requires a number of days")
        else:
            if self.delete_older_than_latest_downloads is None or self.delete_older_than_days is not None:
                raise ValueError("Delete older than latest downloads requires a number of downloads")
        return self


class CollectionDeleteDownloadsAPIRequest(_CollectionDownloadMaintenanceAPIRequest):
    """Select downloads to delete by Local Media Profile."""


class CollectionRedownloadEpisodesAPIRequest(_CollectionDownloadMaintenanceAPIRequest):
    """Select downloads to delete and re-download by Local Media Profile."""


# ---------- Lenient output (read) ----------
class _CollectionAPIBaseOut(SourcedResponse, CustomMetadataResponseBase):
    """Fields for responses: no validators, no constraints."""

    model_config = response_model_config(nested_source="collection")

    custom_metadata: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "custom_metadata",
            "meta_items",
            AliasPath("collection", "meta_items"),
        ),
    )
    id: int
    uuid: str
    slug: str
    membership_level: Optional[str] = None
    type: Union[CollectionType, str]
    episode_identifier: Union[EpisodeIdentifier, str]
    episode_order: EpisodeOrder
    author_slug: str
    title: str
    description: Optional[str] = None
    sharing_url: Optional[str] = None
    """None for a collection that only holds what its link seasons have, and has no link of its own."""
    outside_videos: Optional[OutsideVideos] = None
    """Whether the collection adds videos from its link seasons that its own link lacks, or holds only those."""
    kind: Optional[CollectionKind] = None
    """What its own link is: a channel, which takes the channel's lists and can be in a creator, one list, or none, for
    a custom collection. None for a collection that is not in the Library yet, such as one that is looked up to be
    added."""
    list_type: Optional[str] = None
    """For a collection of one list, the key of its Site's type of list it is, such as album or playlist on
    SoundCloud, where its link doesn't tell; None where the Site has one type of list or it is not known."""
    site: Optional[SiteAPIRead] = None
    """The website the collection is on; None until the background migration finds it for an older collection."""
    author_name: str
    author_headshot_path: Optional[str] = None
    background_image_path: Optional[str] = None
    logo_image_path: Optional[str] = None
    thumbnail_landscape_path: Optional[str] = None
    thumbnail_portrait_path: Optional[str] = None
    thumbnail_square_path: Optional[str] = None
    link_image_path: Optional[str] = None
    """For a collection without a link of its own, the picture of its first link season that has one."""
    link_site_keys: list[Optional[str]] = Field(default_factory=list, exclude=True)
    ytdlp_options: str = ""
    genre: Optional[str] = None
    content_rating: Optional[str] = None
    cookies_mode: CookiesMode = CookiesMode.AUTOMATIC
    split_chapters: bool = False
    cookies_needed_until: Optional[datetime] = None
    check_frequency: CheckFrequency = CheckFrequency.DEFAULT
    check_cron: Optional[str] = None
    creator_slug: Optional[str] = Field(
        default=None, validation_alias=AliasChoices(AliasPath("creator", "slug"), AliasPath("collection", "creator", "slug")),
    )
    """The creator the collection belongs to, when it was added with one."""
    creator_title: Optional[str] = Field(
        default=None, validation_alias=AliasChoices(AliasPath("creator", "title"), AliasPath("collection", "creator", "title")),
    )
    creator_avatar_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(AliasPath("creator", "avatar_path"), AliasPath("collection", "creator", "avatar_path")),
    )
    """The picture of the creator, shown beside their name."""

    @computed_field
    @property
    def creator_names(self) -> NamesAPIRead:
        """What the collection calls the creator behind it: its Site's word, such as host, or artist in a Music
        collection; VODLoft's own while the Site is not known yet."""
        site = site_of(self.site.key) if self.site is not None else Site("", "")
        return NamesAPIRead.model_validate(collection_contract(self.type).creator_names_on(site))

    @computed_field
    @property
    def allows_unplayable_formats(self) -> bool:
        """Its own yt-dlp options allow unplayable formats, so its media protected by DRM can still be tried."""
        return options_allow_unplayable_formats(self.source_key, self.ytdlp_options)

    @computed_field
    @property
    def can_join_creator(self) -> bool:
        """Whether Add to creator is offered: a collection with a link on a Site with creators, a channel or a list,
        or one without a link of its own, which joins a creator in the Library by hand."""
        from backend.services.creators import site_takes_creators

        if self.sharing_url is None:
            return True
        return self.site is not None and site_takes_creators(self.source_key, self.site.key)

    @computed_field
    @property
    def season_names(self) -> Optional[NamesAPIRead]:
        """What the collection's Site calls its seasons, such as playlists in a YouTube channel collection; None where
        its type's own word stands, as the collection contracts give it."""
        from backend.services.sites import NO_SITE, site_season_names

        if self.site is None and self.kind != CollectionKind.CUSTOM:
            return None
        names = site_season_names(site_of(self.site.key) if self.site is not None else NO_SITE, self.type, self.kind)
        return NamesAPIRead.model_validate(names) if names is not None else None


    @computed_field
    @property
    def kind_name(self) -> Optional[str]:
        """What the collection is on its Site, in the Site's words, as a creator is named: "YouTube channel",
        "YouTube playlist" or "The Daily Wire show". A custom collection is named for its lists: "YouTube playlists"
        when they are on one Site, "Custom collection" otherwise. None while its kind is not known yet, and while the
        Site of a collection with a link is not."""
        if self.kind == CollectionKind.CUSTOM:
            # A custom collection is what its lists are when they share a Site: "YouTube playlists".
            keys = set(self.link_site_keys)
            if len(keys) == 1 and (key := keys.pop()) is not None:
                site = site_of(key)
                return f"{site.name} {site.list_collection_names.plural}"
            return CUSTOM_COLLECTION_NAMES.singular.capitalize()
        if self.site is None or self.kind is None:
            return None
        site = site_of(self.site.key)
        names = site.channel_collection_names if self.kind == CollectionKind.CHANNEL.value else site.list_collection_names_of(self.list_type)
        return f"{site.name} {names.singular}"


class CollectionAPIRead(_CollectionAPIBaseOut):
    """Response body for a collection."""
    created_at: datetime
    updated_at: datetime
    added_by: Optional[str] = None
    """Who added it, with user accounts on."""
    healthy: bool = True
    """Whether the collection needs nothing from the user, as it stored it."""
    health_issues: dict[HealthIssueKind, int] = Field(default_factory=dict)
    """What it needs the user for, by kind of issue, with how many things each concerns."""


class CollectionAPIReadView(CollectionAPIRead):
    """Response body for a collection view."""

    episode_count: int = Field(default=0)
    years: str = Field(default="")
    first_published_date: Optional[datetime] = None
    """When its oldest episode came out, for the Library's Release date order."""
    open_count: int
    """How often the Collection's page was opened, for the Library's Often used order."""
    last_opened_at: Optional[datetime] = None
    """When the Collection's page was last opened, for the Library's Recently used order."""


class CollectionSyncLogEntryAPIRead(ResponseBase):
    """One scan that looked at the Collection."""

    id: int
    kind: Literal["full_scan", "quick_check"]
    status: str
    ran_at: Optional[datetime]
    episodes_found: Optional[int]


class CollectionSyncLogAPIRead(ResponseBase):
    items: list[CollectionSyncLogEntryAPIRead]
    total: int


class CollectionIdentificationChangeAPIRequest(RequestBase):
    """Number the collection's episodes another way."""

    episode_identifier: EpisodeIdentifier
    episode_order: Optional[EpisodeOrder] = None
    """The order the collection lists its episodes in from now on; left out, it keeps its own."""


class CollectionIdentificationChangeItemAPIRead(ResponseBase):
    """One episode that gets a new number."""

    title: str
    before: str
    after: str


class CollectionIdentificationProfileFilesAPIRead(ResponseBase):
    name: str
    files_renamed: int
    metadata_rewritten: int


class CollectionIdentificationDownloadProfileAPIRead(ResponseBase):
    name: str
    removed: int
    """Downloads on disk the profile's cleanup would delete, which it would not have before."""
    no_longer_wanted: int
    """Other downloads on disk the profile's filters would leave out; they stay until someone deletes them."""
    newly_wanted: int


class CollectionIdentificationPreviewAPIRead(ResponseBase):
    """What changing the collection's episode identification would do."""

    episode_identifier: EpisodeIdentifier = Field(validation_alias="identification")
    episodes: int
    episodes_renumbered: int
    changes: list[CollectionIdentificationChangeItemAPIRead]
    """Every episode that gets a new number, newest first."""
    become_auxiliary: int
    profiles: list[CollectionIdentificationProfileFilesAPIRead]
    download_profiles: list[CollectionIdentificationDownloadProfileAPIRead]
    busy: Optional[str] = None
    """Why the change can't start now."""


class CollectionMetadataRewriteAPIRequest(RequestBase):
    """Select one Local Media Profile, or every profile with downloaded files that keeps metadata."""

    local_media_profile_id: Optional[int] = Field(default=None, gt=0)


class CollectionBulkChangesIn(BulkChangesIn):
    """The settings the Library's bulk edit gives every chosen Collection; the others keep their own."""

    check_frequency: Optional[CheckFrequency] = None
    episode_order: Optional[EpisodeOrder] = None
    split_chapters: Optional[bool] = None
    cookies_mode: Optional[CookiesMode] = None
    genre: Optional[str] = Field(default=None, max_length=200)
    """Empty removes the genre."""
    content_rating: Optional[str] = Field(default=None, max_length=50)
    """Empty removes the content rating."""

    link_seasons: Optional[LinkSeasons] = None
    """Whether each Collection takes its channel's lists and the links added to it, as the Seasons dialog's switch
    sets it; only Collections of a whole channel on a Site whose lists can be seasons have it."""
    feeds: Optional[dict[str, SourceRole]] = Field(default=None, max_length=50)
    """What some feeds of the Collections' channels become, by the key of the feed (``CollectionBulkFeedRead.key``).
    A Collection takes only the feeds its channel has; the others keep what they are."""

    loose_videos: Optional[LooseVideos] = None
    """Whether what is part of each Collection goes in one season or a season per year, as the Seasons dialog sets
    it; only Collections whose Source lists their videos have it. Whether that one season also holds what has a season
    of its own stays as each Collection has it."""

    nullable: ClassVar[frozenset[str]] = frozenset({"genre", "content_rating"})

    @field_validator("loose_videos")
    @classmethod
    def _grouping(cls, value: Optional[LooseVideos]) -> Optional[LooseVideos]:
        if value == LooseVideos.EVERYTHING:
            raise ValueError("Choose one season or a season per year")
        return value

    @field_validator("feeds")
    @classmethod
    def _some_feed(cls, value: Optional[dict[str, SourceRole]]) -> Optional[dict[str, SourceRole]]:
        if value is not None and not value:
            raise ValueError("Choose what a feed becomes")
        return value

    @field_validator("check_frequency")
    @classmethod
    def _not_own(cls, value: Optional[CheckFrequency]) -> Optional[CheckFrequency]:
        if value == CheckFrequency.OWN:
            raise ValueError("Give a Collection its own schedule on its Edit page")
        return value

    @field_validator("genre", "content_rating")
    @classmethod
    def _strip_metadata(cls, value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None


class CollectionBulkChangeIn(BulkChangeIn[CollectionBulkChangesIn]):
    keep_numbers: list[int] = Field(default_factory=list, max_length=10_000)
    """The Collections, by id, that keep their episodes' numbers when their downloads move into other seasons, as
    the review let the user choose; the others number them again, as the Seasons dialog does by default."""
    saving_token: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    """The review's token, by which it follows how far each collection's save is, as the Seasons dialog does."""


class CollectionBulkFeedRead(ResponseBase):
    """One feed of the chosen Collections' channels, such as YouTube's Shorts, and what it is in each now."""

    key: str
    """The feed by its Site and its ref, as the changes name it."""
    names: NamesAPIRead
    """What the Site calls the feed's videos; the feed is named after them."""
    site: str
    """The name of its Site, such as YouTube."""
    summary: BulkFieldSummaryRead
    """What the feed is now in each Collection whose channel has it: season, part or off."""


class CollectionBulkSummaryRead(BulkSummaryRead):
    feeds: list[CollectionBulkFeedRead] = Field(default_factory=list)
    list_names: Optional[NamesAPIRead] = None
    """What the lists of the Collections that can take them are called, joined, such as playlists."""
    loose_videos: Optional[BulkFieldSummaryRead] = None
    """Whether what is part of each Collection that has the setting goes in one season or a season per year now."""
    season_names: Optional[NamesAPIRead] = None
    """What the seasons of the Collections that have that setting are called, joined, such as seasons or albums."""

