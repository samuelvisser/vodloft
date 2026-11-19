"""Creators: looking one up, what each preset does with its sections, and adding it with its collections."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from sources import (
    CreatorDetails, CreatorPreset, Feature, SectionKind, SectionRef, SectionRole, Site, registry,
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


class CreatorSource(ListedSource):
    id = "tube"
    name = "Tube"
    domains = ("tube.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site(
        "tube", "Tube", ("tube.example",), creators=True,
        creator_presets=(CreatorPreset.ONE_SHOW, CreatorPreset.PER_LIST, CreatorPreset.PICK), link_seasons=True,
    ),)

    def is_creator_page(self, url):
        return url in (ROOT, f"{ROOT}/videos")

    def creator_of(self, url):
        return ROOT if url.startswith("https://tube.example/") else None

    def creator_details(self, ref, progress=lambda step: None):
        progress("Reading the creator")
        return CreatorDetails(
            ref="UCworkshop", url=ROOT, title="Northwind Workshop", handle="@workshop", facts=("1.2M subscribers",),
            sections=SECTIONS,
        )


@pytest.fixture
def tube(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(CreatorSource())


@pytest.fixture
def client(tube, session):
    from backend.api.endpoints.creators import router as creator_router_module

    from fastapi.responses import JSONResponse

    from backend.services.errors import ServiceError

    app = FastAPI()
    app.add_exception_handler(ServiceError, lambda _request, exc: JSONResponse(status_code=422, content={"detail": str(exc)}))
    from backend.api.endpoints.collections import router as collection_router_module

    app.include_router(creator_router_module.router, prefix="/api")
    app.include_router(collection_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _lookup(client):
    """The creator lookup's steps, and the creator it found."""
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]
    return [line["step"] for line in lines[:-1]], lines[-1]["creator"]


def _plan(body, preset):
    plan = next(item["plan"] for item in body["presets"] if item["key"] == preset)
    return {item["ref"]: item["target"] for item in plan}


def test_one_show_folds_feeds_and_playlists_into_one_collection(client):
    steps, body = _lookup(client)

    assert steps == ["Looking the creator up", "Reading the creator", "Checking what is in your library already"]
    assert (body["title"], body["creatorLabel"], body["facts"]) == ("Northwind Workshop", "creator", ["1.2M subscribers"])
    # The creator's own collection lists its Shorts and Live too, and its playlists are seasons of it.
    assert _plan(body, "one_show") == {
        "videos": "main", "shorts": "main", "streams": "main", "PLcabin": "main", "PLtools": "main",
        # Only members can watch it, so it is left for the user to pick.
        "PLmembers": "skip",
    }
    assert _plan(body, "per_list")["PLtools"] == "own"
    assert set(_plan(body, "pick").values()) == {"skip"}


def test_adding_a_creator_makes_its_collection_with_its_playlists_as_seasons(client, session):
    from backend.db.models import Collection

    plan = [
        {"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"}, {"ref": "PLcabin", "target": "main"},
        {"ref": "shorts", "target": "own"}, {"ref": "PLtools", "target": "own"}, {"ref": "PLmembers", "target": "skip"},
    ]
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan})

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
    assert main.sharing_url == f"{ROOT}/videos" and main.creator.title == "Northwind Workshop"
    from backend.api.models.collection import CollectionAPIRead

    assert CollectionAPIRead.model_validate(main).creator_slug == "workshop"
    # Every playlist of the creator is known to it, and the ones picked are its seasons.
    assert main.link_seasons == "selected"
    assert [(link.ref, link.enabled) for link in main.lists] == [
        ("PLcabin", True), ("PLtools", False), ("PLmembers", False),
    ]
    # The section nobody keeps stays on the creator page.
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

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "PLtools", "target": "own"}]})
    assert session.scalars(select(Collection.title).order_by(Collection.id)).all() == ["My tools"]
    assert client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": []}).status_code == 422

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "shorts", "target": "own"}]})
    page = client.get("/api/creators/workshop").json()
    # The creator's page shows it is kept in the collection it was already in.
    kept = next(section for section in page["sections"] if section["ref"] == "PLtools")
    assert (kept["collectionSlug"], kept["collectionTitle"]) == ("tools", "My tools")


