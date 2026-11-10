"""Each Site's settings: its own value from config.yml, its preset, or the system default."""
from __future__ import annotations

import pytest

from config.registry import get_settings, replace_settings
from config.settings.site_settings import (
    SITE_SETTINGS,
    SettingOrigin,
    SiteSetting,
    SiteSettingValues,
    resolve_site_setting,
)
from sources import all_sources, site_of


@pytest.fixture
def site_settings():
    """Give Sites settings of their own, as under siteSettings in config.yml."""
    original = get_settings()

    def apply(**own: dict):
        replace_settings(original.model_copy(update={
            "site_settings": {key: SiteSettingValues(**values) for key, values in own.items()},
        }))

    yield apply
    replace_settings(original)


def _resolve(site_key: str, key: SiteSetting):
    return resolve_site_setting(get_settings(), site_key, key, site_of(site_key).settings.presets)


def test_a_site_follows_its_own_value_then_its_preset_then_the_system(site_settings):
    system_days = get_settings().download_profile_defaults.upgrade_after_days

    # The Daily Wire's preset checks after 3 days; YouTube has none, so it follows the system default.
    assert _resolve("dailywire", SiteSetting.UPGRADE_AFTER_DAYS) == (3, SettingOrigin.PRESET)
    assert _resolve("youtube", SiteSetting.UPGRADE_AFTER_DAYS) == (system_days, SettingOrigin.SYSTEM)

    # Default always means the system default, even on a Site with a preset.
    site_settings(dailywire={"upgrade_after_days": "default"}, youtube={"upgrade_after_days": 10})
    assert _resolve("dailywire", SiteSetting.UPGRADE_AFTER_DAYS) == (system_days, SettingOrigin.SYSTEM)
    assert _resolve("youtube", SiteSetting.UPGRADE_AFTER_DAYS) == (10, SettingOrigin.OWN)


def test_a_setting_without_a_system_default_starts_on_its_built_in_value(site_settings):
    assert _resolve("youtube", SiteSetting.SPONSORBLOCK) == (True, SettingOrigin.SYSTEM)
    site_settings(youtube={"sponsorblock": False})
    assert _resolve("youtube", SiteSetting.SPONSORBLOCK) == (False, SettingOrigin.OWN)
    with pytest.raises(ValueError):
        SiteSettingValues(sponsorblock="default")


def test_every_site_contract_only_presets_what_it_shows_with_valid_values():
    for source in all_sources():
        for site in source.sites:
            for key, preset in site.settings.presets.items():
                assert site.settings.offers(key), f"{site.key} presets {key} it does not show"
                # A preset is a value a user could give the Site in config.yml.
                assert SiteSettingValues.model_validate({key.value: preset}).own(key) is not None
            # A Site shows only settings without a system default, and hides only ones with one.
            assert not any(SITE_SETTINGS[key].has_system_default for key in site.settings.shows)
            assert all(SITE_SETTINGS[key].has_system_default for key in site.settings.hides)
            # Only a Site with subtitles has auto-generated ones.
            if site.settings.offers(SiteSetting.AUTO_SUBTITLES):
                assert site.downloads.subtitles, f"{site.key} offers auto-generated subtitles without subtitles"


def test_which_sites_show_which_settings():
    assert site_of("dailywire").settings.offers(SiteSetting.DOWNLOAD_WITH_COUNTDOWN)
    assert not site_of("dailywire").settings.offers(SiteSetting.AUTO_SUBTITLES)
    assert site_of("youtube").settings.offers(SiteSetting.SPONSORBLOCK)
    assert site_of("youtube").settings.offers(SiteSetting.AUTO_SUBTITLES)
    # NPO Start has no subtitles, so no auto-generated ones either.
    npo = site_of("npo").settings
    assert not any(npo.offers(key) for key in (SiteSetting.AUTO_SUBTITLES, SiteSetting.SPONSORBLOCK, SiteSetting.DOWNLOAD_WITH_COUNTDOWN))
    for key in ("generic:vimeo.com", "rumble"):
        assert site_of(key).settings.offers(SiteSetting.AUTO_SUBTITLES)
        assert not site_of(key).settings.offers(SiteSetting.SPONSORBLOCK)
        assert not site_of(key).settings.offers(SiteSetting.DOWNLOAD_WITH_COUNTDOWN)


