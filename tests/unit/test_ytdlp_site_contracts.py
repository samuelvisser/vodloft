"""The yt-dlp sites' own contracts, and OtherSites for whatever they leave out."""
from dataclasses import replace

import pytest
from sources import SiteSetting, site_for
from sources.ytdlp.site_contracts import CONTRACTS, OtherSites
from sources.ytdlp.sites import site_of


def _without_identity(site):
    return replace(site, key="", name="", domains=(), accesses=())


def test_a_contract_that_only_names_its_locked_content_takes_everything_else_from_other_sites():
    floatplane = site_of("floatplane", "floatplane.com")

    assert floatplane.name == "Floatplane"
    assert floatplane.access("members").description == "Only subscribers of the creator can watch this."
    # The general name of what Floatplane names no differently.
    assert floatplane.access("premium").label == "Premium only"
    assert _without_identity(floatplane) == _without_identity(site_of("arte", "arte.tv"))


def test_a_site_without_a_contract_is_named_after_its_domain():
    assert site_of("arte", "arte.tv").name == "arte.tv"


def test_a_page_only_the_generic_extractor_handles_gets_what_other_sites_offer():
    site = site_for("https://example.com/clip.mp4", "ytdlp")

    assert site.key == "generic:example.com"
    assert site.downloads == OtherSites.downloads
    assert site.settings.offers(SiteSetting.CHAPTERS)
    assert [access.label for access in site.accesses] == ["Subscribers only", "Premium only"]


def test_youtube_keeps_the_chapters_other_sites_show_beside_sponsorblock():
    shows = site_of("youtube").settings.shows

    assert {SiteSetting.CHAPTERS, SiteSetting.SPONSORBLOCK, SiteSetting.SPONSORBLOCK_SEGMENTS} <= shows


def test_a_sites_contract_is_built_once():
    assert site_for("https://youtu.be/a", "ytdlp") is site_for("https://youtu.be/b", "ytdlp")


def test_a_contract_can_only_set_what_a_site_has():
    with pytest.raises(TypeError, match="creator_lable"):
        type("Misspelled", (OtherSites,), {"key": "misspelled", "creator_lable": "artist"})


def test_every_contract_has_a_key_of_its_own():
    assert all(key == contract.key for key, contract in CONTRACTS.items())
    assert len(CONTRACTS) == len({contract.__name__ for contract in CONTRACTS.values()})


def test_soundcloud_and_bandcamp_name_the_lists_their_link_seasons_come_from():
    soundcloud, bandcamp = site_of("soundcloud").list_names, site_of("bandcamp").list_names

    assert (soundcloud.one, soundcloud.many, soundcloud.loose_season) == ("album or playlist", "albums and playlists", "Tracks")
    assert (bandcamp.one, bandcamp.many, bandcamp.loose_season) == ("album", "albums", "Tracks")
    # A Music collection still puts what is in no album in Singles.
    assert soundcloud.music_loose_season == bandcamp.music_loose_season == "Singles"
