"""Generic endpoints work for any Source, and only send a Source's own fields
when that Source has the Feature they belong to."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import ANY_DOMAIN, LinkKind, ResolvedLink, Source, registry


class StubSource(Source):
    """A Source with no Features, as a second service would start out."""

    id = "stub"
    name = "Stub Video"
    domains = ("stub.example",)
    features = frozenset()

    def resolve(self, url):
        if "/watch/" not in url:
            return None
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return ResolvedLink(kind=LinkKind.MOVIE, slug=slug, url=url, title=f"Stub {slug}")

    def episode_media(self, *, slug, members_only, interactive=False):
        raise NotImplementedError

    def movie_playback(self, **_kwargs):
        raise NotImplementedError


class CatchAllSource(StubSource):
    id = "catch_all"
    name = "Anything"
    domains = (ANY_DOMAIN,)

    def resolve(self, url):
        return ResolvedLink(kind=LinkKind.SHOW, slug="anything", url=url, title="Anything")


@pytest.fixture
def stub_sources(monkeypatch):
    # Only the stubs claim every domain, so no real catch-all Source answers first.
    sources = {key: source for key, source in registry._sources.items() if ANY_DOMAIN not in source.domains}
    monkeypatch.setattr(registry, "_sources", sources)
    catch_all = registry.register(CatchAllSource())
    stub = registry.register(StubSource())
    return stub, catch_all


@pytest.fixture
def session():
    from backend.db.core import Base

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture
def client(stub_sources, session, monkeypatch):
    from backend.api.endpoints.sources import router as source_router_module

    @contextmanager
    def db_session():
        yield session

    monkeypatch.setattr(source_router_module, "db_session", db_session)
    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _show(source_key: str):
    from backend.db.models import Show
    from backend.types.show_types import EpisodeIdentifier, ShowType

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Show(
        id=1, uuid="show-uuid", slug="a-show", title="A Show", sharing_url="https://example.test/a-show",
        membership_level="ALL_ACCESS", type=ShowType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="Host", author_slug="host",
        source_key=source_key, created_at=now, updated_at=now,
    )


def test_sources_that_claim_every_domain_come_last(stub_sources):
    stub, catch_all = stub_sources
    assert registry.sources_for("https://www.stub.example/watch/x") == [stub, catch_all]
    assert registry.sources_for("https://elsewhere.example/") == [catch_all]


def test_daily_wire_links_are_parsed_by_path():
    from sources.dailywire.links import parse_link

    assert parse_link("https://www.dailywire.com/show/the-ben-shapiro-show") == (LinkKind.SHOW, "the-ben-shapiro-show")
    assert parse_link("https://www.dailywire.com/videos/run-hide-fight/") == (LinkKind.MOVIE, "run-hide-fight")
    assert parse_link("https://www.dailywire.com/episode/ep-1?x=1") == (LinkKind.EPISODE, "ep-1")
    assert parse_link("https://www.dailywire.com/") is None
    assert parse_link("https://www.dailywire.com/about/team") is None


def test_resolve_stops_at_the_first_source_that_recognises_the_link(client):
    response = client.post("/api/resolve", json={"url": "stub.example/watch/clip-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == {"id": "stub", "name": "Stub Video", "domains": ["stub.example"], "features": []}
    assert body["kind"] == "movie"
    assert body["slug"] == "clip-1"
    assert body["preview"]["title"] == "Stub clip-1"

    # The stub does not recognise this path, so the catch-all Source answers.
    fallback = client.post("/api/resolve", json={"url": "https://stub.example/about"}).json()
    assert fallback["source"]["id"] == "catch_all"


def test_resolve_explains_an_unrecognised_link(client, monkeypatch):
    monkeypatch.setattr(registry, "_sources", {"stub": StubSource()})
    response = client.post("/api/resolve", json={"url": "https://nothing.example/x"})
    assert response.status_code == 422
    assert "No Source recognises" in response.json()["detail"]


def test_resolve_reports_a_failing_source_as_bad_gateway(client, monkeypatch):
    def broken(url):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(registry.get_source("stub"), "resolve", broken)
    response = client.post("/api/resolve", json={"url": "https://stub.example/watch/x"})
    assert response.status_code == 502
    assert "Stub Video could not look up this link" in response.json()["detail"]


def test_resolve_finds_the_show_of_a_known_episode(client, session, monkeypatch):
    from backend.db.models import Episode, Season
    from backend.utils.helpers import generate_uuid

    show = _show("stub")
    season = Season(show=show, index=1, slug="season-1", name="One")
    episode = Episode(
        uuid=generate_uuid(), type="episode", show=show, season=season, index=1, episode_identifier="ep.1",
        slug="ep-1", title="Episode 1", duration=1.0, publish_status="published_final",
        sharing_url="https://stub.example/episode/ep-1", source_key="stub",
    )
    session.add_all([show, season, episode])
    session.commit()

    monkeypatch.setattr(
        registry.get_source("stub"), "resolve",
        lambda url: ResolvedLink(kind=LinkKind.EPISODE, slug="ep-1", url=url, title="Episode 1"),
    )
    body = client.post("/api/resolve", json={"url": "https://stub.example/episode/ep-1"}).json()
    assert body["kind"] == "episode"
    assert body["showSlug"] == "a-show"
    assert body["showUrl"] == "https://example.test/a-show"


def test_source_list_names_each_source_and_its_features(client):
    sources = {source["id"]: source for source in client.get("/api/sources").json()}
    assert sources["stub"]["features"] == []
    assert "membership_levels" in sources["dailywire"]["features"]
    assert sources["dailywire"]["domains"] == ["dailywire.com"]


def test_show_response_leaves_out_daily_wire_only_fields_for_other_sources(stub_sources):
    from backend.api.models.show import ShowAPIRead

    stub_show = ShowAPIRead.model_validate(_show("stub")).model_dump(by_alias=True)
    assert stub_show["sourceKey"] == "stub"
    assert stub_show["sourceFeatures"] == []
    assert "membershipLevel" not in stub_show

    dw_show = ShowAPIRead.model_validate(_show("dailywire")).model_dump(by_alias=True)
    assert dw_show["membershipLevel"] == "ALL_ACCESS"
    assert "live_episodes" in dw_show["sourceFeatures"]


def test_movie_and_episode_responses_leave_out_daily_wire_only_fields(stub_sources):
    from backend.api.models.episode import EpisodeAPIRead
    from backend.api.models.movie import MovieAPIRead

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    movie = MovieAPIRead.model_validate({
        "id": 1, "uuid": "u", "slug": "m", "title": "M", "extended_title": None, "description": None,
        "duration": 1.0, "background_image_path": None, "thumbnail_landscape_path": None,
        "thumbnail_portrait_path": None, "thumbnail_square_path": None, "sharing_url": None,
        "author_name": None, "author_slug": None, "logo_image_path": None, "mature_rating": None,
        "has_video": True, "is_downloadable": True, "status": None, "published_at": None,
        "background": None, "byline": None, "language": None, "origin_country": None, "images": {},
        "available_for": ["ALL_ACCESS"], "cast_and_crew": [], "directed_by": [], "genres": [], "hosts": [],
        "production_companies": [], "starring": [], "written_by": [], "release_date": None,
        "release_date_source": None, "release_date_source_id": None, "release_date_lookup_status": "pending",
        "release_date_lookup_attempted_at": None, "release_date_lookup_error": None,
        "movie_extras": [], "created_at": now, "updated_at": now, "source_key": "stub",
    }).model_dump(by_alias=True)
    for field in ("availableFor", "movieExtras", "officialTrailer", "officialTrailerId"):
        assert field not in movie
    assert movie["title"] == "M"

    episode = EpisodeAPIRead.model_validate({
        "id": 1, "show_id": 1, "season_id": 1, "index": 1, "publish_status": "published_final",
        "went_live_date": now, "published_date": now, "scheduled_date": None, "sharing_url": "https://x",
        "download_delay_passed": True, "download_delay_ready_at": None, "title": "E", "description": None,
        "duration": 1.0, "uuid": "u", "slug": "e", "background_image_path": None,
        "thumbnail_landscape_path": None, "thumbnail_portrait_path": None, "thumbnail_square_path": None,
        "episode_identifier": "ep.1", "dw_episode_number": None, "episode_type": None,
        "episode_extra_type": None, "episode_number": None, "episode_sub_number": None, "episode_label": "1",
        "created_at": now, "updated_at": now, "source_key": "stub",
    }).model_dump(by_alias=True)
    assert "wentLiveDate" not in episode
    assert episode["sourceKey"] == "stub"


def test_api_routes_serialise_the_trimmed_show(stub_sources):
    """FastAPI validates the dumped response again, which must not need the dropped field."""
    from backend.api.models.show import ShowAPIRead

    app = FastAPI()

    @app.get("/show", response_model=ShowAPIRead)
    def show():
        return ShowAPIRead.model_validate(_show("stub"))

    with TestClient(app) as test_client:
        body = test_client.get("/show").json()
    assert "membershipLevel" not in body
    assert body["sourceKey"] == "stub"
