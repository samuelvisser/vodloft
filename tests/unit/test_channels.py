"""Channels: looking one up, what each preset does with its sections, and adding it with its collections."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from sources import (
    ChannelDetails, ChannelPreset, Feature, SectionKind, SectionRef, SectionRole, Site, registry,
)
from test_ytdlp_collections import ListedSource, session  # noqa: F401

ROOT = "https://tube.example/@workshop"
SECTIONS = (
    SectionRef("videos", f"{ROOT}/videos", "Videos", SectionKind.FEED),
    SectionRef("shorts", f"{ROOT}/shorts", "Shorts", SectionKind.FEED, SectionRole.SHORT),
    SectionRef("streams", f"{ROOT}/streams", "Live", SectionKind.FEED, SectionRole.LIVE),
    SectionRef("PLcabin", "https://tube.example/playlist?list=PLcabin", "Building the Cabin", SectionKind.LIST, item_count=38),
    SectionRef("PLtools", "https://tube.example/playlist?list=PLtools", "Tool Reviews", SectionKind.LIST, item_count=61),
    SectionRef("PLmembers", "https://tube.example/playlist?list=PLmembers", "Members' Cuts", SectionKind.LIST, access="members"),
)


class ChannelSource(ListedSource):
    id = "tube"
    name = "Tube"
    domains = ("tube.example",)
    features = ListedSource.features | {Feature.CHANNELS}
    sites = (Site(
        "tube", "Tube", ("tube.example",), channel_label="channel",
        channel_presets=(ChannelPreset.ONE_SHOW, ChannelPreset.PER_LIST, ChannelPreset.PICK),
    ),)

    def channel_details(self, ref, progress=lambda step: None):
        progress("Reading the channel")
        return ChannelDetails(
            ref="UCworkshop", url=ROOT, title="Northwind Workshop", handle="@workshop", facts=("1.2M subscribers",),
            sections=SECTIONS,
        )


@pytest.fixture
def tube(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(ChannelSource())


@pytest.fixture
def client(tube, session):
    from backend.api.endpoints.channels import router as channel_router_module

    from fastapi.responses import JSONResponse

    from backend.services.errors import ServiceError

    app = FastAPI()
    app.add_exception_handler(ServiceError, lambda _request, exc: JSONResponse(status_code=422, content={"detail": str(exc)}))
    app.include_router(channel_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _lookup(client):
    """The channel lookup's steps, and the channel it found."""
    response = client.post("/api/channels/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]
    return [line["step"] for line in lines[:-1]], lines[-1]["channel"]


def _plan(body, preset):
    plan = next(item["plan"] for item in body["presets"] if item["key"] == preset)
    return {item["ref"]: (item["target"], item["placement"]) for item in plan}


def test_one_show_folds_feeds_and_playlists_into_one_collection_and_keeps_shorts_apart(client):
    steps, body = _lookup(client)

    assert steps == ["Reading the channel", "Checking what is in your library already"]
    assert (body["title"], body["channelLabel"], body["facts"]) == ("Northwind Workshop", "channel", ["1.2M subscribers"])
    assert _plan(body, "one_show") == {
        "videos": ("main", "site_seasons"),
        "shorts": ("own", "site_seasons"),
        "streams": ("main", "site_seasons"),
        "PLcabin": ("main", "one_season"),
        "PLtools": ("main", "one_season"),
        # Only members can watch it, so it is left for the user to pick.
        "PLmembers": ("skip", "site_seasons"),
    }
    assert _plan(body, "per_list")["PLtools"] == ("own", "site_seasons")
    assert set(_plan(body, "pick").values()) == {("skip", "site_seasons")}
    # Lists first as the Site lists them, then Live, Shorts and Videos, which holds all of the channel's uploads.
    assert body["claimOrder"] == ["PLcabin", "PLtools", "PLmembers", "streams", "shorts", "videos"]


def test_adding_a_channel_makes_its_collections_with_their_links_in_the_channels_order(client, session):
    from backend.db.models import Collection

    plan = [
        {"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"},
        {"ref": "PLcabin", "target": "main", "placement": "one_season"},
        {"ref": "shorts", "target": "own"}, {"ref": "PLtools", "target": "own"},
        {"ref": "PLmembers", "target": "skip"},
    ]
    response = client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": plan})

    assert response.status_code == 201, response.text
    page = response.json()
    assert page["slug"] == "workshop"
    assert [(c["title"], c["links"]) for c in page["collections"]] == [
        ("Northwind Workshop", ["Building the Cabin", "Live", "Videos"]),
        ("Northwind Workshop Shorts", ["Shorts"]),
        ("Tool Reviews", ["Tool Reviews"]),
    ]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert main.sharing_url == f"{ROOT}/videos" and main.channel.title == "Northwind Workshop"
    from backend.api.models.collection import CollectionAPIRead

    assert CollectionAPIRead.model_validate(main).channel_slug == "workshop"
    assert [(link.title, link.placement, link.position) for link in main.links] == [
        ("Building the Cabin", "one_season", 0), ("Live", "site_seasons", 3), ("Videos", "site_seasons", 5),
    ]
    # The section nobody keeps stays on the channel page.
    left = {section["ref"]: section["collectionSlug"] for section in page["sections"]}
    assert left["PLmembers"] is None and left["PLtools"] == "PLtools"


def test_a_section_already_in_the_library_stays_where_it_is(client, session):
    from backend.db.models import Collection

    session.add(Collection(
        uuid="uuid-tools", slug="tools", source_key="tube", title="My tools", sharing_url=SECTIONS[4].url,
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="x", author_slug="x",
    ))
    session.commit()

    _steps, body = _lookup(client)
    assert next(s for s in body["sections"] if s["ref"] == "PLtools")["collectionSlug"] == "tools"

    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "PLtools", "target": "own"}]})
    assert session.scalars(select(Collection.title).order_by(Collection.id)).all() == ["My tools"]
    assert client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": []}).status_code == 422

    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "shorts", "target": "own"}]})
    page = client.get("/api/channels/workshop").json()
    # The channel's page shows it is kept in the collection it was already in.
    kept = next(section for section in page["sections"] if section["ref"] == "PLtools")
    assert (kept["collectionSlug"], kept["collectionTitle"]) == ("tools", "My tools")


