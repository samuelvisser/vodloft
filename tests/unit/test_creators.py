"""Creators: a creator groups collections and movies, and joining or leaving one changes nothing a collection holds. A
collection is a channel or one list, told by its link, and either can be in a creator on a Site with creators."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from progress_plan import PlanTracker, StageSpec
from sources import CreatorDetails, Feature, ListOrder, Names, SectionKind, SectionRef, SectionRole, SectionType, Site, registry
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
        "tube", "Tube", ("tube.example",), creators=True, section_types=(VIDEOS, SHORTS, PLAYLISTS), link_seasons=True, list_order=ListOrder.OLDEST_FIRST,
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
    # Its lists are on, each whole, and the channel season holds the whole channel, as a channel shows itself.
    assert (collection.link_seasons, collection.outside_videos, collection.repeat_videos, collection.loose_videos) == (
        "on", "add", "each_season", "everything",
    )


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


def test_a_playlist_joins_the_creator_of_the_channel_that_made_it_beside_the_channel(client, session):
    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})
    _add("cabin", PLAYLIST)
    assert client.get("/api/collections/cabin").json()["canJoinCreator"] is True

    lines = [json.loads(line) for line in client.get("/api/collections/cabin/creator/match").text.splitlines()]
    match = lines[-1]["match"]
    # The playlist's creator is the channel that made it, who is in the Library already.
    assert (match["title"], match["creatorSlug"]) == ("Northwind Workshop", "workshop")
    response = client.post("/api/collections/cabin/creator", json={"lookupId": match["lookupId"]})
    assert response.status_code == 200, response.text

    page = client.get("/api/creators/workshop").json()
    # Two collections of one creator: the playlist stays a collection of its own, not a season of the channel.
    assert sorted(collection["slug"] for collection in page["collections"]) == ["cabin", "workshop"]
    assert _collection(session, "cabin").kind == "list"


def test_a_playlist_joins_another_creator_in_the_library_by_hand(client, session):
    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})
    _add("cabin", PLAYLIST)

    response = client.post("/api/collections/cabin/creator", json={"creatorSlug": "workshop"})

    assert response.status_code == 200, response.text
    assert _collection(session, "cabin").creator_id == _collection(session, "workshop").creator_id


def test_a_collection_of_only_playlists_joins_a_creator_by_hand_only(client, session):
    from backend.db.core import run_write_transaction
    from backend.services.collections import add_links_only_collection
    from backend.types.collection_types import CollectionType

    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})
    run_write_transaction(lambda s: add_links_only_collection(s, title="Mixtape", collection_type=CollectionType.SERIES).slug)
    assert client.get("/api/collections/mixtape").json()["canJoinCreator"] is True

    # It has no link of its own to find a creator behind.
    response = client.post("/api/collections/mixtape/creator", json={})
    assert response.status_code == 422
    assert "has no link of its own" in response.text

    response = client.post("/api/collections/mixtape/creator", json={"creatorSlug": "workshop"})
    assert response.status_code == 200, response.text
    assert _collection(session, "mixtape").creator_id == _collection(session, "workshop").creator_id


def test_a_collection_on_a_site_without_creators_cannot_join_one(client, session):
    _add("workshop", ROOT)
    client.post("/api/collections/workshop/creator", json={})
    _add("plain", "https://plain.example/everything", source_key="plain")
    assert client.get("/api/collections/plain").json()["canJoinCreator"] is False

    response = client.post("/api/collections/plain/creator", json={"creatorSlug": "workshop"})

    assert response.status_code == 422
    assert "Plain has no creators VODLoft can add" in response.text
    assert _collection(session, "plain").creator_id is None


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


def test_a_site_can_have_a_channel_collection_put_a_video_in_the_first_of_its_lists_only(tube, session, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(CreatorSource, "sites", (replace(CreatorSource.sites[0], whole_lists=False),))
    _add("workshop", ROOT)
    collection = _collection(session, "workshop")
    assert (collection.link_seasons, collection.repeat_videos) == ("on", "one_season")


def test_a_channel_collection_on_a_site_without_list_seasons_keeps_its_seasons_as_they_are(tube, session, monkeypatch):
    # Such as a show on The Daily Wire: its seasons are the Site's own, so no default about lists applies.
    from dataclasses import replace

    monkeypatch.setattr(CreatorSource, "sites", (replace(CreatorSource.sites[0], link_seasons=False),))
    _add("workshop", ROOT)

    collection = _collection(session, "workshop")
    assert (collection.link_seasons, collection.repeat_videos) == ("off", "one_season")


def test_a_channel_collection_says_in_words_what_its_seasons_will_be(tube, session):
    from backend.services.link_seasons import seasons_plan

    _add("workshop", ROOT)

    plan = seasons_plan(_collection(session, "workshop"))
    assert plan.startswith("Every creator playlist becomes a season in VODLoft.")
    assert "also those in a playlist" in plan


def test_a_creators_own_ytdlp_options_reach_its_collections_before_their_own(client, session, monkeypatch):
    from backend.services.source_options import ytdlp_call_options
    from sources import ytdlp_runner

    _add("workshop", ROOT)
    lines = [json.loads(line) for line in client.get("/api/collections/workshop/creator/match").text.splitlines()]
    joined = client.post("/api/collections/workshop/creator", json={"lookupId": lines[-1]["match"]["lookupId"]})
    assert joined.status_code == 200, joined.text

    # A Source without your own yt-dlp options has no field for them.
    page = client.get("/api/creators/workshop").json()
    assert (page["takesYtdlpOptions"], page["ytdlpOptions"]) == (False, "")
    refused = client.patch("/api/creators/workshop", json={"ytdlpOptions": "--impersonate chrome"})
    assert refused.status_code == 422

    monkeypatch.setattr(CreatorSource, "features", CreatorSource.features | {Feature.YTDLP_OPTIONS})
    assert client.get("/api/creators/workshop").json()["takesYtdlpOptions"] is True
    # The same lines are refused as for a collection.
    blocked = client.patch("/api/creators/workshop", json={"ytdlpOptions": "-o out.mp4"})
    assert blocked.status_code == 422
    assert blocked.json()["detail"][0]["loc"][-1] == "ytdlpOptions"

    saved = client.patch("/api/creators/workshop", json={"ytdlpOptions": "--impersonate chrome\n--proxy http://a:1\n"})
    assert saved.json()["ytdlpOptions"] == "--impersonate chrome\n--proxy http://a:1"
    # Leaving them out keeps them.
    assert client.patch("/api/creators/workshop", json={"genre": "DIY"}).json()["ytdlpOptions"].startswith("--impersonate")

    collection = _collection(session, "workshop")
    collection.ytdlp_options = "--proxy http://b:2"
    assert collection.ytdlp_option_texts == ("--impersonate chrome\n--proxy http://a:1", "--proxy http://b:2")
    with ytdlp_call_options("tube", *collection.ytdlp_option_texts, session=session):
        # yt-dlp takes the last of an option given twice: the collection's own proxy.
        assert ytdlp_runner.command()[-6:] == (
            "--impersonate", "chrome", "--proxy", "http://a:1", "--proxy", "http://b:2",
        )
    session.rollback()
