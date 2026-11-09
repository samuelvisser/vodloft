"""The settings each Site follows: its own from config.yml, its preset, or the system default.

Which settings there are, and which have a system default, is ``config.settings.site_settings``.
Which of them a Site shows, and what it starts with, is its Source's contract (``sources.SiteSettings``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from backend.db.models import Collection, Site as SiteRecord, Video
from config import get_settings
from config.settings.site_settings import (
    SITE_SETTINGS,
    SettingOrigin,
    SiteSetting,
    SiteSettingGroup,
    UpgradeImprovement,
    resolve_site_setting,
)
from sources import Site, site_of

_UPGRADE_SETTINGS = frozenset({
    SiteSetting.UPGRADE_CHECK, SiteSetting.UPGRADE_AFTER_DAYS, SiteSetting.UPGRADE_REPEAT,
    SiteSetting.UPGRADE_IMPROVEMENTS, SiteSetting.UPGRADE_LENGTH_MINUTES,
})

_PROFILE_FIELDS = {
    SiteSetting.DOWNLOAD_WITH_COUNTDOWN: "download_with_countdown",
    SiteSetting.UPGRADE_CHECK: "upgrade_check",
    SiteSetting.UPGRADE_AFTER_DAYS: "upgrade_after_days",
    SiteSetting.UPGRADE_REPEAT: "upgrade_repeat",
    SiteSetting.UPGRADE_IMPROVEMENTS: "upgrade_improvements",
    SiteSetting.UPGRADE_LENGTH_MINUTES: "upgrade_length_minutes",
    SiteSetting.AUTO_SUBTITLES: "auto_subtitles",
    SiteSetting.SPONSORBLOCK: "sponsorblock_enabled",
    SiteSetting.SPONSORBLOCK_SEGMENTS: "sponsorblock_segments",
}
"""The Download Profile field each download profile setting gives its starting value."""


def site_setting(site_key: Optional[str], key: SiteSetting) -> Any:
    """The value the Site with the key follows; an item without a Site follows the system default."""
    return site_setting_of(site_of(site_key) if site_key else None, key)[0]


def site_setting_of(site: Optional[Site], key: SiteSetting) -> tuple[Any, SettingOrigin]:
    """The value the Site follows, and where it comes from."""
    presets = site.settings.presets if site is not None else {}
    return resolve_site_setting(get_settings(), site.key if site is not None else None, key, presets)


def offers(site: Site, key: SiteSetting, *, refreshes: bool = True, follows_pending: bool = True) -> bool:
    """Whether the setting means anything for the Site: the Site shows it, and what it needs is there.

    ``refreshes`` and ``follows_pending`` tell whether a Source the Site's items come through looks
    them up again, and follows their upcoming and live episodes.
    """
    if not site.settings.offers(key):
        return False
    improvements = site.upgrade_checks.improvements
    if key is SiteSetting.METADATA_REFRESH:
        return refreshes
    if key in (SiteSetting.UPCOMING_AND_LIVE, SiteSetting.LOOKUP_MINUTES):
        return follows_pending
    if key is SiteSetting.UPGRADE_LENGTH_MINUTES:
        return UpgradeImprovement.LENGTH in improvements
    if key in _UPGRADE_SETTINGS:
        return bool(improvements)
    return True


def offered_settings(
    site: Site, group: Optional[SiteSettingGroup] = None, *, refreshes: bool = True, follows_pending: bool = True,
) -> list[SiteSetting]:
    return [
        key for key, spec in SITE_SETTINGS.items()
        if (group is None or spec.group is group)
        and offers(site, key, refreshes=refreshes, follows_pending=follows_pending)
    ]


def download_profile_defaults(site: Site) -> dict[str, Any]:
    """What a new Download Profile on the Site starts with, by Download Profile field."""
    values = {field: site_setting_of(site, key)[0] for key, field in _PROFILE_FIELDS.items()}
    # Only what the Site can check, in the order it shows them.
    chosen = {str(improvement) for improvement in values["upgrade_improvements"]}
    values["upgrade_improvements"] = [
        improvement.value for improvement in site.upgrade_checks.improvements if improvement.value in chosen
    ]
    # With nothing that counts as better by default, the check starts off.
    values["upgrade_check"] = bool(values["upgrade_check"]) and bool(values["upgrade_improvements"])
    if not site.settings.offers(SiteSetting.DOWNLOAD_WITH_COUNTDOWN):
        values["download_with_countdown"] = False
    return values


@dataclass(frozen=True)
class OfferedSetting:
    """A setting a Site shows in Settings, and what it starts with there."""

    key: SiteSetting
    start: Any
    """The Site's preset; for a setting without a system default, its built-in value when it has no preset.
    None for a setting that starts out following the system default."""
    preset: bool
    """``start`` is the Site's own preset."""


@dataclass(frozen=True)
class SiteSettingsListing:
    """A Site VODLoft has seen, as Settings lists it."""

    record: SiteRecord
    site: Site
    settings: list[OfferedSetting]

    @property
    def upgrade_improvements(self) -> tuple[UpgradeImprovement, ...]:
        return self.site.upgrade_checks.improvements


def _offered_setting(site: Site, key: SiteSetting) -> OfferedSetting:
    if key in site.settings.presets:
        return OfferedSetting(key, site.settings.presets[key], True)
    spec = SITE_SETTINGS[key]
    return OfferedSetting(key, None if spec.has_system_default else spec.builtin, False)


def _sources_of_sites(s: Session) -> dict[str, tuple[bool, bool]]:
    """Every Site with collections or videos, and whether a Source looks its items up again and
    follows its upcoming and live episodes."""
    # Both read their settings through this module.
    from backend.services.metadata_refresh import refreshes_metadata
    from backend.services.pending_episodes import follows_pending

    rows = s.execute(union(
        select(Collection.site_key, Collection.source_key).where(Collection.site_key.is_not(None)),
        select(Video.site_key, Video.source_key).where(Video.site_key.is_not(None)),
    )).all()
    found: dict[str, tuple[bool, bool]] = {}
    for site_key, source_key in rows:
        refreshes, follows = found.get(site_key, (False, False))
        found[site_key] = (refreshes or refreshes_metadata(source_key), follows or follows_pending(source_key))
    return found


def list_sites_settings(s: Session) -> list[SiteSettingsListing]:
    """Every Site VODLoft has seen, with the settings it shows. A Site without collections or videos yet
    shows every setting it offers."""
    found = _sources_of_sites(s)
    listings = []
    for record in s.scalars(select(SiteRecord).order_by(SiteRecord.name)).all():
        site = site_of(record.key)
        refreshes, follows = found.get(record.key, (True, True))
        keys = offered_settings(site, refreshes=refreshes, follows_pending=follows)
        listings.append(SiteSettingsListing(record, site, [_offered_setting(site, key) for key in keys]))
    return listings
