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
        "tube", "Tube", ("tube.example",), channels=True,
        channel_presets=(ChannelPreset.ONE_SHOW, ChannelPreset.PER_LIST, ChannelPreset.PICK), link_seasons=True,
    ),)

    def is_channel_page(self, url):
        return url in (ROOT, f"{ROOT}/videos")

    def channel_of(self, url):
        return ROOT if url.startswith("https://tube.example/") else None

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
    from backend.api.endpoints.collections import router as collection_router_module

    app.include_router(channel_router_module.router, prefix="/api")
    app.include_router(collection_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _lookup(client):
    """The channel lookup's steps, and the channel it found."""
    response = client.post("/api/channels/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]
    return [line["step"] for line in lines[:-1]], lines[-1]["channel"]


def _plan(body, preset):
    plan = next(item["plan"] for item in body["presets"] if item["key"] == preset)
    return {item["ref"]: item["target"] for item in plan}


def test_one_show_folds_feeds_and_playlists_into_one_collection(client):
    steps, body = _lookup(client)

    assert steps == ["Looking the channel up", "Reading the channel", "Checking what is in your library already"]
    assert (body["title"], body["channelLabel"], body["facts"]) == ("Northwind Workshop", "channel", ["1.2M subscribers"])
    # The channel's own collection lists its Shorts and Live too, and its playlists are seasons of it.
    assert _plan(body, "one_show") == {
        "videos": "main", "shorts": "main", "streams": "main", "PLcabin": "main", "PLtools": "main",
        # Only members can watch it, so it is left for the user to pick.
        "PLmembers": "skip",
    }
    assert _plan(body, "per_list")["PLtools"] == "own"
    assert set(_plan(body, "pick").values()) == {"skip"}


def test_adding_a_channel_makes_its_collection_with_its_playlists_as_seasons(client, session):
    from backend.db.models import Collection

    plan = [
        {"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"}, {"ref": "PLcabin", "target": "main"},
        {"ref": "shorts", "target": "own"}, {"ref": "PLtools", "target": "own"}, {"ref": "PLmembers", "target": "skip"},
    ]
    response = client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": plan})

    assert response.status_code == 201, response.text
    page = response.json()
    assert page["slug"] == "workshop"
    # Its Videos page lists the Shorts too, so the Shorts collection of their own is the user's extra choice.
    assert [(c["title"], c["links"]) for c in page["collections"]] == [
        ("Northwind Workshop", ["Videos", "Live", "Building the Cabin"]),
        ("Northwind Workshop Shorts", ["Shorts"]),
        ("Tool Reviews", ["Tool Reviews"]),
    ]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert main.sharing_url == f"{ROOT}/videos" and main.channel.title == "Northwind Workshop"
    from backend.api.models.collection import CollectionAPIRead

    assert CollectionAPIRead.model_validate(main).channel_slug == "workshop"
    # Every playlist of the channel is known to it, and the ones picked are its seasons.
    assert main.link_seasons == "selected"
    assert [(link.ref, link.enabled) for link in main.lists] == [
        ("PLcabin", True), ("PLtools", False), ("PLmembers", False),
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
    plan = [{"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"}, {"ref": "shorts", "target": "own"}]
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

    # Adding it to the channel's own collection makes it a season of it.
    page = client.post("/api/channels/workshop/sections", json={"sections": [{"ref": "PLbarn", "target": "main"}]}).json()
    assert next(c for c in page["collections"] if c["slug"] == page["mainCollectionSlug"])["links"] == [
        "Timber Frame Barn", "Videos", "Live",
    ]
    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "known"


def test_the_channel_asks_about_a_new_playlist_also_when_its_collection_has_playlist_seasons(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    _follow(session, tube, SECTIONS)
    client.post("/api/channels/workshop/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    # The channel alone finds new playlists and asks; its own collection follows the channel's setting.
    assert [section.ref for section in result.asked] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert (main.link_seasons, main.new_link_seasons) == ("selected", "ask")


def test_a_channel_set_to_make_new_playlists_seasons_adds_them_to_its_own_collection(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    client.post("/api/channels/workshop/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})
    assert client.patch("/api/channels/workshop", json={"newSections": "season"}).status_code == 200

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert [section.ref for section in result.added] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    session.refresh(main)
    assert main.new_link_seasons == "add"
    assert {link.ref: link.enabled for link in main.lists}["PLbarn"] is True


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


def _plain_collection(session, slug, url):
    from backend.db.models import Collection

    session.add(Collection(
        uuid=f"uuid-{slug}", slug=slug, source_key="tube", title=f"My {slug}", sharing_url=url,
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="x", author_slug="x",
    ))
    session.commit()


def test_adding_a_collection_to_a_channel_adds_the_channel_and_matches_its_link(client, session):
    from backend.db.models import Channel, Collection

    _plain_collection(session, "tools", SECTIONS[4].url)

    match = client.get("/api/collections/tools/channel/match").json()
    assert (match["title"], match["channelSlug"]) == ("Northwind Workshop", None)
    assert (match["sectionTitle"], match["keptBy"]) == ("Tool Reviews", None)

    response = client.post("/api/collections/tools/channel")
    assert response.status_code == 200, response.text
    assert response.json()["channelSlug"] == "workshop"
    channel = session.scalar(select(Channel))
    assert channel.main_collection is None
    page = client.get("/api/channels/workshop").json()
    assert [(c["title"], c["links"]) for c in page["collections"]] == [("My tools", ["Tool Reviews"])]
    # The channel's other sections are not in the library, and nothing asks about them.
    assert {s["ref"]: (s["collectionSlug"], s["status"]) for s in page["sections"]}["PLcabin"] == (None, "known")
    assert session.scalar(select(Collection).where(Collection.slug == "tools")).episodes == []


def test_a_collection_of_a_section_another_collection_keeps_cannot_join(client, session):
    from backend.db.models import Collection

    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "shorts", "target": "own"},
    ]})
    _plain_collection(session, "tools", SECTIONS[4].url)
    _plain_collection(session, "my-videos", ROOT)

    assert client.post("/api/collections/tools/channel").status_code == 200
    # The channel's own collection keeps all its uploads already.
    match = client.get("/api/collections/my-videos/channel/match").json()
    assert match["channelSlug"] == "workshop"
    assert (match["keptBy"], match["sectionTitle"]) == ("Northwind Workshop", None)
    refused = client.post("/api/collections/my-videos/channel")
    assert refused.status_code == 422 and "already keeps" in refused.json()["detail"]
    assert session.scalar(select(Collection.channel_id).where(Collection.slug == "my-videos")) is None


def test_removing_a_collection_from_its_channel_makes_it_plain_again(client, session):
    from backend.db.models import Channel, Collection

    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    leave = client.get("/api/collections/UCworkshop/channel/leave").json()
    assert leave == {"channelTitle": "Northwind Workshop"}

    response = client.delete("/api/collections/UCworkshop/channel")
    assert response.status_code == 200, response.text
    assert response.json()["channelSlug"] is None
    session.expire_all()
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert main.channel_id is None and session.scalar(select(Channel)).main_collection_id is None
    page = client.get("/api/channels/workshop").json()
    assert [c["title"] for c in page["collections"]] == ["Tool Reviews"]
    # Its link is still the Videos page, so the channel page shows it kept there.
    assert next(s for s in page["sections"] if s["ref"] == "videos")["collectionSlug"] == "UCworkshop"

    # It can join again.
    assert client.post("/api/collections/UCworkshop/channel").status_code == 200

def test_a_failed_lookup_ends_with_what_went_wrong(client, tube, monkeypatch):
    def refuse(ref, progress=lambda step: None):
        progress("Reading the channel")
        raise ValueError("This channel does not exist")

    monkeypatch.setattr(tube, "channel_details", refuse)
    response = client.post("/api/channels/lookup", json={"sourceKey": "tube", "url": ROOT})

    assert [json.loads(line) for line in response.text.splitlines()] == [
        {"step": "Looking the channel up", "channelLabel": "channel"},
        {"step": "Reading the channel"},
        {"error": "Could not look up this channel: This channel does not exist"},
    ]


def test_an_artists_collections_hold_music(client, tube, session, monkeypatch):
    from dataclasses import replace

    from backend.db.models import Collection

    details = tube.channel_details(ROOT)
    monkeypatch.setattr(tube, "channel_details", lambda ref, progress=lambda step: None: replace(details, music=True))
    _steps, body = _lookup(client)
    assert body["music"] is True

    response = client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "PLcabin", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    assert response.status_code == 201, response.text
    assert set(session.scalars(select(Collection.type))) == {"music"}


def test_a_site_names_its_channels_in_its_own_words(client, tube, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(type(tube), "sites", (replace(tube.sites[0], channel_label="host"),))
    response = client.post("/api/channels/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]

    assert lines[0] == {"step": "Looking the host up", "channelLabel": "host"}
    assert lines[-1]["channel"]["channelLabel"] == "host"


def test_a_playlist_that_is_a_season_of_the_channels_collection_moves_to_a_collection_that_joins(client, session):
    from backend.db.models import Collection, CollectionList

    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})
    _plain_collection(session, "cabin", SECTIONS[3].url)

    match = client.get("/api/collections/cabin/channel/match").json()
    assert (match["sectionTitle"], match["keptBy"]) == ("Building the Cabin", None)
    assert match["overlaps"] == [
        {"ref": "PLcabin", "title": "Building the Cabin", "keptBy": "Northwind Workshop", "canMoveHere": True},
    ]
    # Without the user's choice the playlist stays where it is, and the collection can't join.
    refused = client.post("/api/collections/cabin/channel")
    assert refused.status_code == 422 and "already keeps" in refused.json()["detail"]

    joined = client.post("/api/collections/cabin/channel", json={"moveHere": ["PLcabin"]})

    assert joined.status_code == 200, joined.text
    session.expire_all()
    assert session.scalar(select(Collection.channel_id).where(Collection.slug == "cabin")) is not None
    main_cabin = session.scalar(
        select(CollectionList).join(Collection).where(Collection.slug == "UCworkshop", CollectionList.ref == "PLcabin")
    )
    assert main_cabin.enabled is False


def test_the_seasons_window_of_a_channels_collection_follows_the_channel(client, session):
    client.post("/api/channels", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})

    view = client.get("/api/collections/UCworkshop/season-settings").json()
    assert (view["channelSlug"], view["channelTitle"], view["linkSeasons"]) == ("workshop", "Northwind Workshop", "selected")
    body = {
        "seasons": [{"id": season["id"], "name": season["name"]} for season in view["seasons"]],
        "customSeasonOrder": False, "linkSeasons": "all", "newLinkSeasons": "add",
        "playlists": [{"id": playlist["id"], "enabled": playlist["enabled"]} for playlist in view["playlists"]],
    }
    refused = client.put("/api/collections/UCworkshop/season-settings", json=body)
    assert refused.status_code == 422 and "decides which of its playlists" in refused.text
    saved = client.put("/api/collections/UCworkshop/season-settings", json={**body, "linkSeasons": "selected"}).json()
    # What happens with a new playlist stays the channel's choice.
    assert saved["newLinkSeasons"] == "ask"
