from __future__ import annotations

from typing import Any

from backend.api.models.base import ResponseBase, response_model_config
from config.settings.site_settings import SiteSetting, SiteSettingGroup, UpgradeImprovement


class SiteSettingSpecAPIRead(ResponseBase):
    """A setting a Site can have of its own."""

    key: SiteSetting
    group: SiteSettingGroup
    has_system_default: bool
    """Without one, the setting shows only on Sites that offer it, and has no Default to follow."""


class OfferedSettingAPIRead(ResponseBase):
    """A setting a Site shows, and what it starts with when the Site has no value of its own."""

    key: SiteSetting
    start: Any = None
    """The Site's preset or, for a setting without a system default, its built-in value; None follows the system default."""
    preset: bool


class SiteSettingsAPIRead(ResponseBase):
    """A Site VODLoft has seen, read from a ``SiteSettingsListing``. Its own values are part of the
    settings, under ``siteSettings``."""

    model_config = response_model_config(nested_source="record")

    key: str
    name: str
    domains: list[str]
    settings: list[OfferedSettingAPIRead]
    upgrade_improvements: list[UpgradeImprovement]
    """What the upgrade check can count as better on the Site, in the order it shows them."""


class SitesSettingsAPIRead(ResponseBase):
    specs: list[SiteSettingSpecAPIRead]
    sites: list[SiteSettingsAPIRead]
