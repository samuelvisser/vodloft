"""The settings each Site can have of its own, and the system defaults they fall back to.

Every setting is one ``SiteSetting``. ``SITE_SETTINGS`` says for each whether it has a system default
the user can change, and where that lives in config.yml. A Site's own values live under
``siteSettings`` in config.yml, by Site key:

* a setting left out follows the Site's preset, which its Source declares, or else the system default;
* ``default`` follows the system default, even when the Site has a preset;
* any other value is the Site's own.

A setting without a system default shows only on Sites that offer it, and starts with the Site's
preset or else its built-in value. Which settings a Site shows, and its presets, are part of its
Source's contract (``sources.contract.SiteSettings``).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal, Optional, Union

from pydantic import Field, field_validator

from config.settings.base import SubmodelBase
from config.settings.submodels import SITE_REFRESH_OFF, normalize_metadata_refresh_intervals

if TYPE_CHECKING:
    from config.settings.settings import AppSettings


class UpgradeImprovement(StrEnum):
    """What the upgrade check can count as a better version of a download."""

    RESOLUTION = "resolution"
    SPONSORBLOCK = "sponsorblock"
    SUBTITLES = "subtitles"
    CODEC = "codec"
    LENGTH = "length"
    """The episode got longer or shorter, such as a live stream cut down after it ended."""


class UpgradeRepeat(StrEnum):
    """How often the upgrade check looks at a download again."""
    ONCE = "once"
    TWICE = "twice"
    """Once more, 30 days after the first check."""
    EVERY = "every"
    """Every "check after" days, up to three times."""


class AutoSubtitles(StrEnum):
    """Whether a Download Profile downloads the subtitles a site generated itself."""
    NEVER = "never"
    FALLBACK = "fallback"
    ALWAYS = "always"


class SponsorBlockAction(StrEnum):
    """What a download does with one type of SponsorBlock segment."""

    KEEP = "keep"
    CHAPTER = "chapter"
    """A named chapter a player can skip."""
    CUT = "cut"
    """Removed from the file for good."""


class SponsorBlockCategory(StrEnum):
    """SponsorBlock's segment types, in the order they are shown."""

    SPONSOR = "sponsor"
    SELFPROMO = "selfpromo"
    INTERACTION = "interaction"
    INTRO = "intro"
    OUTRO = "outro"
    PREVIEW = "preview"
    FILLER = "filler"
    HOOK = "hook"
    """The greeting and teaser at the start of a video."""
    MUSIC_OFFTOPIC = "music_offtopic"
    POI_HIGHLIGHT = "poi_highlight"
    """The one moment viewers mark as where the video gets going: a point in time, never cut out."""
    CHAPTER = "chapter"
    """Chapter titles viewers wrote for a video. They name parts of it, so they are never cut out."""


CHAPTER_ONLY_SPONSORBLOCK_CATEGORIES = frozenset({SponsorBlockCategory.POI_HIGHLIGHT.value, SponsorBlockCategory.CHAPTER.value})
"""Segment types that can only be kept or made a chapter: they mark a moment or name a part, nothing to cut out."""


DEFAULT_SPONSORBLOCK_SEGMENTS: dict[str, str] = {
    SponsorBlockCategory.SPONSOR.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.SELFPROMO.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.INTERACTION.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.INTRO.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.OUTRO.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.PREVIEW.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.FILLER.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.HOOK.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.MUSIC_OFFTOPIC.value: SponsorBlockAction.KEEP.value,
    SponsorBlockCategory.POI_HIGHLIGHT.value: SponsorBlockAction.CHAPTER.value,
    SponsorBlockCategory.CHAPTER.value: SponsorBlockAction.KEEP.value,
}
"""Chapters of sponsors, intros, outros and the highlight, and everything else kept."""


def sponsorblock_changes_anything(segments: Mapping[str, str]) -> bool:
    """Whether the segment choices mark or cut out anything. Keeping every type does nothing, the same as off."""
    return any(action != SponsorBlockAction.KEEP.value for action in segments.values())


def check_sponsorblock_segments(value: Mapping[str, str]) -> None:
    """Refuse a choice to cut out a segment type that can only be a chapter."""
    refused = sorted(
        category for category in CHAPTER_ONLY_SPONSORBLOCK_CATEGORIES if value.get(category) == SponsorBlockAction.CUT.value
    )
    if refused:
        raise ValueError(f"SponsorBlock can't cut out {', '.join(refused)}: choose Keep or Chapter")

DEFAULT_UPGRADE_IMPROVEMENTS = (UpgradeImprovement.RESOLUTION.value,)

PENDING_MINIMUM_MINUTES = 2
"""The pending check sweep runs every two minutes, so no lookup time is shorter."""

SITE_SETTING_DEFAULT = "default"
"""A Site's value for a setting that follows the system default."""


