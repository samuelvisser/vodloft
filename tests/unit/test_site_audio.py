"""A Site with sound only, whose Music collections hold tracks rather than music videos."""
from __future__ import annotations

from backend.api.models.source import SiteAPIRead
from sources.ytdlp.sites import site_of


def test_bandcamp_and_soundcloud_have_sound_only():
    assert site_of("bandcamp").audio_only
    assert site_of("soundcloud").audio_only
    assert not site_of("youtube").audio_only


def test_the_api_tells_the_site_has_sound_only():
    assert SiteAPIRead(key="bandcamp", name="Bandcamp").model_dump(by_alias=True)["audioOnly"] is True
    assert SiteAPIRead(key="youtube", name="YouTube").model_dump(by_alias=True)["audioOnly"] is False