def test_the_creator_list_counts_its_collections(client):
    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "shorts", "target": "own"}]})

    [creator] = client.get("/api/creators").json()

    assert (creator["title"], creator["collectionCount"], creator["site"]["name"]) == ("Northwind Workshop", 1, "Tube")


def test_a_youtube_creator_is_read_from_its_tabs_and_playlists_under_the_link_people_paste(monkeypatch):
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

    details = YtDlpSource().creator_details("https://www.youtube.com/@workshop/videos")

    assert (details.ref, details.url, details.handle, details.facts) == (
        "UCworkshop", "https://www.youtube.com/@workshop", "@workshop", ("1.2M subscribers",),
    )
    assert (details.avatar_url, details.banner_url) == ("https://img.example/a", "https://img.example/b")
    # A creator without livestreams or Shorts has only its Videos feed.
    assert [(section.ref, section.kind, section.url) for section in details.sections] == [
        ("videos", SectionKind.FEED, "https://www.youtube.com/@workshop/videos"),
        ("PLcabin", SectionKind.LIST, "https://www.youtube.com/playlist?list=PLcabin"),
    ]


def test_a_youtube_creator_page_opens_with_its_collections(client, monkeypatch):
    from sources import ytdlp_runner as runner

    pages = {
        "https://www.youtube.com/@workshop/videos": {
            "channel_id": "UCworkshop", "channel": "Northwind Workshop", "uploader_id": "@workshop", "entries": [{"id": "v1"}],
        },
        "https://www.youtube.com/@workshop/streams": {"entries": []},
        "https://www.youtube.com/@workshop/playlists": {"entries": [{"id": "PLcabin", "title": "Building the Cabin"}]},
    }

    def run_json(*args, **_kwargs):
        if args[-1] not in pages:
            raise runner.YtDlpError("This channel does not have a shorts tab")
        return pages[args[-1]]

    monkeypatch.setattr(runner, "run_json", run_json)
    plan = [{"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "own"}]
    added = client.post(
        "/api/creators", json={"sourceKey": "ytdlp", "url": "https://www.youtube.com/@workshop", "sections": plan},
    )
    assert added.status_code == 201, added.text

    page = client.get(f"/api/creators/{added.json()['slug']}")

    assert page.status_code == 200, page.text
    assert page.json()["title"] == "Northwind Workshop"
    assert [(c["title"], c["links"]) for c in page.json()["collections"]] == [
        ("Northwind Workshop", ["Videos"]), ("Building the Cabin", ["Building the Cabin"]),
    ]


NEW_LIST = SectionRef(
    "PLbarn", "https://tube.example/playlist?list=PLbarn", "Timber Frame Barn", SectionKind.LIST, kind_label="Playlist", item_count=4,
)


def _one_show(client):
    plan = [{"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"}, {"ref": "shorts", "target": "own"}]
    assert client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan}).status_code == 201


def _follow(session, tube, sections):
    from backend.db.models import Creator
    from backend.services.creators import follow_creator
    from datetime import datetime, timezone

    creator = session.scalar(select(Creator))
    details = tube.creator_details(ROOT)
    from dataclasses import replace

    result = follow_creator(session, creator, replace(details, sections=sections), now=datetime.now(timezone.utc))
    session.commit()
    return result


def test_a_new_playlist_waits_for_a_choice_and_says_so(client, session, tube):
    from backend.db.models import NotificationEvent
    from backend.services.notifications.emitters import creator_sections_found

    _one_show(client)
    result = _follow(session, tube, (NEW_LIST, *SECTIONS))
    creator_sections_found(session, result.asked[0].creator, result.asked)
    session.commit()

    assert [section.ref for section in result.asked] == ["PLbarn"]
    event = session.scalar(select(NotificationEvent))
    assert (event.title, event.url) == ("New playlist on Northwind Workshop", "/creator/workshop")
    page = client.get("/api/creators/workshop").json()
    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "new"

    # Adding it to the creator's own collection makes it a season of it.
    page = client.post("/api/creators/workshop/sections", json={"sections": [{"ref": "PLbarn", "target": "main"}]}).json()
    assert next(c for c in page["collections"] if c["slug"] == page["mainCollectionSlug"])["links"] == [
        "Timber Frame Barn", "Videos", "Live",
    ]
    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "known"


