"""Site icons and initials: the UI can show every icon a Site names, and every Site has initials for the rest."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from sources import all_sources
from sources.contract import Site
from sources.ytdlp.site_contracts import CONTRACTS
from sources.ytdlp.sites import site_of

UI_SITE_ICONS = Path(__file__).resolve().parents[2] / "ui/src/icons/siteIcons.ts"


def _contract_sites() -> list[Site]:
    named = [site for source in all_sources() for site in source.sites]
    return [*named, *(site_of(key) for key in CONTRACTS)]


def test_every_site_icon_has_an_entry_in_the_ui():
    entries = re.findall(r"'([a-z]+:[a-z0-9-]+)': faIcon\('([a-z]+)', '([a-z0-9-]+)'\)", UI_SITE_ICONS.read_text())
    # Each entry draws the icon it is listed by.
    assert all(key == f"{prefix}:{name}" for key, prefix, name in entries)
    listed = {key for key, *_ in entries}
    missing = {site.key: site.icon for site in _contract_sites() if site.icon and site.icon not in listed}
    assert not missing, f"Add these Site icons to ui/src/icons/siteIcons.ts: {missing}"


def test_every_site_has_initials():
    assert all(re.fullmatch(r"[A-Z0-9]{1,2}", site.initials) for site in _contract_sites())


def test_a_site_with_creators_needs_no_icon():
    assert Site("tube", "Tube", creators=True).icon is None


@pytest.mark.parametrize(("name", "initials"), [
    ("SoundCloud", "SC"), ("The Daily Wire", "DW"), ("Vimeo", "VI"), ("example.com", "EX"), ("www.my-site.co.uk", "MS"),
    ("X", "X"),
])
def test_initials_come_from_the_name(name, initials):
    assert Site("site", name).initials == initials


def test_a_site_without_a_contract_gets_initials_from_its_domain():
    site = site_of("generic", "streams.example")
    assert (site.icon, site.initials) == (None, "ST")


def test_a_contract_names_its_own_initials():
    assert (site_of("youtube").icon, site_of("youtube").initials) == ("fab:youtube", "YT")
    assert Site("site", "Site", initials="ZZ").initials == "ZZ"
    with pytest.raises(ValueError, match="initials"):
        Site("site", "Site", initials="abc")


def test_an_icon_is_named_as_prefix_and_name():
    with pytest.raises(ValueError, match="prefix:name"):
        Site("tube", "Tube", icon="youtube")
    assert Site("tube", "Tube", icon="fab:youtube").icon == "fab:youtube"