def test_the_channel_list_counts_its_collections(client):
    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "shorts", "target": "own"}]})

    [channel] = client.get("/api/channels").json()

    assert (channel["title"], channel["collectionCount"], channel["site"]["name"]) == ("Northwind Workshop", 1, "Tube")


def test_a_youtube_channel_is_read_from_its_tabs_and_playlists_under_the_link_people_paste(monkeypatch):
    from sources import ytdlp_runner as runner
    from sources.ytdlp.source import YtDlpSource

    pages = {
        "https://www.youtube.com/@workshop/videos": {
            "channel_id": "UCworkshop", "channel": "Northwind Workshop", "uploader_id": "@workshop",
            "channel_follower_count": 1_234_567, "entries": [{"id": "v1"}],
            "thumbnails": [{"id": "avatar_uncropped", "url": "https://img.example/a"}, {"id": "banner_uncropped", "url": "https://img.example/b"}],
        },
        "https://www.youtube.com/@workshop/streams": {"entries": []},
        "https://www.youtube.com/@workshop/playlists": {"entries": [{"id": "PLcabin", "title": "Building the Cabin"}]},
    }

    def run_json(*args, **_kwargs):
        if args[-1] not in pages:
            raise runner.YtDlpError("This channel does not have a shorts tab")
        return pages[args[-1]]

    monkeypatch.setattr(runner, "run_json", run_json)

    details = YtDlpSource().channel_details("https://www.youtube.com/@workshop/videos")

    assert (details.ref, details.url, details.handle, details.facts) == (
        "UCworkshop", "https://www.youtube.com/@workshop", "@workshop", ("1.2M subscribers",),
    )
    assert (details.avatar_url, details.banner_url) == ("https://img.example/a", "https://img.example/b")
    # A channel without livestreams or Shorts has only its Videos feed.
    assert [(section.ref, section.kind, section.url) for section in details.sections] == [
        ("videos", SectionKind.FEED, "https://www.youtube.com/@workshop/videos"),
        ("PLcabin", SectionKind.LIST, "https://www.youtube.com/playlist?list=PLcabin"),
    ]


NEW_LIST = SectionRef(
    "PLbarn", "https://tube.example/playlist?list=PLbarn", "Timber Frame Barn", SectionKind.LIST, kind_label="Playlist", item_count=4,
)


def _one_show(client):
    plan = [
        {"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"},
        {"ref": "PLcabin", "target": "main", "placement": "one_season"}, {"ref": "shorts", "target": "own"},
    ]
    assert client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": plan}).status_code == 201


def _follow(session, tube, sections):
    from backend.db.models import Channel
    from backend.services.channels import follow_channel
    from datetime import datetime, timezone

    channel = session.scalar(select(Channel))
    details = tube.channel_details(ROOT)
    from dataclasses import replace

    result = follow_channel(session, channel, replace(details, sections=sections), now=datetime.now(timezone.utc))
    session.commit()
    return result