def test_the_creator_asks_about_a_new_playlist_also_when_its_collection_has_playlist_seasons(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    _follow(session, tube, SECTIONS)
    client.post("/api/creators/workshop/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    # The creator alone finds new playlists and asks; its own collection follows the creator's setting.
    assert [section.ref for section in result.asked] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert (main.link_seasons, main.new_link_seasons) == ("selected", "ask")


def test_a_creator_set_to_make_new_playlists_seasons_adds_them_to_its_own_collection(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    client.post("/api/creators/workshop/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})
    assert client.patch("/api/creators/workshop", json={"newSections": "season"}).status_code == 200

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert [section.ref for section in result.added] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    session.refresh(main)
    assert main.new_link_seasons == "add"
    assert {link.ref: link.enabled for link in main.lists}["PLbarn"] is True


def test_a_creator_set_to_add_new_playlists_as_collections_adds_them(client, session, tube):
    _one_show(client)
    assert client.patch("/api/creators/workshop", json={"newSections": "own", "genre": "DIY"}).status_code == 200

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert [section.ref for section in result.added] == ["PLbarn"]
    page = client.get("/api/creators/workshop").json()
    barn = next(c for c in page["collections"] if c["slug"] == "PLbarn")
    assert barn["links"] == ["Timber Frame Barn"]
    from backend.db.models import Collection

    assert session.scalar(select(Collection.genre).where(Collection.slug == "PLbarn")) == "DIY"


def test_ignoring_a_new_playlist_keeps_it_on_the_creator_page(client, session, tube):
    _one_show(client)
    _follow(session, tube, (NEW_LIST, *SECTIONS))

    page = client.post("/api/creators/workshop/sections", json={"sections": [{"ref": "PLbarn", "target": "skip"}]}).json()

    assert next(s for s in page["sections"] if s["ref"] == "PLbarn")["status"] == "ignored"
    # The next look does not ask again.
    assert _follow(session, tube, (NEW_LIST, *SECTIONS)).asked == []


def test_the_creators_genre_follows_to_collections_that_had_it(client, session):
    from backend.db.models import Collection

    _one_show(client)
    session.execute(Collection.__table__.update().where(Collection.slug == "UCworkshop-shorts").values(genre="Shorts"))
    session.commit()

    client.patch("/api/creators/workshop", json={"newSections": "ask", "genre": "Woodworking", "contentRating": "TV-G"})

    session.expire_all()
    genres = dict(session.execute(select(Collection.slug, Collection.genre)).all())
    assert genres == {"UCworkshop": "Woodworking", "UCworkshop-shorts": "Shorts"}


def test_the_daily_look_finds_new_playlists_on_every_creator_and_asks_about_them(client, session, tube, monkeypatch):
    from dataclasses import replace

    from backend.db.models import Creator, NotificationEvent
    from task_manager.tasks.workers.follow_creators.service import run_follow_creators

    _one_show(client)
    details = tube.creator_details(ROOT)
    monkeypatch.setattr(tube, "creator_details", lambda _ref: replace(details, sections=(NEW_LIST, *SECTIONS), facts=("1.3M subscribers",)))

    result = run_follow_creators(session)

    assert result.data["found"] == 1 and result.data["added"] == 0
    session.expire_all()
    creator = session.scalar(select(Creator))
    assert creator.facts == ["1.3M subscribers"] and creator.checked_at is not None
    assert session.scalar(select(NotificationEvent.title)) == "New playlist on Northwind Workshop"
    # Looking again finds nothing new and does not ask twice.
    assert run_follow_creators(session).data["found"] == 0


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


def test_adding_a_collection_to_a_creator_adds_the_creator_and_matches_its_link(client, session):
    from backend.db.models import Creator, Collection

    _plain_collection(session, "tools", SECTIONS[4].url)

    match = client.get("/api/collections/tools/creator/match").json()
    assert (match["title"], match["creatorSlug"]) == ("Northwind Workshop", None)
    assert (match["sectionTitle"], match["keptBy"]) == ("Tool Reviews", None)

    response = client.post("/api/collections/tools/creator")
    assert response.status_code == 200, response.text
    assert response.json()["creatorSlug"] == "workshop"
    creator = session.scalar(select(Creator))
    assert creator.main_collection is None
    page = client.get("/api/creators/workshop").json()
    assert [(c["title"], c["links"]) for c in page["collections"]] == [("My tools", ["Tool Reviews"])]
    # The creator's other sections are not in the library, and nothing asks about them.
    assert {s["ref"]: (s["collectionSlug"], s["status"]) for s in page["sections"]}["PLcabin"] == (None, "known")
    assert session.scalar(select(Collection).where(Collection.slug == "tools")).episodes == []


def test_a_collection_of_a_section_another_collection_keeps_cannot_join(client, session):
    from backend.db.models import Collection

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "shorts", "target": "own"},
    ]})
    _plain_collection(session, "tools", SECTIONS[4].url)
    _plain_collection(session, "my-videos", ROOT)

    assert client.post("/api/collections/tools/creator").status_code == 200
    # The creator's own collection keeps all its uploads already.
    match = client.get("/api/collections/my-videos/creator/match").json()
    assert match["creatorSlug"] == "workshop"
    assert (match["keptBy"], match["sectionTitle"]) == ("Northwind Workshop", None)
    refused = client.post("/api/collections/my-videos/creator")
    assert refused.status_code == 422 and "already keeps" in refused.json()["detail"]
    assert session.scalar(select(Collection.creator_id).where(Collection.slug == "my-videos")) is None