class SiteSettingGroup(StrEnum):
    """Where a setting is used: in Automations, on Download Profiles, or on Local Media Profiles."""
    SCHEDULING = "scheduling"
    DOWNLOAD_PROFILE = "downloadProfile"
    LOCAL_MEDIA_PROFILE = "localMediaProfile"


class SiteSetting(StrEnum):
    """A setting a Site can have of its own, by its key under ``siteSettings`` in config.yml."""
    METADATA_REFRESH = "metadataRefresh"
    UPCOMING_AND_LIVE = "upcomingAndLive"
    LOOKUP_MINUTES = "lookupMinutes"
    DOWNLOAD_WITH_COUNTDOWN = "downloadWithCountdown"
    UPGRADE_CHECK = "upgradeCheck"
    UPGRADE_AFTER_DAYS = "upgradeAfterDays"
    UPGRADE_REPEAT = "upgradeRepeat"
    UPGRADE_IMPROVEMENTS = "upgradeImprovements"
    UPGRADE_LENGTH_MINUTES = "upgradeLengthMinutes"
    AUTO_SUBTITLES = "autoSubtitles"
    SPONSORBLOCK = "sponsorblock"
    SPONSORBLOCK_SEGMENTS = "sponsorblockSegments"


class LookupMinutes(SubmodelBase):
    """Minutes between lookups of upcoming and live episodes."""
    upcoming: int = Field(ge=PENDING_MINIMUM_MINUTES, le=24 * 60)
    starting: int = Field(ge=PENDING_MINIMUM_MINUTES, le=60)
    """From 15 minutes before an episode starts until an hour after."""
    live: int = Field(ge=PENDING_MINIMUM_MINUTES, le=60)
    """While an episode is live or still being finished."""


class DownloadProfileDefaults(SubmodelBase):
    """What a new Download Profile starts with, for Sites that follow the system default."""
    upgrade_check: bool = Field(default=True, description="Download again when a better version is out")
    upgrade_after_days: int = Field(default=7, ge=1, le=365, description="Days after downloading that the upgrade check first looks")
    upgrade_repeat: UpgradeRepeat = Field(default=UpgradeRepeat.ONCE, description="How often the upgrade check looks again")
    upgrade_improvements: list[UpgradeImprovement] = Field(
        default_factory=lambda: [UpgradeImprovement(value) for value in DEFAULT_UPGRADE_IMPROVEMENTS],
        description="What counts as a better version",
    )
    upgrade_length_minutes: int = Field(
        default=5, ge=1, le=600, description="How many minutes longer or shorter counts as a different length",
    )
    auto_subtitles: AutoSubtitles = Field(
        default=AutoSubtitles.FALLBACK, description="Use the subtitles a site generates itself: never, fallback or always",
    )

    @field_validator("upgrade_improvements")
    @classmethod
    def _unique_improvements(cls, value: list) -> list:
        return list(dict.fromkeys(value))


def _metadata_refresh(value: str) -> str:
    return SITE_REFRESH_OFF if value.strip().lower() == SITE_REFRESH_OFF else normalize_metadata_refresh_intervals(value)


Default = Literal["default"]


