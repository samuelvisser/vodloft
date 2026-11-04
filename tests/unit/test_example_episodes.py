"""Example episodes of a collection that is being added: looked up cheaply, kept in memory, never saved."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sources import MAIN_TAG, SeasonRef, VideoDetails


def _video(slug, day, *, tag=MAIN_TAG, season=None, number=None, number_text=None, title=None, description=None):
    return VideoDetails(
        slug=slug, url=f"https://example.test/{slug}", title=title or f"Video {slug}", description=description,
        published_at=datetime(2026, 1, day, 12, tzinfo=timezone.utc), tag=tag, season=season,
        episode_number=number, number_text=number_text,
    )


@pytest.fixture
def newest(monkeypatch):
    from backend.services import example_episodes

    found: list[VideoDetails] = []
    monkeypatch.setattr(example_episodes, "newest_episodes", lambda source_key, url: list(found))
    return found


def _collection(source_key="ytdlp", numbering="date_based", seasons=()):
    from backend.services.example_episodes import ExampleCollection, ExampleSeason
    from backend.types.collection_types import EpisodeIdentifier

    return ExampleCollection(
        source_key=source_key, url="https://example.test/show", slug="show", title="The Show", author_name="Host",
        type="series", episode_identifier=EpisodeIdentifier(numbering),
        seasons=tuple(ExampleSeason(slug, name) for slug, name in seasons),
    )


def _values(collection):
    from backend.services.example_episodes import example_session, example_template_values

    with example_session(collection) as (_session, _collection, examples):
        return [(example.episode.episode_identifier, example_template_values(example)) for example in examples]


def test_dates_are_exact_and_numbers_counted_from_the_oldest_show_their_names(newest):
    newest.extend([_video("b", 2), _video("a", 1)])

    (identifier, values), _older = _values(_collection())

    assert identifier == "ep.2026-01-02T12:00:00.000000"
    assert values["episode_identifier"] == identifier
    assert values["collection_title"] == "The Show"
    assert values["episode_title"] == "Video b"
    assert values["season_name"] == "2026"
    # Indexing counts these from the collection's oldest episode.
    assert values["episode_index"] == "[episode_index]"
    assert values["season_index"] == "[season_index]"


def test_a_listed_numbered_collection_shows_its_numbers_by_name_but_keeps_the_episode_type(newest):
    newest.extend([_video("short", 3, tag="short"), _video("main", 2)])

    (short_id, short), (main_id, main) = _values(_collection(numbering="numbered"))

    assert short["episode_type"] == "short" and short["episode_number"] == "[episode_number]"
    assert main["episode_type"] == "ep" and main["episode_identifier"] == "[episode_identifier]"
    assert short_id.startswith("short.") and main_id.startswith("ep.")


def test_daily_wire_numbers_come_from_its_own_episode_numbers_and_seasons(newest):
    season = SeasonRef("season-2", 2, "Season 2")
    newest.extend([
        _video("extra", 3, tag="ep-extra", season=season, number=12, number_text="12.01"),
        _video("twelve", 2, season=season, number=12, number_text="12"),
    ])
    seasons = [("season-1", "Season 1"), ("extras", "Extras"), ("season-2", "Season 2")]

    (_extra_id, extra), (twelve_id, twelve) = _values(_collection("dailywire", "seasonal", seasons))

    assert twelve_id == "ep.S02E12"
    assert (twelve["season_number"], twelve["season_index"], twelve["dw_episode_number"]) == ("2", "3", "12")
    assert extra["episode_type"] == "ep-extra" and extra["episode_label"] == "[episode_label]"


def test_nothing_is_saved_and_each_use_starts_empty(newest):
    from backend.services.example_episodes import example_session

    newest.append(_video("a", 1))
    for _ in range(2):
        with example_session(_collection()) as (session, _collection_row, examples):
            from backend.db.models import Episode
            assert session.query(Episode).count() == len(examples) == 1


@pytest.fixture
def client(monkeypatch, newest):
    from backend.api.endpoints.download_profiles import router as download_profiles
    from backend.api.endpoints.local_media_profiles import router as local_media_profiles
    from backend.api.endpoints.regex import router as regex

    newest.extend([
        _video("c", 3, title="Weekly highlights", description="Part three"),
        _video("b", 2, tag="short", title="Short clip"),
        _video("a", 1, title="Highlights of the year"),
    ])
    app = FastAPI()
    for module in (download_profiles, local_media_profiles, regex):
        app.include_router(module.router, prefix="/api")
    return TestClient(app)


EXAMPLE = {
    "sourceKey": "ytdlp", "sharingUrl": "https://www.youtube.com/@show", "slug": "show", "title": "The Show",
    "type": "series", "episodeIdentifier": "date_based",
}


def test_the_examples_are_template_sources_newest_first(client):
    body = client.post("/api/local-media-profiles/template/sources/examples", json=EXAMPLE).json()

    assert [source["values"]["episode_title"] for source in body] == ["Weekly highlights", "Short clip", "Highlights of the year"]
    assert body[0]["id"] == "new-episode:c"
    assert body[0]["label"] == "The Show — Weekly highlights"
    assert "episode_index" in body[0]["pending"]


def test_the_regex_test_runs_on_the_examples(client):
    body = client.post("/api/regex/check", json={
        "pattern": r"\bhighlights\b", "ignoreCase": True, "exampleCollection": EXAMPLE, "field": "title",
    }).json()

    assert (body["collectionMatches"], body["collectionTotal"]) == (2, 3)


def test_which_episodes_counts_the_examples(client):
    body = client.post("/api/download-profiles/which-episodes", json={
        "exampleCollection": EXAMPLE, "downloadWithCountdown": False, "includeEpisodes": True, "filters": [
            {"action": "only", "field": "types", "episodeTypes": ["ep"]},
            {"action": "only", "field": "published", "count": 1},
        ],
    }).json()

    assert (body["total"], body["filters"], body["downloaded"]) == (3, [1, 1], 1)
    assert [episode["leftOutBy"] for episode in body["episodes"]] == [None, "filter:0", "filter:1"]


def test_which_episodes_needs_one_collection(client):
    response = client.post("/api/download-profiles/which-episodes", json={
        "downloadWithCountdown": False,
    })

    assert response.status_code == 422


def test_an_example_renders_a_custom_index_by_name():
    from backend.api.endpoints.local_media_profiles.output_template import get_output_template_preview
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview

    result = get_output_template_preview(None, LocalMediaProfileTemplatePreview.model_validate({
        "type": "collection", "outputTemplate": "/downloads/{{ episode_title }} {{ 'part' | custom_index }}.ext",
        "preferredFormat": "format_1080p", "values": {"episode_title": "Pilot"}, "sourceId": "new-episode:pilot",
        "indexingValues": [{"key": "part", "name": "Part"}],
    }))

    assert result.output_path == "/downloads/Pilot [part].mp4"


_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <yt:videoId>short1</yt:videoId>
  <title>A Short</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/short1"/>
  <author><name>Host</name><uri>https://www.youtube.com/channel/UC1</uri></author>
  <published>2026-11-03T10:00:00+00:00</published>
  <media:group><media:thumbnail url="https://i.ytimg.com/vi/short1/hqdefault.jpg"/><media:description>Quick</media:description></media:group>
 </entry>
 <entry>
  <yt:videoId>video1</yt:videoId>
  <title>A Video</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=video1"/>
  <published>2026-11-02T10:00:00+00:00</published>
 </entry>
</feed>"""