def test_removing_a_collection_from_its_creator_makes_it_plain_again(client, session):
    from backend.db.models import Creator, Collection

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    leave = client.get("/api/collections/UCworkshop/creator/leave").json()
    assert leave == {"creatorTitle": "Northwind Workshop"}

    response = client.delete("/api/collections/UCworkshop/creator")
    assert response.status_code == 200, response.text
    assert response.json()["creatorSlug"] is None
    session.expire_all()
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert main.creator_id is None and session.scalar(select(Creator)).main_collection_id is None
    page = client.get("/api/creators/workshop").json()
    assert [c["title"] for c in page["collections"]] == ["Tool Reviews"]
    # Its link is still the Videos page, so the creator page shows it kept there.
    assert next(s for s in page["sections"] if s["ref"] == "videos")["collectionSlug"] == "UCworkshop"

    # It can join again.
    assert client.post("/api/collections/UCworkshop/creator").status_code == 200

def test_a_failed_lookup_ends_with_what_went_wrong(client, tube, monkeypatch):
    def refuse(ref, progress=lambda step: None):
        progress("Reading the creator")
        raise ValueError("This creator does not exist")

    monkeypatch.setattr(tube, "creator_details", refuse)
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})

    assert [json.loads(line) for line in response.text.splitlines()] == [
        {"step": "Looking the creator up", "creatorLabel": "creator"},
        {"step": "Reading the creator"},
        {"error": "Could not look up this creator: This creator does not exist"},
    ]


def test_an_artists_collections_hold_music(client, tube, session, monkeypatch):
    from dataclasses import replace

    from backend.db.models import Collection

    details = tube.creator_details(ROOT)
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=lambda step: None: replace(details, music=True))
    _steps, body = _lookup(client)
    assert body["music"] is True

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "PLcabin", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    assert response.status_code == 201, response.text
    assert set(session.scalars(select(Collection.type))) == {"music"}


def test_a_site_names_its_creators_in_its_own_words(client, tube, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(type(tube), "sites", (replace(tube.sites[0], creator_label="host"),))
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]

    assert lines[0] == {"step": "Looking the host up", "creatorLabel": "host"}
    assert lines[-1]["creator"]["creatorLabel"] == "host"


