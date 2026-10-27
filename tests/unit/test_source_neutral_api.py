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

from backend.api.errors import source_request_error_handler
from backend.services.source_requests import SourceRequestError
from sources import ANY_DOMAIN, LinkKind, ResolvedLink, SearchNotice, SearchResults, Source, registry


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
    import backend.db.models  # noqa: F401  (registers every table)

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
    app.add_exception_handler(SourceRequestError, source_request_error_handler)
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
    assert body["source"] == {"id": "stub", "name": "Stub Video", "domains": ["stub.example"], "features": [], "searchLabel": None}
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


def test_a_link_looked_up_with_one_source_names_that_source(client, monkeypatch):
    monkeypatch.setattr(registry, "_sources", {"stub": StubSource()})
    response = client.post("/api/resolve", json={"url": "https://stub.example/about", "sourceKey": "stub"})
    assert response.status_code == 422
    assert response.json()["detail"] == "Stub Video does not recognise this link"


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


def test_show_responses_have_the_same_shape_for_every_source(stub_sources):
    from backend.api.models.show import ShowAPIRead

    stub_show = ShowAPIRead.model_validate(_show("stub")).model_dump(by_alias=True)
    dw_show = ShowAPIRead.model_validate(_show("dailywire")).model_dump(by_alias=True)

    assert stub_show.keys() == dw_show.keys()
    assert stub_show["sourceKey"] == "stub"
    assert stub_show["sourceFeatures"] == []
    assert "live_episodes" in dw_show["sourceFeatures"]


def test_movie_and_episode_responses_send_every_field(stub_sources):
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
    assert movie["availableFor"] == ["ALL_ACCESS"]
    assert movie["movieExtras"] == []
    assert movie["officialTrailer"] is None and movie["officialTrailerId"] is None
    assert movie["sourceFeatures"] == []

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
    assert episode["wentLiveDate"] == now
    assert episode["sourceKey"] == "stub"


def test_api_routes_serialise_a_show_from_any_source(stub_sources):
    from backend.api.models.show import ShowAPIRead

    app = FastAPI()

    @app.get("/show", response_model=ShowAPIRead)
    def show():
        return ShowAPIRead.model_validate(_show("stub"))

    with TestClient(app) as test_client:
        body = test_client.get("/show").json()
    assert body["membershipLevel"] == "ALL_ACCESS"
    assert body["sourceKey"] == "stub"


def test_a_preferred_source_is_asked_first(client, stub_sources):
    stub, catch_all = stub_sources
    assert registry.sources_for("https://www.stub.example/watch/x", {"stub.example": "catch_all"}) == [catch_all, stub]
    assert registry.sources_for("https://elsewhere.example/", {"stub.example": "catch_all"}) == [catch_all]

    body = client.post("/api/resolve", json={"url": "https://stub.example/watch/clip-1"}).json()
    assert body["source"]["id"] == "stub"
    assert [candidate["id"] for candidate in body["candidates"]] == ["stub", "catch_all"]

    picked = client.post("/api/resolve", json={"url": "https://stub.example/watch/clip-1", "sourceKey": "catch_all"}).json()
    assert picked["source"]["id"] == "catch_all"
    assert client.post("/api/resolve", json={"url": "https://stub.example/x", "sourceKey": "nope"}).status_code == 422


def test_the_preferred_source_per_domain_is_saved(client):
    domains = {row["domain"]: row for row in client.get("/api/sources/domains").json()}
    assert domains["stub.example"] == {
        "domain": "stub.example", "sourceKeys": ["stub", "catch_all"], "defaultSourceKey": "stub",
        "preferredSourceKey": None,
    }

    saved = client.put("/api/sources/domains/stub.example", json={"preferredSourceKey": "catch_all"}).json()
    assert saved["preferredSourceKey"] == "catch_all"
    body = client.post("/api/resolve", json={"url": "https://stub.example/watch/clip-1"}).json()
    assert body["source"]["id"] == "catch_all"

    assert client.put("/api/sources/domains/stub.example", json={"preferredSourceKey": "nope"}).status_code == 422
    assert client.put("/api/sources/domains/other.example", json={"preferredSourceKey": "stub"}).status_code == 422
    reset = client.put("/api/sources/domains/stub.example", json={"preferredSourceKey": None}).json()
    assert reset["preferredSourceKey"] is None
    assert client.post("/api/resolve", json={"url": "https://stub.example/watch/clip-1"}).json()["source"]["id"] == "stub"


def test_a_source_with_search_is_searched_by_name(client, monkeypatch):
    from sources import Feature

    stub = registry.get_source("stub")
    assert client.get("/api/sources/stub/search", params={"q": "clip"}).status_code == 404

    monkeypatch.setattr(type(stub), "features", frozenset({Feature.SEARCH}))
    monkeypatch.setattr(stub, "search", lambda query, **_: SearchResults([
        ResolvedLink(kind=LinkKind.SHOW, slug="clips", url="https://stub.example/show/clips", title=f"{query} show",
                     kind_label="Channel", facts=("3 videos",)),
    ], SearchNotice(badge="Search via stub", text="Answered by the stub")), raising=False)
    body = client.get("/api/sources/stub/search", params={"q": "clip"}).json()
    assert body == {
        "results": [{
            "kind": "show", "slug": "clips", "url": "https://stub.example/show/clips", "title": "clip show",
            "description": None, "imageUrl": None, "authorName": None, "showSlug": None, "showUrl": None,
            "kindLabel": "Channel", "facts": ["3 videos"],
        }],
        "notice": {
            "badge": "Search via stub", "text": "Answered by the stub", "tone": "neutral",
            "linkLabel": None, "linkPath": None,
        },
    }
