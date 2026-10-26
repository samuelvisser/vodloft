from __future__ import annotations

from types import SimpleNamespace

import pytest

import sources
from sources import Feature, UnknownSourceError, get_source, sources_for
from sources.dailywire import DailyWireSource
from sources.dailywire import source as dailywire_source
from sources.ytdlp import YtDlpSource


def test_daily_wire_is_registered():
    source = get_source(sources.DAILYWIRE)
    assert isinstance(source, DailyWireSource)
    assert source.name == "The Daily Wire"
    assert source.has(Feature.RSS_STREAMING)
    assert sources.all_sources() == [source, get_source("npo"), get_source("ytdlp")]


def test_ytdlp_claims_every_link_after_the_dedicated_sources():
    ytdlp = get_source("ytdlp")
    assert isinstance(ytdlp, YtDlpSource)
    assert sources_for("https://www.dailywire.com/show/x") == [get_source(sources.DAILYWIRE), ytdlp]
    assert sources_for("https://www.youtube.com/watch?v=x") == [ytdlp]


def test_unknown_source_raises():
    with pytest.raises(UnknownSourceError):
        get_source("nope")


def test_registering_an_id_twice_fails():
    with pytest.raises(ValueError):
        sources.register(DailyWireSource())


@pytest.mark.parametrize("url, handled", [
    ("https://www.dailywire.com/show/the-ben-shapiro-show", True),
    ("https://dailywire.com/videos/x", True),
    ("https://DAILYWIRE.COM./x", True),
    ("https://notdailywire.com/x", False),
    ("https://dailywire.com.evil.example/x", False),
    ("not a url", False),
])
def test_sources_for_matches_domain_and_subdomains(url, handled):
    assert (get_source(sources.DAILYWIRE) in sources_for(url)) is handled


def test_episode_media_uses_member_lookup(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def get_episode_details(self, slug, *, require_member_exclusive):
            calls.append((slug, require_member_exclusive))
            return SimpleNamespace(video_url="https://v", audio_url=None)

    monkeypatch.setattr(dailywire_source, "MiddlewareClient", FakeClient)
    media = DailyWireSource().episode_media(slug="ep", members_only=True)
    assert media == sources.EpisodeMedia(video_url="https://v", audio_url=None)
    assert calls == [{}, ("ep", True)]

    calls.clear()
    DailyWireSource().episode_media(slug="ep", members_only=False, interactive=True)
    assert calls == [{"request_priority": "interactive"}, ("ep", False)]


def test_movie_playback_signs_in_and_resolves(monkeypatch):
    seen = {}

    class FakeAuth:
        def get_token(self):
            return SimpleNamespace(access_token="token")

    class FakeMovieClient:
        def __init__(self, *, access_token):
            seen["token"] = access_token

    def fake_resolve(client, **kwargs):
        seen["client"], seen["kwargs"] = client, kwargs
        return SimpleNamespace(url="https://m3u8", metadata="record")

    monkeypatch.setattr(dailywire_source, "DeviceAuthClient", FakeAuth)
    monkeypatch.setattr(dailywire_source, "MovieMiddlewareClient", FakeMovieClient)
    monkeypatch.setattr(dailywire_source, "resolve_movie_playback", fake_resolve)

    playback = DailyWireSource().movie_playback(movie_slug="m", title="M", duration=10.0, extra_slug="x", is_extra=True)
    assert playback == sources.Playback(url="https://m3u8", metadata="record")
    assert seen["token"] == "token"
    assert seen["kwargs"] == {
        "movie_slug": "m", "title": "M", "duration": 10.0,
        "is_extra": True, "extra_slug": "x", "is_official_trailer": False,
    }