def test_a_playlist_that_is_a_season_of_the_creators_collection_moves_to_a_collection_that_joins(client, session):
    from backend.db.models import Collection, CollectionList

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})
    _plain_collection(session, "cabin", SECTIONS[3].url)

    match = client.get("/api/collections/cabin/creator/match").json()
    assert (match["sectionTitle"], match["keptBy"]) == ("Building the Cabin", None)
    assert match["overlaps"] == [
        {"ref": "PLcabin", "title": "Building the Cabin", "keptBy": "Northwind Workshop", "canMoveHere": True},
    ]
    # Without the user's choice the playlist stays where it is, and the collection can't join.
    refused = client.post("/api/collections/cabin/creator")
    assert refused.status_code == 422 and "already keeps" in refused.json()["detail"]

    joined = client.post("/api/collections/cabin/creator", json={"moveHere": ["PLcabin"]})

    assert joined.status_code == 200, joined.text
    session.expire_all()
    assert session.scalar(select(Collection.creator_id).where(Collection.slug == "cabin")) is not None
    main_cabin = session.scalar(
        select(CollectionList).join(Collection).where(Collection.slug == "UCworkshop", CollectionList.ref == "PLcabin")
    )
    assert main_cabin.enabled is False


def test_the_seasons_window_of_a_creators_collection_follows_the_creator(client, session):
    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})

    view = client.get("/api/collections/UCworkshop/season-settings").json()
    assert (view["creatorSlug"], view["creatorTitle"], view["linkSeasons"]) == ("workshop", "Northwind Workshop", "selected")
    body = {
        "seasons": [{"id": season["id"], "name": season["name"]} for season in view["seasons"]],
        "customSeasonOrder": False, "linkSeasons": "all", "newLinkSeasons": "add",
        "playlists": [{"id": playlist["id"], "enabled": playlist["enabled"]} for playlist in view["playlists"]],
    }
    refused = client.put("/api/collections/UCworkshop/season-settings", json=body)
    assert refused.status_code == 422 and "decides which of its playlists" in refused.text
    saved = client.put("/api/collections/UCworkshop/season-settings", json={**body, "linkSeasons": "selected"}).json()
    # What happens with a new playlist stays the creator's choice.
    assert saved["newLinkSeasons"] == "ask"


def test_an_artists_creator_is_called_an_artist(client, tube, session, monkeypatch):
    from dataclasses import replace

    details = tube.creator_details(ROOT)
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=lambda step: None: replace(details, music=True))
    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "PLcabin", "target": "main"}]})

    assert client.get("/api/creators/workshop").json()["creatorLabel"] == "artist"
    assert [creator["creatorLabel"] for creator in client.get("/api/creators").json()] == ["artist"]


def test_a_collection_from_another_link_can_join_a_creator_in_the_library(client, session):
    from backend.db.models import Collection

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "videos", "target": "main"}]})
    # Such as an artist's music videos on their label's creator.
    _plain_collection(session, "music-videos", "https://tube.test/@label/playlist/PLvideos")

    response = client.post("/api/collections/music-videos/creator", json={"creatorSlug": "workshop"})
    assert response.status_code == 200, response.text
    assert response.json()["creatorSlug"] == "workshop"
    page = client.get("/api/creators/workshop").json()
    assert {c["title"] for c in page["collections"]} == {"Northwind Workshop", "My music-videos"}
    session.expire_all()
    assert session.scalar(select(Collection.sharing_url).where(Collection.slug == "music-videos")).endswith("PLvideos")

    # A collection of one of the creator's own sections joins through its link instead.
    _plain_collection(session, "tools", SECTIONS[4].url)
    refused = client.post("/api/collections/tools/creator", json={"creatorSlug": "workshop"})
    assert refused.status_code == 422 and "behind its link" in refused.text
    assert "not in the Library" in client.post("/api/collections/tools/creator", json={"creatorSlug": "nowhere"}).text