def test_the_youtube_feed_gives_videos_without_a_key(monkeypatch):
    from sources.ytdlp import youtube_rss

    class Response:
        ok, status_code, content = True, 200, _FEED

    monkeypatch.setattr(youtube_rss.requests, "get", lambda *args, **kwargs: Response())

    short, video = youtube_rss.latest_videos(channel_id="UC1")

    assert (short.slug, short.tag, short.title, short.description, short.author_name) == ("short1", "short", "A Short", "Quick", "Host")
    assert short.image_url == "https://i.ytimg.com/vi/short1/hqdefault.jpg"
    assert short.published_at == datetime(2026, 11, 3, 10, tzinfo=timezone.utc)
    assert (video.tag, video.url, video.duration) == (MAIN_TAG, "https://www.youtube.com/watch?v=video1", None)


def test_daily_wire_takes_the_show_page_and_fills_up_from_the_newest_season(monkeypatch):
    from dataclasses import dataclass
    from types import SimpleNamespace

    from sources.dailywire import source as dailywire

    @dataclass(frozen=True)
    class Record:
        slug: str
        episode_number: str
        day: int
        trailer: bool = False
        title: str = "Title"
        description: str | None = None
        duration: float = 60.0
        thumbnail_landscape_path: str | None = None
        background_image_path: str | None = None

        @property
        def sharing_url(self):
            return f"https://www.dailywire.com/episode/{self.slug}"

        @property
        def published_date(self):
            return datetime(2026, 1, self.day, tzinfo=timezone.utc)

        @property
        def ep_number(self):
            return int(self.episode_number.split(".")[0]) if self.episode_number else None

        @property
        def ep_segment(self):
            return int(self.episode_number.split(".")[1]) if "." in self.episode_number else 0

    newest_season = SimpleNamespace(slug="season-2", name="Season 2", dw_id="s2")
    show = SimpleNamespace(
        slug="show", seasons=[newest_season, SimpleNamespace(slug="season-1", name="Season 1", dw_id="s1")],
        latest_season=newest_season,
        latest_episodes=[Record("e3", "3", 3), Record("e3-extra", "3.01", 4), Record("trailer", "", 5, trailer=True)],
    )
    pages = {"s2": [Record("e3", "3", 3), Record("e2", "2", 2)], "s1": [Record("e1", "1", 1)]}
    requested = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def get_show_page(self, slug):
            return show

        def get_episodes_paginated(self, slug, selector):
            requested.append(selector.season_dw_id)
            return SimpleNamespace(items=pages[selector.season_dw_id])

    monkeypatch.setattr(dailywire, "MiddlewareClient", Client)
    monkeypatch.setattr(dailywire, "_access_token", lambda: None)

    newest = dailywire.DailyWireSource().newest_episodes("https://www.dailywire.com/show/show")

    assert [(video.slug, video.tag) for video in newest] == [
        ("trailer", "trailer"), ("e3-extra", "ep-extra"), ("e3", MAIN_TAG), ("e2", MAIN_TAG), ("e1", MAIN_TAG),
    ]
    assert requested == ["s2", "s1"]
    assert newest[1].number_text == "3.01" and newest[1].episode_number == 3
    assert newest[2].season == SeasonRef("season-2", 2, "Season 2")