class SiteSettingValues(SubmodelBase):
    """One Site's own settings. A setting left out (None) follows the Site's preset, then the system default."""

    metadata_refresh: Optional[str] = Field(
        default=None, description="Offsets after publication for refreshing the metadata of the Site's items, off, or default",
    )
    upcoming_and_live: Optional[Union[Default, bool]] = None
    lookup_minutes: Optional[Union[Default, LookupMinutes]] = None
    download_with_countdown: Optional[bool] = None
    upgrade_check: Optional[Union[Default, bool]] = None
    upgrade_after_days: Optional[Union[Default, Annotated[int, Field(ge=1, le=365)]]] = None
    upgrade_repeat: Optional[Union[Default, UpgradeRepeat]] = None
    upgrade_improvements: Optional[Union[Default, list[UpgradeImprovement]]] = None
    upgrade_length_minutes: Optional[Union[Default, Annotated[int, Field(ge=1, le=600)]]] = None
    auto_subtitles: Optional[Union[Default, AutoSubtitles]] = None
    sponsorblock: Optional[bool] = None
    sponsorblock_segments: Optional[dict[SponsorBlockCategory, SponsorBlockAction]] = None

    @field_validator("metadata_refresh")
    @classmethod
    def _validate_metadata_refresh(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value.strip().lower() == SITE_SETTING_DEFAULT:
            return None if value is None else SITE_SETTING_DEFAULT
        return _metadata_refresh(value)

    @field_validator("upgrade_improvements")
    @classmethod
    def _unique_improvements(cls, value):
        return list(dict.fromkeys(value)) if isinstance(value, list) else value

    @field_validator("sponsorblock_segments")
    @classmethod
    def _segment_types(cls, value):
        if value is None:
            return value
        check_sponsorblock_segments(value)
        # A type the file leaves out follows VODLoft's default.
        return {**DEFAULT_SPONSORBLOCK_SEGMENTS, **value}

    def own(self, key: SiteSetting) -> Any:
        """The Site's value for the setting: None when left out, ``default`` to follow the system default."""
        return getattr(self, field_name(key))


@dataclass(frozen=True)
class SiteSettingSpec:
    """What VODLoft knows about one setting a Site can have of its own."""

    key: SiteSetting
    group: SiteSettingGroup
    system: Optional[Callable[["AppSettings"], Any]] = None
    """The system default, read from the settings. A setting without one is a Site's own only."""
    builtin: Any = None
    """The value of a setting without a system default on a Site that gives no preset."""

    @property
    def has_system_default(self) -> bool:
        return self.system is not None

    def system_value(self, settings: "AppSettings") -> Any:
        return self.system(settings) if self.system is not None else self.builtin


def _lookup_minutes(settings: "AppSettings") -> LookupMinutes:
    schedule = settings.new_episode_schedule
    return LookupMinutes(
        upcoming=schedule.pending_upcoming_minutes, starting=schedule.pending_starting_minutes,
        live=schedule.pending_live_minutes,
    )


def _profile_default(name: str) -> Callable[["AppSettings"], Any]:
    return lambda settings: getattr(settings.download_profile_defaults, name)


SITE_SETTINGS: Mapping[SiteSetting, SiteSettingSpec] = {spec.key: spec for spec in (
    SiteSettingSpec(
        SiteSetting.METADATA_REFRESH, SiteSettingGroup.SCHEDULING,
        lambda settings: settings.new_episode_schedule.metadata_refresh_intervals,
    ),
    SiteSettingSpec(
        SiteSetting.UPCOMING_AND_LIVE, SiteSettingGroup.SCHEDULING,
        lambda settings: settings.new_episode_schedule.upcoming_and_live,
    ),
    SiteSettingSpec(SiteSetting.LOOKUP_MINUTES, SiteSettingGroup.SCHEDULING, _lookup_minutes),
    SiteSettingSpec(SiteSetting.DOWNLOAD_WITH_COUNTDOWN, SiteSettingGroup.DOWNLOAD_PROFILE, builtin=False),
    SiteSettingSpec(SiteSetting.UPGRADE_CHECK, SiteSettingGroup.DOWNLOAD_PROFILE, _profile_default("upgrade_check")),
    SiteSettingSpec(SiteSetting.UPGRADE_AFTER_DAYS, SiteSettingGroup.DOWNLOAD_PROFILE, _profile_default("upgrade_after_days")),
    SiteSettingSpec(SiteSetting.UPGRADE_REPEAT, SiteSettingGroup.DOWNLOAD_PROFILE, _profile_default("upgrade_repeat")),
    SiteSettingSpec(
        SiteSetting.UPGRADE_IMPROVEMENTS, SiteSettingGroup.DOWNLOAD_PROFILE, _profile_default("upgrade_improvements"),
    ),
    SiteSettingSpec(
        SiteSetting.UPGRADE_LENGTH_MINUTES, SiteSettingGroup.DOWNLOAD_PROFILE, _profile_default("upgrade_length_minutes"),
    ),
    SiteSettingSpec(SiteSetting.AUTO_SUBTITLES, SiteSettingGroup.LOCAL_MEDIA_PROFILE, _profile_default("auto_subtitles")),
    SiteSettingSpec(SiteSetting.SPONSORBLOCK, SiteSettingGroup.LOCAL_MEDIA_PROFILE, builtin=True),
    SiteSettingSpec(
        SiteSetting.SPONSORBLOCK_SEGMENTS, SiteSettingGroup.LOCAL_MEDIA_PROFILE, builtin=DEFAULT_SPONSORBLOCK_SEGMENTS,
    ),
)}


def field_name(key: SiteSetting) -> str:
    """The setting's field in ``SiteSettingValues``, such as ``metadata_refresh``."""
    return "".join(f"_{char.lower()}" if char.isupper() else char for char in key.value)


class SettingOrigin(StrEnum):
    """Where the value a Site follows for a setting comes from."""
    OWN = "own"
    PRESET = "preset"
    SYSTEM = "system"


def resolve_site_setting(
    settings: "AppSettings", site_key: Optional[str], key: SiteSetting, presets: Mapping[SiteSetting, Any],
) -> tuple[Any, SettingOrigin]:
    """The value a Site follows for the setting, and where it comes from."""
    spec = SITE_SETTINGS[key]
    own = settings.site_settings[site_key].own(key) if site_key in settings.site_settings else None
    if own is not None and own != SITE_SETTING_DEFAULT:
        return own, SettingOrigin.OWN
    if own is None and key in presets:
        return presets[key], SettingOrigin.PRESET
    return spec.system_value(settings), SettingOrigin.SYSTEM
