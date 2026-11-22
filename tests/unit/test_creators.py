"""Creators: a creator groups channel collections and movies, and joining or leaving one changes nothing a collection
holds. A collection is a channel or one list, told by its link, and only a channel collection can be in a creator."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from progress_plan import PlanTracker, StageSpec
from sources import CreatorDetails, Feature, Names, SectionKind, SectionRef, SectionRole, SectionType, Site, registry
from test_ytdlp_collections import ListedSource, session  # noqa: F401

ROOT = "https://tube.example/@workshop"
PLAYLIST = "https://tube.example/playlist?list=PLcabin"
VIDEOS = SectionType("videos", SectionKind.FEED, Names("video", "videos"))
SHORTS = SectionType("shorts", SectionKind.FEED, Names("short", "shorts"), role=SectionRole.SHORT, episode_tag="short")
PLAYLISTS = SectionType("list", SectionKind.LIST, Names("playlist", "playlists"))
SHOWS = SectionType("show", SectionKind.SHOW, Names("show", "shows"))
CAST_ROOT = "https://cast.example/hosts/northwind"
SHOW = "https://cast.example/shows/workbench"


class CreatorSource(ListedSource):
    id = "tube"
    name = "Tube"
    domains = ("tube.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site(
        "tube", "Tube", ("tube.example",), creators=True, section_types=(VIDEOS, SHORTS, PLAYLISTS), link_seasons=True,
        channel_collection_names=Names("channel", "channels"), list_collection_names=Names("playlist", "playlists"),
    ),)

    def is_creator_page(self, url):
        return url in (ROOT, f"{ROOT}/videos")

    def is_list(self, url):
        return "playlist?list=" in url

    def creator_of(self, url):
        return ROOT if url.startswith("https://tube.example/") else None

    def creator_details(self, ref, plan=None):
        plan = plan or PlanTracker()
        plan.add(StageSpec(id="read", code="read_creator", label="Reading the creator"))
        with plan.running("read"):
            pass
        return CreatorDetails(
            ref="UCworkshop", url=ROOT, title="Northwind Workshop", handle="@workshop",
            sections=(SectionRef("videos", f"{ROOT}/videos", VIDEOS), SectionRef("PLcabin", PLAYLIST, PLAYLISTS, "Cabin")),
        )


class CastSource(ListedSource):
    """A second Site, whose creators are hosts with shows beside their own channel."""

    id = "cast"
    name = "Cast"
    domains = ("cast.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site("cast", "Cast", ("cast.example",), creators=True, creator_names=Names("host", "hosts"), section_types=(SHOWS,)),)

    def creator_of(self, url):
        return CAST_ROOT if url.startswith("https://cast.example/") else None

    def creator_details(self, ref, plan=None):
        return CreatorDetails(
            ref="northwind", url=CAST_ROOT, title="Northwind Live", handle="@nw-live",
            sections=(
                SectionRef("workbench", SHOW, SHOWS, "The Workbench"),
                SectionRef("garage", "https://cast.example/shows/garage", SHOWS, "The Garage"),
            ),
        )


class PlainSource(ListedSource):
    """A Site without creators, whose collections are lists."""

    id = "plain"
    name = "Plain"
    domains = ("plain.example",)
    sites = (Site("plain", "Plain", ("plain.example",)),)


@pytest.fixture(autouse=True)
def forget_lookups(monkeypatch):
    """Each test looks its creators up afresh."""
    from backend.api.endpoints.creators import service

    monkeypatch.setattr(service, "_lookups", {})


@pytest.fixture
def tube(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    registry.register(CastSource())
    registry.register(PlainSource())
    return registry.register(CreatorSource())


@pytest.fixture
def client(tube, session):
    from fastapi.responses import JSONResponse

    from backend.api.endpoints.collections import router as collection_router_module
    from backend.api.endpoints.creators import router as creator_router_module
    from backend.services.errors import ServiceError

    app = FastAPI()
    app.add_exception_handler(ServiceError, lambda _request, exc: JSONResponse(status_code=422, content={"detail": str(exc)}))
    app.include_router(creator_router_module.router, prefix="/api")
    app.include_router(collection_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _add(slug, url, source_key="tube"):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.collections import add_collection

    def add(s):
        collection = Collection(
            uuid=f"uuid-{slug}", slug=slug, source_key=source_key, title=slug.title(), sharing_url=url,
            membership_level="FREE", type="series", episode_identifier="date_based", author_name="", author_slug="",
        )
        add_collection(s, collection)
        s.flush()
        return collection.id

    return run_write_transaction(add)


def _collection(session, slug):
    from backend.db.models import Collection

    session.expire_all()
    return session.scalar(select(Collection).where(Collection.slug == slug))


def test_a_collection_of_a_channel_is_a_channel_with_the_channel_defaults(tube, session):
    _add("workshop", ROOT)

    collection = _collection(session, "workshop")
    assert collection.kind == "channel"
    assert (collection.link_seasons, collection.outside_videos, collection.channel_season) == ("selected", "add", "everything")


def test_a_playlist_and_anything_on_a_site_without_creators_is_a_list(tube, session):
    _add("cabin", PLAYLIST)
    _add("plain", "https://plain.example/everything", source_key="plain")

    for slug in ("cabin", "plain"):
        collection = _collection(session, slug)
        assert collection.kind == "list"
        assert collection.link_seasons == "off"


def test_a_channel_collection_joins_the_creator_behind_its_link_and_keeps_what_it_holds(client, session):
    _add("workshop", ROOT)
    before = _collection(session, "workshop")
    settings = (before.link_seasons, before.outside_videos, before.feeds, before.title)

    lines = [json.loads(line) for line in client.get("/api/collections/workshop/creator/match").text.splitlines()]
    match = lines[-1]["match"]
    assert (match["title"], match["creatorSlug"]) == ("Northwind Workshop", None)

    response = client.post("/api/collections/workshop/creator", json={"lookupId": match["lookupId"]})
    assert response.status_code == 200, response.text

    page = client.get("/api/creators/workshop").json()
    assert [collection["slug"] for collection in page["collections"]] == ["workshop"]
    assert [account["site"]["key"] for account in page["accounts"]] == ["tube"]
    after = _collection(session, "workshop")
    assert (after.link_seasons, after.outside_videos, after.feeds) == settings[:3]
    assert after.author_name == "Northwind Workshop"


def test_a_list_collection_cannot_join_a_creator(client, session):
    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})
    _add("cabin", PLAYLIST)

    response = client.post("/api/collections/cabin/creator", json={"creatorSlug": "workshop"})

    assert response.status_code == 422
    assert "Only a channel can be in a creator" in response.text
    assert _collection(session, "cabin").creator_id is None


def test_leaving_a_creator_keeps_the_collection_as_it_is(client, session):
    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})

    assert client.delete("/api/collections/workshop/creator").status_code == 200

    assert _collection(session, "workshop").creator_id is None
    assert client.get("/api/creators/workshop").json()["collections"] == []


def test_the_creator_page_offers_the_shows_of_a_host_with_what_the_library_has(client, session):
    _add("workbench", SHOW, source_key="cast")
    assert client.post("/api/collections/workbench/creator", json={}).status_code == 200

    page = client.get("/api/creators/nw-live").json()
    assert [account["offers"] for account in page["accounts"]] == [True]
    offerings = client.get("/api/creators/nw-live/offerings").json()["accounts"][0]["offerings"]

    assert [(item["title"], item["collectionSlug"], item["collectionJoined"]) for item in offerings] == [
        ("The Workbench", "workbench", True), ("The Garage", None, False),
    ]
    assert offerings[0]["names"]["singular"] == "show"


def test_combined_creators_keep_every_collection_and_split_by_site_again(client, session):
    _add("workshop", ROOT)
    _add("workbench", SHOW, source_key="cast")
    client.post("/api/collections/workshop/creator", json={})
    client.post("/api/collections/workbench/creator", json={})

    combined = client.post("/api/creators/workshop/combine", json={"otherSlug": "nw-live"}).json()
    assert sorted(collection["slug"] for collection in combined["collections"]) == ["workbench", "workshop"]

    cast = next(account for account in combined["accounts"] if account["site"]["key"] == "cast")
    split = client.post(f"/api/creators/workshop/accounts/{cast['id']}/split").json()
    assert [collection["slug"] for collection in split["collections"]] == ["workbench"]
    assert [collection["slug"] for collection in client.get("/api/creators/workshop").json()["collections"]] == ["workshop"]


def test_deleting_a_creator_keeps_its_collections(client, session):
    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})

    assert client.delete("/api/creators/workshop").status_code == 204

    collection = _collection(session, "workshop")
    assert collection is not None and collection.creator_id is None