def test_a_new_playlist_waits_for_a_choice_and_says_so(client, session, tube):
    from backend.db.models import NotificationEvent
    from backend.services.notifications.emitters import channel_sections_found

    _one_show(client)
    result = _follow(session, tube, (NEW_LIST, *SECTIONS))
    channel_sections_found(session, result.asked[0].channel, result.asked)
    session.commit()

    assert [section.ref for section in result.asked] == ["PLbarn"]
    event = session.scalar(select(NotificationEvent))
    assert (event.title, event.url) == ("New playlist on Northwind Workshop", "/channel/workshop")
    page = client.get("/api/channels/workshop").json()
    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "new"

    # Adding it as a season puts it first in the channel's order, in the channel's own collection.
    page = client.post("/api/channels/workshop/sections", json={"sections": [
        {"ref": "PLbarn", "target": "main", "placement": "one_season"},
    ]}).json()
    assert [entry["ref"] for entry in page["order"]] == ["PLbarn", "PLcabin", "streams", "shorts", "videos"]
    assert next(c for c in page["collections"] if c["slug"] == page["mainCollectionSlug"])["links"] == [
        "Timber Frame Barn", "Building the Cabin", "Live", "Videos",
    ]
    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "known"


def test_a_channel_set_to_add_new_playlists_as_collections_adds_them(client, session, tube):
    _one_show(client)
    assert client.patch("/api/channels/workshop", json={"newSections": "own", "genre": "DIY"}).status_code == 200

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert [section.ref for section in result.added] == ["PLbarn"]
    page = client.get("/api/channels/workshop").json()
    barn = next(c for c in page["collections"] if c["slug"] == "PLbarn")
    assert barn["links"] == ["Timber Frame Barn"]
    from backend.db.models import Collection

    assert session.scalar(select(Collection.genre).where(Collection.slug == "PLbarn")) == "DIY"


def test_ignoring_a_new_playlist_keeps_it_on_the_channel_page(client, session, tube):
    _one_show(client)
    _follow(session, tube, (NEW_LIST, *SECTIONS))

    page = client.post("/api/channels/workshop/sections", json={"sections": [{"ref": "PLbarn", "target": "skip"}]}).json()

    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "ignored"
    # The next look does not ask again.
    assert _follow(session, tube, (NEW_LIST, *SECTIONS)).asked == []


def test_the_channels_genre_follows_to_collections_that_had_it(client, session):
    from backend.db.models import Collection

    _one_show(client)
    session.execute(Collection.__table__.update().where(Collection.slug == "UCworkshop-shorts").values(genre="Shorts"))
    session.commit()

    client.patch("/api/channels/workshop", json={"newSections": "ask", "genre": "Woodworking", "contentRating": "TV-G"})

    session.expire_all()
    genres = dict(session.execute(select(Collection.slug, Collection.genre)).all())
    assert genres == {"UCworkshop": "Woodworking", "UCworkshop-shorts": "Shorts"}


def test_reordering_a_channel_checks_every_section_is_named_once(client):
    _one_show(client)
    page = client.get("/api/channels/workshop").json()
    order = [entry["ref"] for entry in page["order"]]
    assert order == ["PLcabin", "streams", "shorts", "videos"]

    assert client.patch("/api/channels/workshop", json={"newSections": "ask", "order": ["videos"]}).status_code == 422
    page = client.patch("/api/channels/workshop", json={"newSections": "ask", "order": ["shorts", "PLcabin", "streams", "videos"]}).json()
    assert [entry["ref"] for entry in page["order"]] == ["shorts", "PLcabin", "streams", "videos"]


def test_the_daily_look_finds_new_playlists_on_every_channel_and_asks_about_them(client, session, tube, monkeypatch):
    from dataclasses import replace

    from backend.db.models import Channel, NotificationEvent
    from task_manager.tasks.workers.follow_channels.service import run_follow_channels

    _one_show(client)
    details = tube.channel_details(ROOT)
    monkeypatch.setattr(tube, "channel_details", lambda _ref: replace(details, sections=(NEW_LIST, *SECTIONS), facts=("1.3M subscribers",)))

    result = run_follow_channels(session)

    assert result.data["found"] == 1 and result.data["added"] == 0
    session.expire_all()
    channel = session.scalar(select(Channel))
    assert channel.facts == ["1.3M subscribers"] and channel.checked_at is not None
    assert session.scalar(select(NotificationEvent.title)) == "New playlist on Northwind Workshop"
    # Looking again finds nothing new and does not ask twice.
    assert run_follow_channels(session).data["found"] == 0


def test_a_new_section_that_is_already_in_the_library_needs_no_choice(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    session.add(Collection(
        uuid="uuid-barn", slug="barn", source_key="tube", title="My barn", sharing_url=NEW_LIST.url,
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="x", author_slug="x",
    ))
    session.commit()

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert result.asked == [] and result.added == []

def test_a_failed_lookup_ends_with_what_went_wrong(client, tube, monkeypatch):
    def refuse(ref, progress=lambda step: None):
        progress("Reading the channel")
        raise ValueError("This channel does not exist")

    monkeypatch.setattr(tube, "channel_details", refuse)
    response = client.post("/api/channels/lookup", json={"sourceKey": "tube", "url": ROOT})

    assert [json.loads(line) for line in response.text.splitlines()] == [
        {"step": "Reading the channel"},
        {"error": "Could not look up this channel: This channel does not exist"},
    ]