def test_a_new_download_profile_starts_with_its_sites_settings(site_settings):
    from backend.services.site_settings import download_profile_defaults

    dailywire = download_profile_defaults(site_of("dailywire"))
    assert (dailywire["upgrade_check"], dailywire["upgrade_after_days"], dailywire["upgrade_improvements"]) == (True, 3, ["length"])
    assert dailywire["download_with_countdown"] is False

    youtube = download_profile_defaults(site_of("youtube"))
    assert youtube["upgrade_after_days"] == get_settings().download_profile_defaults.upgrade_after_days
    assert youtube["upgrade_improvements"] == ["resolution", "sponsorblock"]
    assert youtube["download_with_countdown"] is False

    # A Site only checks for what it can find, whatever the system default lists.
    site_settings(**{"generic:vimeo.com": {"upgrade_improvements": ["sponsorblock", "codec", "resolution"]}})
    vimeo = download_profile_defaults(site_of("generic:vimeo.com"))
    assert vimeo["upgrade_improvements"] == ["resolution", "codec"]


def test_a_local_media_profiles_choices_apply_where_a_site_has_the_setting(site_settings):
    from types import SimpleNamespace

    from backend.services.site_settings import local_media_profile_defaults, local_media_profile_site_choices

    # A new profile starts with what YouTube, the Site that shows SponsorBlock, starts with.
    defaults = local_media_profile_defaults()
    assert defaults["sponsorblock_enabled"] is True and defaults["auto_subtitles"] == get_settings().download_profile_defaults.auto_subtitles
    # SponsorBlock that keeps every segment type does nothing, so it starts off.
    site_settings(youtube={"sponsorblock": True, "sponsorblock_segments": {"sponsor": "keep", "intro": "keep", "outro": "keep", "poi_highlight": "keep"}})
    defaults = local_media_profile_defaults()
    assert set(defaults["sponsorblock_segments"].values()) == {"keep"} and defaults["sponsorblock_enabled"] is False

    profile = SimpleNamespace(auto_subtitles="always", sponsorblock_enabled=True, sponsorblock_segments={"sponsor": "cut"})
    youtube = local_media_profile_site_choices(profile, site_of("youtube"))
    assert (youtube["auto_subtitles"], youtube["sponsorblock_enabled"], youtube["sponsorblock_segments"]) == ("always", True, {"sponsor": "cut"})
    vimeo = local_media_profile_site_choices(profile, site_of("generic:vimeo.com"))
    assert (vimeo["auto_subtitles"], vimeo["sponsorblock_enabled"]) == ("always", False)
    # What a Site does not show stays off.
    for key in ("dailywire", "npo"):
        choices = local_media_profile_site_choices(profile, site_of(key))
        assert (choices["auto_subtitles"], choices["sponsorblock_enabled"]) == ("never", False)


def test_a_new_download_profile_starts_with_the_check_off_when_nothing_counts_as_better(site_settings):
    from dataclasses import replace

    from backend.services.site_settings import download_profile_defaults
    from sources import UpgradeChecks, UpgradeImprovement

    # NPO Start can only check the length, which no default counts as better.
    npo = download_profile_defaults(site_of("npo"))
    assert (npo["upgrade_check"], npo["upgrade_improvements"]) == (False, [])

    # As soon as a default counts something the Site offers, the check starts on.
    site_settings(npo={"upgrade_improvements": ["length"]})
    assert download_profile_defaults(site_of("npo"))["upgrade_check"] is True
    site_settings(npo={"upgrade_improvements": "default"})
    with_resolution = replace(site_of("npo"), upgrade_checks=UpgradeChecks((UpgradeImprovement.RESOLUTION, UpgradeImprovement.LENGTH)))
    assert download_profile_defaults(with_resolution)["upgrade_check"] is True

    # A user who turned the check off keeps it off, whatever counts as better.
    site_settings(youtube={"upgrade_check": False})
    assert download_profile_defaults(site_of("youtube"))["upgrade_check"] is False

