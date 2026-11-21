"""Creators: looking one up, what each preset does with its sections, and adding it with its collections."""
from __future__ import annotations

import json
import threading

import pytest
from progress_plan import PlanTracker, StageSpec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sources import (
    CreatorDetails, CreatorPreset, Feature, Names, SectionKind, SectionRef, SectionRole, SectionType, Site, registry,
)
from test_ytdlp_collections import ListedSource, session  # noqa: F401

ROOT = "https://tube.example/@workshop"
VIDEOS = SectionType("videos", SectionKind.FEED, Names("video", "videos"))
LIVE = SectionType("live", SectionKind.FEED, Names("livestream", "livestreams"), role=SectionRole.LIVE)
SHORTS = SectionType("shorts", SectionKind.FEED, Names("short", "shorts"), role=SectionRole.SHORT)
PLAYLISTS = SectionType("list", SectionKind.LIST, Names("playlist", "playlists"))
SHOWS = SectionType("show", SectionKind.SHOW, Names("show", "shows"))
MOVIES = SectionType("movie", SectionKind.ITEM, Names("movie", "movies"))
SECTIONS = (
    SectionRef("videos", f"{ROOT}/videos", VIDEOS),
    SectionRef("shorts", f"{ROOT}/shorts", SHORTS),
    SectionRef("streams", f"{ROOT}/streams", LIVE),
    SectionRef("PLcabin", "https://tube.example/playlist?list=PLcabin", PLAYLISTS, "Building the Cabin", item_count=38),
    SectionRef("PLtools", "https://tube.example/playlist?list=PLtools", PLAYLISTS, "Tool Reviews", item_count=61),
    SectionRef("PLmembers", "https://tube.example/playlist?list=PLmembers", PLAYLISTS, "Members' Cuts", access="members"),
)


class CreatorSource(ListedSource):
    id = "tube"
    name = "Tube"
    domains = ("tube.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site(
        "tube", "Tube", ("tube.example",), creators=True, section_types=(VIDEOS, LIVE, SHORTS, PLAYLISTS),
        creator_presets=(CreatorPreset.ONE_SHOW, CreatorPreset.PER_LIST, CreatorPreset.PICK), link_seasons=True,
    ),)

    def is_creator_page(self, url):
        return url in (ROOT, f"{ROOT}/videos")

    def creator_of(self, url):
        return ROOT if url.startswith("https://tube.example/") else None

    def creator_details(self, ref, plan=None):
        plan = plan or PlanTracker()
        plan.add(StageSpec(id="read", code="read_creator", label="Reading the creator"))
        with plan.running("read"):
            pass
        return CreatorDetails(
            ref="UCworkshop", url=ROOT, title="Northwind Workshop", handle="@workshop", facts=("1.2M subscribers",),
            sections=SECTIONS,
        )


@pytest.fixture(autouse=True)
def forget_lookups(monkeypatch):
    """Each test looks its creators up afresh."""
    from backend.api.endpoints.creators import service

    monkeypatch.setattr(service, "_lookups", {})


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
    from backend.api.endpoints.episodes import episode_router

    app.include_router(episode_router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _steps(lines):
    """The steps of the last plan a lookup sent, each with its state."""
    plan = [line["plan"] for line in lines if "plan" in line][-1]
    return [(stage["label"], stage["state"]) for stage in plan["stages"]]


def _lookup(client):
    """The creator lookup's steps, and the creator it found."""
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]
    return [label for label, _state in _steps(lines)], lines[-1]["creator"]


def _match(client, slug):
    """The creator the collection's link is of, after the steps of looking it up, and the steps."""
    lines = [json.loads(line) for line in client.get(f"/api/collections/{slug}/creator/match").text.splitlines()]
    return lines[-1]["match"], [label for label, _state in _steps(lines)]


def _plan(body, preset):
    plan = next(item["plan"] for item in body["presets"] if item["key"] == preset)
    return {item["ref"]: item["target"] for item in plan}


def test_one_show_folds_feeds_and_playlists_into_one_collection(client):
    steps, body = _lookup(client)

    assert steps == ["Reading the creator", "Checking what is in your library already"]
    assert (body["title"], body["creatorNames"]["singular"], body["facts"]) == ("Northwind Workshop", "creator", ["1.2M subscribers"])
    # The creator's own collection lists its Shorts and Live too, and its playlists are seasons of it.
    assert _plan(body, "one_show") == {
        "videos": "main", "shorts": "main", "streams": "main", "PLcabin": "main", "PLtools": "main",
        # Only members can watch it, so it is left for the user to pick.
        "PLmembers": "exclude",
    }
    assert _plan(body, "per_list")["PLtools"] == "own"
    assert set(_plan(body, "pick").values()) == {"exclude"}


def test_adding_a_creator_makes_its_collection_with_its_playlists_as_seasons(client, session):
    from backend.db.models import Collection

    plan = [
        {"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"}, {"ref": "PLcabin", "target": "main"},
        {"ref": "shorts", "target": "own"}, {"ref": "PLtools", "target": "own"}, {"ref": "PLmembers", "target": "exclude"},
    ]
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan})

    assert response.status_code == 201, response.text
    page = response.json()
    assert page["slug"] == "workshop"
    # Its Videos page lists the Shorts too, so the Shorts collection of their own is the user's extra choice.
    assert [(c["title"], c["links"]) for c in page["collections"]] == [
        ("Northwind Workshop", ["Videos", "Livestreams", "Building the Cabin"]),
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
    left = {section["ref"]: section["collectionSlug"] for section in page["accounts"][0]["sections"]}
    assert left["PLmembers"] is None and left["PLtools"] == "PLtools"


def test_adding_a_creator_puts_sections_into_the_new_collection_of_another(client, session):
    from backend.db.models import Collection

    plan = [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "own"},
        {"ref": "PLtools", "target": "main", "intoRef": "PLcabin"}, {"ref": "shorts", "target": "main", "intoRef": "PLcabin"},
        {"ref": "streams", "target": "exclude"}, {"ref": "PLmembers", "target": "exclude"},
    ]
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan})

    assert response.status_code == 201, response.text
    assert [(c["title"], c["links"]) for c in response.json()["collections"]] == [
        ("Northwind Workshop", ["Videos"]),
        ("Building the Cabin", ["Shorts", "Building the Cabin", "Tool Reviews"]),
    ]
    cabin = session.scalar(select(Collection).where(Collection.slug == "PLcabin"))
    # The playlist's own collection gathers now: its own playlist and the Tool Reviews are seasons of it, it lists the
    # Shorts, and it knows no other playlist of the creator.
    assert cabin.feeds == ["shorts"]
    assert {(link.ref, link.enabled, link.as_season) for link in cabin.lists} == {
        ("PLcabin", True, True), ("PLtools", True, True),
    }
    assert cabin.episode_identifier == "seasonal"


def test_adding_a_deleted_creator_again_takes_back_their_collection(client, session):
    from backend.db.models import Collection

    plan = [{"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"}]
    assert client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan}).status_code == 201
    assert client.delete("/api/creators/workshop").status_code == 204

    # The collection stays, a plain one; adding the creator again makes it theirs instead of a second one of its link.
    _steps, body = _lookup(client)
    assert {section["ref"]: section["collectionSlug"] for section in body["sections"]}["videos"] == "UCworkshop"
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLtools", "target": "main"},
    ]})
    assert response.status_code == 201, response.text
    assert [(c["slug"], c["links"]) for c in response.json()["collections"]] == [
        ("UCworkshop", ["Videos", "Building the Cabin", "Tool Reviews"]),
    ]
    assert session.scalar(select(func.count()).select_from(Collection)) == 1


def test_a_section_only_joins_the_new_collection_of_a_section_that_gets_one(client):
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLtools", "target": "main", "intoRef": "PLcabin"},
    ]})
    assert response.status_code == 422
    assert response.json()["detail"] == "Tool Reviews can only go into a new collection of another feed or list"


def test_adding_a_creator_uses_what_its_lookup_found(client, tube, monkeypatch):
    _steps, found = _lookup(client)
    asked = []
    look_up = tube.creator_details
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=None: asked.append(ref) or look_up(ref))

    plan = [{"ref": "videos", "target": "main"}]
    added = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan, "lookupId": found["lookupId"]})

    assert added.status_code == 201, added.text
    assert added.json()["title"] == "Northwind Workshop" and asked == []
    # A lookup id of another link is not used for this one.
    other = client.post("/api/creators", json={
        "sourceKey": "tube", "url": f"{ROOT}/videos", "sections": plan, "lookupId": found["lookupId"],
    })
    assert asked == [f"{ROOT}/videos"] and other.status_code == 422


def test_a_creator_looked_up_ahead_is_found_by_the_users_lookup(client, tube, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from backend.api.endpoints.creators import service

    calls = []
    looked_up = tube.creator_details

    def creator_details(ref, progress=lambda step: None):
        calls.append(ref)
        return looked_up(ref, progress)

    monkeypatch.setattr(tube, "creator_details", creator_details)
    with ThreadPoolExecutor(max_workers=1) as ahead:
        monkeypatch.setattr(service, "_ahead", ahead)
        service.look_up_creator_ahead("tube", ROOT)
        ahead.submit(lambda: None).result()

    _steps, body = _lookup(client)

    assert body["title"] == "Northwind Workshop"
    assert calls == [ROOT]


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
    kept = next(section for section in page["accounts"][0]["sections"] if section["ref"] == "PLtools")
    assert (kept["collectionSlug"], kept["collectionTitle"]) == ("tools", "My tools")


def test_the_creator_list_counts_its_collections(client):
    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "shorts", "target": "own"}]})

    [creator] = client.get("/api/creators").json()

    assert (creator["title"], creator["collectionCount"], creator["accounts"][0]["site"]["name"]) == ("Northwind Workshop", 1, "Tube")


def test_a_creator_counts_as_opened_when_its_page_or_one_of_its_collections_is(client):
    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [{"ref": "shorts", "target": "own"}]})
    [creator] = client.get("/api/creators").json()
    assert (creator["openCount"], creator["lastOpenedAt"]) == (0, None)

    assert client.post(f"/api/creators/{creator['slug']}/opened").status_code == 204
    [after_page] = client.get("/api/creators").json()
    assert after_page["openCount"] == 1 and after_page["lastOpenedAt"] is not None

    [collection] = client.get(f"/api/creators/{creator['slug']}").json()["collections"]
    assert client.post(f"/api/collections/{collection['slug']}/opened").status_code == 204
    [after_collection] = client.get("/api/creators").json()
    assert after_collection["openCount"] == 2
    assert after_collection["lastOpenedAt"] >= after_page["lastOpenedAt"]

    assert client.post("/api/creators/nobody/opened").status_code == 404


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


def test_a_youtube_playlist_shows_the_picture_youtube_serves(monkeypatch):
    from sources import ytdlp_runner as runner
    from sources.ytdlp.source import YtDlpSource

    signed = "https://i9.ytimg.com/s_p/PLretro/landscape_sddefault.jpg?sqp=abc&rs=def"
    pages = {
        "https://www.youtube.com/@workshop/videos": {"channel_id": "UCworkshop", "channel": "Northwind Workshop", "uploader_id": "@workshop", "entries": []},
        "https://www.youtube.com/@workshop/playlists": {"entries": [{"id": "PLretro", "title": "Retro Tech", "thumbnails": [
            {"url": "https://i9.ytimg.com/s_p/PLretro/landscape_mqdefault.jpg?sqp=abc&rs=ghi", "width": 320},
            {"url": signed, "width": 800},
            # yt-dlp's widest form has no signature, and YouTube answers it with a grey placeholder.
            {"url": "https://i9.ytimg.com/s_p/PLretro/landscape_maxresdefault.jpg", "width": 2560},
        ]}]},
    }

    def run_json(*args, **_kwargs):
        if args[-1] not in pages:
            raise runner.YtDlpError("This channel does not have that tab")
        return pages[args[-1]]

    monkeypatch.setattr(runner, "run_json", run_json)

    details = YtDlpSource().creator_details("https://www.youtube.com/@workshop/videos")

    assert [section.image_url for section in details.sections if section.ref == "PLretro"] == [signed]


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
    "PLbarn", "https://tube.example/playlist?list=PLbarn", PLAYLISTS, "Timber Frame Barn", item_count=4,
)


def _one_show(client):
    plan = [{"ref": "videos", "target": "main"}, {"ref": "streams", "target": "main"}, {"ref": "shorts", "target": "own"}]
    assert client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan}).status_code == 201


def _follow(session, tube, sections):
    from backend.db.models import Creator
    from backend.services.creators import follow_account
    from datetime import datetime, timezone

    creator = session.scalar(select(Creator))
    details = tube.creator_details(ROOT)
    from dataclasses import replace

    result = follow_account(session, creator.accounts[0], replace(details, sections=sections), now=datetime.now(timezone.utc))
    session.commit()
    return result


def test_a_new_playlist_waits_for_a_choice_and_says_so(client, session, tube):
    from backend.db.models import NotificationEvent
    from backend.services.notifications.emitters import creator_sections_found

    _one_show(client)
    result = _follow(session, tube, (NEW_LIST, *SECTIONS))
    creator_sections_found(session, result.asked[0].account.creator, result.asked)
    session.commit()

    assert [section.ref for section in result.asked] == ["PLbarn"]
    event = session.scalar(select(NotificationEvent))
    assert (event.title, event.url) == ("New playlist on Northwind Workshop", "/edit-creator/workshop")
    page = client.get("/api/creators/workshop").json()
    assert next(s for s in page["accounts"][0]["sections"] if s["ref"] == "PLbarn")["status"] == "new"

    # Adding it to the creator's own collection makes it a season of it.
    page = client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLbarn", "target": "main"}]}).json()
    assert next(c for c in page["collections"] if c["slug"] == page["accounts"][0]["mainCollectionSlug"])["links"] == [
        "Timber Frame Barn", "Videos", "Livestreams",
    ]
    assert next(s for s in page["accounts"][0]["sections"] if s["ref"] == "PLbarn")["status"] == "known"


def test_a_playlist_added_as_a_collection_of_its_own_takes_the_type_and_identification_the_user_chose(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    _follow(session, tube, SECTIONS)
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert (main.type, main.episode_identifier) == ("series", "seasonal")

    page = client.post("/api/creators/workshop/accounts/1/sections", json={
        "sections": [{"ref": "PLcabin", "target": "own"}], "type": "podcast", "episodeIdentifier": "date_based",
    }).json()

    slug = next(s for s in page["accounts"][0]["sections"] if s["ref"] == "PLcabin")["collectionSlug"]
    session.expire_all()
    added = session.scalar(select(Collection).where(Collection.slug == slug))
    assert (added.type, added.episode_identifier) == ("podcast", "date_based")


def test_the_creator_asks_about_a_new_playlist_also_when_its_collection_has_playlist_seasons(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    _follow(session, tube, SECTIONS)
    client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    # The creator alone finds new playlists and asks; its own collection follows the creator's setting.
    assert [section.ref for section in result.asked] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    assert (main.link_seasons, main.new_lists) == ("selected", {"list": "ask"})


def test_a_creator_set_to_make_new_playlists_seasons_adds_them_to_its_own_collection(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})
    assert client.patch("/api/creators/workshop", json={"newLists": {"tube": {"list": "season"}}}).status_code == 200

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert [section.ref for section in result.added] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    session.refresh(main)
    assert main.new_lists == {"list": "add"}
    assert {link.ref: link.enabled for link in main.lists}["PLbarn"] is True


def test_a_creator_set_to_add_new_playlists_as_collections_adds_them(client, session, tube):
    _one_show(client)
    assert client.patch("/api/creators/workshop", json={"newLists": {"tube": {"list": "own"}}, "genre": "DIY"}).status_code == 200

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

    page = client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLbarn", "target": "exclude"}]}).json()

    assert next(s for s in page["accounts"][0]["sections"] if s["ref"] == "PLbarn")["status"] == "ignored"
    # The next look does not ask again.
    assert _follow(session, tube, (NEW_LIST, *SECTIONS)).asked == []


def test_a_hidden_playlist_shows_on_the_creator_page_again(client, session, tube):
    _one_show(client)
    client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLtools", "target": "exclude"}]})

    page = client.post("/api/creators/workshop/accounts/1/sections/show", json={"refs": ["PLtools", "PLcabin"]})

    assert page.status_code == 200, page.text
    statuses = {s["ref"]: (s["status"], s["collectionSlug"]) for s in page.json()["accounts"][0]["sections"]}
    # It is back on the creator page, and still not in the library; one that was not hidden stays as it was.
    assert statuses["PLtools"] == ("known", None)
    assert statuses["PLcabin"] == ("known", None)
    assert client.post("/api/creators/workshop/accounts/1/sections/show", json={"refs": ["PLnone"]}).status_code == 422


def test_the_creators_genre_follows_to_collections_that_had_it(client, session):
    from backend.db.models import Collection

    _one_show(client)
    session.execute(Collection.__table__.update().where(Collection.slug == "UCworkshop-shorts").values(genre="Shorts"))
    session.commit()

    client.patch("/api/creators/workshop", json={"newLists": {"tube": {"list": "ask"}}, "genre": "Woodworking", "contentRating": "TV-G"})

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
    assert creator.facts == ["1.3M subscribers"] and creator.accounts[0].checked_at is not None
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


def test_adding_a_collection_to_a_creator_adds_the_creator_and_matches_its_link(client, session, tube, monkeypatch):
    from backend.db.models import Creator, Collection

    _plain_collection(session, "tools", SECTIONS[4].url)

    match, steps = _match(client, "tools")
    assert steps == ["Finding the creator behind the link", "Reading the creator", "Checking what is in your library already"]
    assert (match["title"], match["creatorSlug"]) == ("Northwind Workshop", None)
    assert (match["sectionTitle"], match["keptBy"]) == ("Tool Reviews", None)

    # Adding it uses what the lookup found, without asking the Site again.
    asked = []
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=None: asked.append(ref))
    response = client.post("/api/collections/tools/creator", json={"lookupId": match["lookupId"]})
    assert response.status_code == 200, response.text
    assert response.json()["creatorSlug"] == "workshop" and asked == []
    creator = session.scalar(select(Creator))
    assert creator.accounts[0].main_collection is None
    page = client.get("/api/creators/workshop").json()
    assert [(c["title"], c["links"]) for c in page["collections"]] == [("My tools", ["Tool Reviews"])]
    # The creator's other sections are not in the library, and nothing asks about them.
    assert {s["ref"]: (s["collectionSlug"], s["status"]) for s in page["accounts"][0]["sections"]}["PLcabin"] == (None, "known")
    assert session.scalar(select(Collection).where(Collection.slug == "tools")).episodes == []


def test_a_collection_of_a_section_another_collection_keeps_cannot_join(client, session):
    from backend.db.models import Collection

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "shorts", "target": "own"},
    ]})
    _plain_collection(session, "tools", SECTIONS[4].url)
    _plain_collection(session, "my-videos", ROOT)

    joined = client.post("/api/collections/tools/creator")
    assert joined.status_code == 200, joined.text
    # The creator's own collection keeps all its uploads already.
    match, _steps = _match(client, "my-videos")
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
    assert main.creator_id is None and session.scalar(select(Creator)).accounts[0].main_collection_id is None
    page = client.get("/api/creators/workshop").json()
    assert [c["title"] for c in page["collections"]] == ["Tool Reviews"]
    # Its link is still the Videos page, so the creator page shows it kept there.
    assert next(s for s in page["accounts"][0]["sections"] if s["ref"] == "videos")["collectionSlug"] == "UCworkshop"

    # It can join again.
    assert client.post("/api/collections/UCworkshop/creator").status_code == 200

def test_a_failed_lookup_ends_with_what_went_wrong(client, tube, monkeypatch):
    def refuse(ref, plan):
        plan.add(StageSpec(id="read", code="read_creator", label="Reading the creator"))
        with plan.running("read"):
            raise ValueError("This creator does not exist")

    monkeypatch.setattr(tube, "creator_details", refuse)
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]

    assert lines[0] == {"creatorNames": {"singular": "creator", "plural": "creators", "a": "a creator"}}
    assert _steps(lines) == [("Reading the creator", "failed")]
    assert lines[-1] == {"error": "Could not look up this creator: This creator does not exist"}


def test_a_creator_found_a_moment_ago_shows_no_steps(client, tube):
    """Pasting a creator's link looks them up ahead; once that is done, the Add creator page answers at once."""
    from backend.api.endpoints.creators import service

    service.look_up_creator("tube", ROOT, None)
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]

    assert _steps(lines) == [("Checking what is in your library already", "completed")]
    assert lines[-1]["creator"]["title"] == "Northwind Workshop"


def test_a_lookup_that_joins_one_already_running_follows_its_steps(client, tube, monkeypatch):
    """Pasting a creator's link starts looking them up; the Add creator page then follows that lookup, counts and all."""
    from backend.api.endpoints.creators import service

    details = tube.creator_details(ROOT)
    started, release = threading.Event(), threading.Event()

    def slow(ref, plan):
        plan.add(StageSpec(id="read", code="read_lists", label="Reading the playlists"))
        with plan.running("read"):
            plan.progress("read", 0.5, done=1, total=2)
            started.set()
            release.wait(5)
            plan.progress("read", 1.0, done=2, total=2)
        return details

    monkeypatch.setattr(tube, "creator_details", slow)
    ahead = threading.Thread(target=service.look_up_creator, args=("tube", ROOT, None))
    ahead.start()
    assert started.wait(5)
    threading.Timer(0.2, release.set).start()
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    ahead.join(5)
    lines = [json.loads(line) for line in response.text.splitlines()]

    plans = [line["plan"] for line in lines if "plan" in line]
    # It hears the step the lookup is on as it joins, with how far it is, and each count after.
    counts = [(stage["done"], stage["total"]) for plan in plans for stage in plan["stages"] if stage["id"] == "read"]
    assert counts[0] == (1, 2) and counts[-1] == (2, 2)
    assert _steps(lines) == [("Reading the playlists", "completed"), ("Checking what is in your library already", "completed")]
    assert lines[-1]["creator"]["title"] == "Northwind Workshop"


def test_an_artists_collections_hold_music(client, tube, session, monkeypatch):
    from dataclasses import replace

    from backend.db.models import Collection

    details = tube.creator_details(ROOT)
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=lambda step: None: replace(details, music=True, music_known=True))
    _steps, body = _lookup(client)
    assert (body["music"], body["musicKnown"]) == (True, True)

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "PLcabin", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    assert response.status_code == 201, response.text
    assert set(session.scalars(select(Collection.type))) == {"music"}


def test_the_user_decides_whether_a_creator_the_site_isnt_sure_of_is_an_artist(client, tube, session, monkeypatch):
    from dataclasses import replace

    from backend.db.models import Collection

    details = tube.creator_details(ROOT)
    guessed = replace(details, music=True, music_reason="It has releases on YouTube Music")
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=lambda step: None: guessed)
    _steps, body = _lookup(client)
    assert (body["music"], body["musicKnown"], body["musicReason"]) == (True, False, "It has releases on YouTube Music")

    # The user says it is a channel like any other, despite the guess.
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "type": "series", "sections": [
        {"ref": "PLcabin", "target": "main"},
    ]})
    assert response.status_code == 201, response.text
    assert set(session.scalars(select(Collection.type))) == {"series"}


def test_an_artist_presets_keep_only_the_lists_the_site_marks_as_albums(client, tube, monkeypatch):
    from dataclasses import replace

    import sys

    albums = SectionType("album", SectionKind.LIST, Names("album", "albums"), albums=True)
    playlists = SectionType("playlist", SectionKind.LIST, Names("playlist", "playlists"))
    monkeypatch.setattr(type(tube), "sites", (replace(tube.sites[0], section_types=(VIDEOS, LIVE, SHORTS, albums, playlists)),))
    sections = tuple(
        replace(section, type=albums if section.ref == "PLcabin" else playlists) if section.kind is SectionKind.LIST else section
        for section in SECTIONS
    )
    monkeypatch.setattr(sys.modules[__name__], "SECTIONS", sections)

    _steps, body = _lookup(client)
    assert (body["albumNames"]["plural"], body["skippedListNames"]["plural"]) == ("albums", "playlists")
    music = lambda preset: {
        item["ref"]: item["target"] for item in next(p for p in body["presets"] if p["key"] == preset)["musicPlan"]
    }
    # The album becomes an album; the playlist starts skipped with both presets.
    assert (music("one_show")["PLcabin"], music("one_show")["PLtools"]) == ("main", "exclude")
    assert (music("per_list")["PLcabin"], music("per_list")["PLtools"]) == ("own", "exclude")
    # A creator who isn't an artist keeps every list.
    assert (_plan(body, "one_show")["PLcabin"], _plan(body, "one_show")["PLtools"]) == ("main", "main")


def test_an_artist_on_a_video_site_keeps_only_their_albums(client, session):
    from backend.db.models import Collection
    from backend.types.link_season_types import OutsideVideos

    _steps, body = _lookup(client)
    for preset in ("one_show", "per_list"):
        music = {item["ref"]: item["target"] for item in next(p for p in body["presets"] if p["key"] == preset)["musicPlan"]}
        # The channel's uploads are much more than the artist's albums, so its feeds start skipped.
        assert {music[ref] for ref in ("videos", "streams", "shorts")} == {"exclude"}
    music = {item["ref"]: item["target"] for item in next(p for p in body["presets"] if p["key"] == "one_show")["musicPlan"]}
    assert music["PLcabin"] == "main"

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "type": "music", "sections": [
        {"ref": ref, "target": target} for ref, target in music.items()
    ]})
    assert response.status_code == 201, response.text
    # Without a feed the artist's collection lists none of the channel's uploads, so it holds what its playlists give
    # it, also the tracks the channel's own link doesn't list.
    main = lambda: session.execute(select(Collection.outside_videos, Collection.feeds).where(Collection.slug == "UCworkshop")).one()
    assert tuple(main()) == (OutsideVideos.ADD.value, [])

    # A feed that joins it later lists only that feed: its Videos, without its Live and Shorts.
    added = client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "videos", "target": "main"}]})
    assert added.status_code == 200, added.text
    session.expire_all()
    assert tuple(main()) == (OutsideVideos.ADD.value, ["videos"])
    page = client.get("/api/creators/workshop").json()
    kept = {section["ref"]: section["collectionSlug"] for section in page["accounts"][0]["sections"]}
    assert (kept["videos"], kept["streams"], kept["shorts"]) == ("UCworkshop", None, None)


def test_a_creator_the_site_knows_isnt_an_artist_isnt_added_as_one(client, tube, monkeypatch):
    from dataclasses import replace

    details = tube.creator_details(ROOT)
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=lambda step: None: replace(details, music_known=True))
    _steps, body = _lookup(client)
    assert (body["music"], body["musicKnown"]) == (False, True)

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "lookupId": body["lookupId"], "type": "music", "sections": [
        {"ref": "PLcabin", "target": "main"},
    ]})
    assert response.status_code == 422, response.text
    assert "isn't a music artist" in response.json()["detail"]


def test_a_site_names_its_creators_in_its_own_words(client, tube, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(type(tube), "sites", (replace(tube.sites[0], creator_names=Names("host", "hosts")),))
    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    lines = [json.loads(line) for line in response.text.splitlines()]

    assert lines[0] == {"creatorNames": {"singular": "host", "plural": "hosts", "a": "a host"}}
    assert lines[-1]["creator"]["creatorNames"]["singular"] == "host"


def test_a_creator_lookup_says_what_its_site_calls_the_creators_sections(client, tube, monkeypatch):

    response = client.post("/api/creators/lookup", json={"sourceKey": "tube", "url": ROOT})
    found = json.loads(response.text.splitlines()[-1])["creator"]

    assert [(t["key"], t["kind"], t["names"]["plural"]) for t in found["sectionTypes"]] == [
        ("videos", "feed", "videos"), ("live", "feed", "livestreams"), ("shorts", "feed", "shorts"), ("list", "list", "playlists"),
    ]
    assert [(section["ref"], section["type"], section["kind"], section["role"], section["title"]) for section in found["sections"]][:3] == [
        ("videos", "videos", "feed", "main", "Videos"), ("shorts", "shorts", "feed", "short", "Shorts"),
        ("streams", "live", "feed", "live", "Livestreams"),
    ]
    assert {section["kindNames"]["plural"] for section in found["sections"] if section["kind"] == "feed"} == {"feeds"}


def test_a_creators_sections_keep_their_type_and_a_feed_no_title_of_its_own(client, session):
    from backend.db.models import CreatorSection

    _one_show(client)
    stored = {section.ref: (section.type, section.own_title) for section in session.scalars(select(CreatorSection))}
    assert stored["streams"] == ("live", None) and stored["PLcabin"] == ("list", "Building the Cabin")
    page = client.get("/api/creators/workshop").json()
    assert {(section["ref"], section["type"], section["title"]) for section in page["accounts"][0]["sections"]} >= {
        ("streams", "live", "Livestreams"), ("PLcabin", "list", "Building the Cabin"),
    }


def test_a_playlist_that_is_a_season_of_the_creators_collection_moves_to_a_collection_that_joins(client, session):
    from backend.db.models import Collection, CollectionList

    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})
    _plain_collection(session, "cabin", SECTIONS[3].url)

    match, _steps = _match(client, "cabin")
    assert (match["sectionTitle"], match["keptBy"]) == ("Building the Cabin", None)
    # The collection of the playlist takes it from the creator's own collection.
    joined = client.post("/api/collections/cabin/creator")

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
        "customSeasonOrder": False, "linkSeasons": "all", "newLists": {"list": "add"},
        "playlists": [{"id": playlist["id"], "enabled": playlist["enabled"]} for playlist in view["playlists"]],
    }
    refused = client.put("/api/collections/UCworkshop/season-settings", json=body)
    assert refused.status_code == 422 and "decides which of its playlists" in refused.text
    saved = client.put("/api/collections/UCworkshop/season-settings", json={**body, "linkSeasons": "selected"}).json()
    # What happens with a new playlist stays the creator's choice.
    assert [(setting["key"], setting["action"]) for setting in saved["newLists"]] == [("list", "ask")]


def test_an_artists_creator_is_called_an_artist(client, tube, session, monkeypatch):
    from dataclasses import replace

    details = tube.creator_details(ROOT)
    monkeypatch.setattr(tube, "creator_details", lambda ref, progress=lambda step: None: replace(details, music=True))
    # The user says the creator the Site wasn't sure of is an artist.
    client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "type": "music", "sections": [{"ref": "PLcabin", "target": "main"}]})

    assert client.get("/api/creators/workshop").json()["creatorNames"]["singular"] == "artist"
    assert [creator["creatorNames"]["singular"] for creator in client.get("/api/creators").json()] == ["artist"]


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


CAST_ROOT = "https://cast.example/hosts/northwind"


class CastSource(ListedSource):
    """A second Site, whose creators are hosts with shows."""

    id = "cast"
    name = "Cast"
    domains = ("cast.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site("cast", "Cast", ("cast.example",), creators=True, creator_names=Names("host", "hosts"), section_types=(SHOWS,)),)

    def creator_details(self, ref, progress=lambda step: None):
        return CreatorDetails(
            ref="northwind", url=CAST_ROOT, title="Northwind Workshop Live", handle="@nw-live",
            sections=(SectionRef("workbench", "https://cast.example/shows/workbench", SHOWS, "The Workbench"),),
        )


@pytest.fixture
def cast(tube):
    return registry.register(CastSource())


def _add_host(client, into=None):
    return client.post("/api/creators", json={
        "sourceKey": "cast", "url": CAST_ROOT, "sections": [{"ref": "workbench", "target": "own"}], "into": into,
    })


def test_a_creator_is_called_what_their_one_site_calls_them_and_a_creator_on_several(client, cast):
    _one_show(client)
    assert _add_host(client).status_code == 201
    creators = {creator["slug"]: creator for creator in client.get("/api/creators").json()}
    assert {slug: (creator["creatorNames"]["singular"], creator["kind"]) for slug, creator in creators.items()} == {
        "workshop": ("creator", "Tube creator"), "nw-live": ("host", "Cast host"),
    }


def test_an_account_on_another_site_joins_a_creator_in_the_library(client, cast, session):
    from backend.db.models import Collection
    from task_manager.tasks.workers.follow_creators.service import run_follow_creators

    _one_show(client)
    response = _add_host(client, into="workshop")
    assert response.status_code == 201, response.text

    page = response.json()
    assert page["slug"] == "workshop" and (page["creatorNames"]["singular"], page["kind"]) == ("creator", "creator")
    assert [account["site"]["name"] for account in page["accounts"]] == ["Tube", "Cast"]
    assert [section["collectionSlug"] for section in page["accounts"][1]["sections"]] == ["workbench"]
    assert [creator["slug"] for creator in client.get("/api/creators").json()] == ["workshop"]
    assert session.scalar(select(Collection.creator_id).where(Collection.slug == "workbench")) == page["id"]
    # The daily look visits both accounts of the one creator.
    assert run_follow_creators(session).data | {"found": 0} == {
        "creators": 1, "accounts": 2, "found": 0, "added": 0, "failed": [],
    }
    # Adding the same account again says where it is.
    again = _add_host(client)
    assert again.status_code == 422 and "as Northwind Workshop" in again.json()["detail"]


def test_two_creators_who_are_one_person_combine(client, cast, session):
    from backend.db.models import Collection, Creator

    _one_show(client)
    assert _add_host(client).status_code == 201

    response = client.post("/api/creators/workshop/combine", json={"otherSlug": "nw-live"})
    assert response.status_code == 200, response.text
    page = response.json()
    assert [account["site"]["key"] for account in page["accounts"]] == ["tube", "cast"]
    assert {collection["slug"] for collection in page["collections"]} >= {"UCworkshop", "workbench"}
    session.expire_all()
    assert list(session.scalars(select(Creator.slug))) == ["workshop"]
    assert set(session.scalars(select(Collection.creator_id))) == {page["id"]}
    assert client.post("/api/creators/workshop/combine", json={"otherSlug": "workshop"}).status_code == 422


def test_an_account_splits_off_into_a_creator_of_its_own_with_its_collections(client, cast, session):
    from backend.db.models import Collection

    _one_show(client)
    page = _add_host(client, into="workshop").json()
    cast_account = page["accounts"][1]["id"]

    response = client.post(f"/api/creators/workshop/accounts/{cast_account}/split")
    assert response.status_code == 200, response.text
    split = response.json()
    assert (split["slug"], split["title"], split["kind"]) == ("nw-live", "Northwind Workshop Live", "Cast host")
    assert [collection["slug"] for collection in split["collections"]] == ["workbench"]
    workshop = client.get("/api/creators/workshop").json()
    assert [account["site"]["key"] for account in workshop["accounts"]] == ["tube"]
    assert "workbench" not in {collection["slug"] for collection in workshop["collections"]}
    session.expire_all()
    assert session.scalar(select(Collection.creator_id).where(Collection.slug == "workbench")) == split["id"]
    # A creator's only account stays theirs.
    only = client.post(f"/api/creators/nw-live/accounts/{cast_account}/split")
    assert only.status_code == 422


CLIPS_ROOT = "https://clips.example/northwind"


class ClipsSource(ListedSource):
    """A third Site, where the same creator has a channel of their own, with a picture."""

    id = "clips"
    name = "Clips"
    domains = ("clips.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site("clips", "Clips", ("clips.example",), creators=True, section_types=(VIDEOS,)),)

    def creator_details(self, ref, progress=lambda step: None):
        return CreatorDetails(
            ref="clips-northwind", url=CLIPS_ROOT, title="Northwind Workshop", handle="@nw-clips",
            avatar_url="https://clips.example/northwind.jpg", banner_url="https://clips.example/banner.jpg",
            sections=(SectionRef("videos", f"{CLIPS_ROOT}/videos", VIDEOS),),
        )


def _add_clips(client, into=None):
    return client.post("/api/creators", json={
        "sourceKey": "clips", "url": CLIPS_ROOT, "sections": [{"ref": "videos", "target": "main"}], "into": into,
    })


def _main_titles(client, slug):
    page = client.get(f"/api/creators/{slug}").json()
    titles = {collection["slug"]: collection["title"] for collection in page["collections"]}
    return {account["site"]["key"]: titles[account["mainCollectionSlug"]] for account in page["accounts"]}


def test_the_own_collections_of_a_creator_on_several_sites_are_named_after_their_site(client, tube, session):
    registry.register(ClipsSource())
    _one_show(client)
    assert _add_clips(client).status_code == 201
    assert _main_titles(client, "nw-clips") == {"clips": "Northwind Workshop"}

    # Combined, both own collections take their Site's name, and each account keeps its own picture.
    assert client.post("/api/creators/workshop/combine", json={"otherSlug": "nw-clips"}).status_code == 200
    assert _main_titles(client, "workshop") == {"tube": "Northwind Workshop Tube", "clips": "Northwind Workshop Clips"}
    # Each collection tells its Site, which names what it holds, such as tracks on a Site with sound only.
    page = client.get("/api/creators/workshop").json()
    assert {collection["slug"]: collection["site"]["key"] for collection in page["collections"]} == {
        "UCworkshop": "tube", "UCworkshop-shorts": "tube", "clips-northwind": "clips",
    }
    accounts = page["accounts"]
    assert [account["avatarUrl"] for account in accounts] == [None, "https://clips.example/northwind.jpg"]

    # Split off, the names stay; combined again, no Site's name is added twice.
    clips_account = accounts[1]["id"]
    split = client.post(f"/api/creators/workshop/accounts/{clips_account}/split").json()
    assert split["avatarUrl"] == "https://clips.example/northwind.jpg"
    assert _main_titles(client, split["slug"]) == {"clips": "Northwind Workshop Clips"}
    assert client.post("/api/creators/workshop/combine", json={"otherSlug": split["slug"]}).status_code == 200
    assert _main_titles(client, "workshop") == {"tube": "Northwind Workshop Tube", "clips": "Northwind Workshop Clips"}


def test_an_account_that_joins_a_creator_names_both_own_collections_after_their_site(client, tube, session):
    from backend.db.models import Collection
    from backend.db.core import run_write_transaction

    registry.register(ClipsSource())
    _one_show(client)
    assert _add_clips(client, into="workshop").status_code == 201
    assert _main_titles(client, "workshop") == {"tube": "Northwind Workshop Tube", "clips": "Northwind Workshop Clips"}

    # Only a collection named exactly after the creator takes its Site's name: one the user named stays as it is.
    def rename(s):
        s.scalar(select(Collection).where(Collection.slug == "UCworkshop")).title = "Workshop Videos"
    run_write_transaction(rename)
    accounts = client.get("/api/creators/workshop").json()["accounts"]
    split = client.post(f"/api/creators/workshop/accounts/{accounts[1]['id']}/split").json()
    assert client.post(f"/api/creators/{split['slug']}/combine", json={"otherSlug": "workshop"}).status_code == 200
    assert _main_titles(client, split["slug"]) == {"clips": "Northwind Workshop Clips", "tube": "Workshop Videos"}


def test_an_accounts_own_collection_shows_the_pictures_of_its_own_site(client, tube, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CreatorAccount
    from backend.services.creators import take_account_pictures

    registry.register(ClipsSource())
    _one_show(client)

    def tube_picture(s):
        creator = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == "tube")).creator
        creator.avatar_path = creator.accounts[0].avatar_path = "https://tube.example/northwind.jpg"
    run_write_transaction(tube_picture)
    assert _add_clips(client, into="workshop").status_code == 201

    def pictures(s):
        main = s.scalar(select(Collection).where(Collection.slug == "clips-northwind"))
        return main.thumbnail_landscape_path, main.background_image_path
    clips = ("https://clips.example/northwind.jpg", "https://clips.example/banner.jpg")
    assert run_write_transaction(pictures) == clips

    # An account added before it kept its own pictures showed the other Site's picture until it was looked up again.
    def as_before(s):
        account = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == "clips"))
        account.avatar_path = account.banner_path = None
        account.main_collection.thumbnail_landscape_path = "https://tube.example/northwind.jpg"
        account.main_collection.background_image_path = None
    run_write_transaction(as_before)

    def look_up(s):
        account = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == "clips"))
        take_account_pictures(account, avatar=clips[0], banner=clips[1])
    run_write_transaction(look_up)
    assert run_write_transaction(pictures) == clips

    # A picture the user chose stays when the Site's changes.
    def chosen(s):
        s.scalar(select(Collection).where(Collection.slug == "clips-northwind")).thumbnail_landscape_path = "mine.jpg"
    run_write_transaction(chosen)

    def new_picture(s):
        account = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == "clips"))
        take_account_pictures(account, avatar="https://clips.example/new.jpg", banner=None)
        return account.avatar_path
    assert run_write_transaction(new_picture) == "https://clips.example/new.jpg"
    assert run_write_transaction(pictures) == ("mine.jpg", clips[1])


def _video(session, collection, slug, published):
    from backend.db.models import Episode, Season
    from backend.types.media_types import MediaType

    season = session.scalar(select(Season).where(Season.collection_id == collection.id))
    if season is None:
        season = Season(collection_id=collection.id, index=1, slug=f"{collection.slug}-1", name="Season 1")
        session.add(season)
        session.flush()
    session.add(Episode(
        source_key="tube", uuid=f"uuid-{slug}", type=MediaType.EPISODE.value, collection_id=collection.id,
        season_id=season.id, index=published.year, episode_identifier=f"ep.S01E{published.year}", slug=slug,
        publish_status="published_final", sharing_url=f"https://example.test/{slug}", published_date=published,
        title=slug, duration=60,
    ))


def test_the_creator_page_shows_each_collections_years_and_pages_through_the_newest_episodes(client, session):
    from datetime import datetime, timezone

    from backend.db.models import Collection

    _one_show(client)
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    shorts = session.scalar(select(Collection).where(Collection.slug != "UCworkshop"))
    _video(session, main, "first", datetime(2019, 3, 1, tzinfo=timezone.utc))
    _video(session, main, "latest", datetime(2024, 5, 1, tzinfo=timezone.utc))
    _video(session, shorts, "short", datetime(2025, 1, 1, tzinfo=timezone.utc))
    session.commit()

    page = client.get("/api/creators/workshop").json()

    assert {c["slug"]: c["years"] for c in page["collections"]} == {"UCworkshop": "2019-2024", shorts.slug: "2025-2025"}
    assert page["lastPublishedDate"].startswith("2025-01-01")

    first = client.get("/api/creators/workshop/episodes", params={"limit": 2}).json()
    assert [(e["slug"], e["collectionSlug"]) for e in first["items"]] == [("short", shorts.slug), ("latest", "UCworkshop")]
    assert first["items"][0]["collectionTitle"] == shorts.title
    rest = client.get("/api/creators/workshop/episodes", params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert [e["slug"] for e in rest["items"]] == ["first"]
    assert rest["hasMore"] is False


def test_deleting_a_creator_keeps_its_collections_as_plain_ones(client, session):
    from backend.db.models import Collection, Creator

    _one_show(client)

    assert client.delete("/api/creators/workshop").status_code == 204

    session.expire_all()
    assert session.scalar(select(Creator).where(Creator.slug == "workshop")) is None
    collections = session.scalars(select(Collection)).all()
    assert collections and all(c.creator_id is None for c in collections)
    assert client.delete("/api/creators/workshop").status_code == 404


def test_a_renamed_creator_keeps_its_name_and_gives_it_to_its_collections_as_author(client, session, tube):
    from backend.db.models import Collection

    _one_show(client)
    assert client.patch("/api/creators/workshop", json={"title": "Northwind", "newLists": {"tube": {"list": "ask"}}}).status_code == 200
    authors = {collection.author_name for collection in session.scalars(select(Collection))}
    assert authors == {"Northwind"}

    # The Site's name no longer replaces the one the user gave.
    _follow(session, tube, SECTIONS)
    assert client.get("/api/creators/workshop").json()["title"] == "Northwind"

    # A collection of the creator can't have another author.
    collection = client.get("/api/collections/UCworkshop").json()
    body = {
        "title": collection["title"], "membershipLevel": collection["membershipLevel"], "sharingUrl": collection["sharingUrl"],
        "authorName": "Someone else",
    }
    refused = client.patch("/api/collections/UCworkshop", json=body)
    assert refused.status_code == 422
    assert "change it on their Edit page" in refused.json()["detail"]
    assert client.patch("/api/collections/UCworkshop", json={**body, "authorName": "Northwind"}).status_code == 200



def test_new_sections_only_become_seasons_where_a_creators_site_can_make_lists_seasons(client, tube, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(type(tube), "sites", (replace(tube.sites[0], link_seasons=False),))
    plan = [{"ref": "videos", "target": "own"}]
    refused = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan, "newLists": {"tube": {"list": "season"}}})
    assert refused.status_code == 422
    assert "can't be added as seasons" in str(refused.json())

    assert client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": plan, "newLists": {"tube": {"list": "own"}}}).status_code == 201
    refused = client.patch("/api/creators/workshop", json={"newLists": {"tube": {"list": "season"}}})
    assert refused.status_code == 422
    assert "playlists can't be added as seasons" in str(refused.json())


FILM_ROOT = "https://film.example/hosts/marsh"
FILM_SECTIONS = (
    SectionRef("evenings", "https://film.example/shows/evenings", SHOWS, "Evenings"),
    SectionRef("tribute", "https://film.example/videos/tribute", MOVIES, "A Tribute"),
    SectionRef("harbour", "https://film.example/videos/harbour", MOVIES, "The Harbour"),
)


class FilmSource(ListedSource):
    """A Site whose hosts have shows and movies."""

    id = "film"
    name = "Film"
    domains = ("film.example",)
    features = ListedSource.features | {Feature.CREATORS, Feature.MOVIES}
    sites = (Site(
        "film", "Film", ("film.example",), creators=True, creator_names=Names("host", "hosts"), section_types=(SHOWS, MOVIES),
        creator_presets=(CreatorPreset.PER_LIST, CreatorPreset.PICK),
    ),)

    def creator_details(self, ref, progress=lambda step: None):
        return CreatorDetails(ref="marsh", url=FILM_ROOT, title="Ada Marsh", sections=FILM_SECTIONS)


def _movie(session, slug, title):
    from backend.db.models import Movie

    movie = Movie(uuid=f"uuid-{slug}", slug=slug, title=title, type="movie", source_key="film")
    session.add(movie)
    session.commit()
    return movie


@pytest.fixture
def film(tube, session, monkeypatch):
    """The Film Site, whose movies the Source "looks up" as their slugs and the Library adds as plain movies."""
    from backend.api.endpoints.creators import router as creator_router, service as creator_service
    from backend.db.models import Movie

    asked: list[list[str]] = []

    def look_up_movies(source_key, slugs):
        asked.append(list(slugs))
        return list(slugs)

    def add_movies(s, slugs):
        titles = {section.ref: section.title for section in FILM_SECTIONS}
        movies = [Movie(uuid=f"uuid-{slug}", slug=slug, title=titles[slug], type="movie", source_key="film") for slug in slugs]
        s.add_all(movies)
        s.flush()
        return movies

    monkeypatch.setattr(creator_router, "look_up_movies", look_up_movies)
    monkeypatch.setattr(creator_service, "add_movies", add_movies)
    registry.register(FilmSource())
    return asked


def _film_lookup(client):
    response = client.post("/api/creators/lookup", json={"sourceKey": "film", "url": FILM_ROOT})
    return json.loads(response.text.splitlines()[-1])["creator"]


def test_a_hosts_movies_are_added_with_them_and_a_movie_in_the_library_joins_them(client, session, film):
    from backend.db.models import Movie

    _movie(session, "tribute", "A Tribute to the Coast")
    found = _film_lookup(client)
    assert found["movies"] is True
    by_ref = {section["ref"]: section for section in found["sections"]}
    assert (by_ref["tribute"]["movieSlug"], by_ref["tribute"]["movieTitle"]) == ("tribute", "A Tribute to the Coast")
    assert by_ref["harbour"]["movieSlug"] is None
    # Every preset adds the movies, and the one in the library joins the host even when the user picks.
    assert _plan(found, "per_list") == {"evenings": "own", "tribute": "own", "harbour": "own"}
    assert _plan(found, "pick") == {"evenings": "exclude", "tribute": "own", "harbour": "exclude"}

    response = client.post("/api/creators", json={
        "sourceKey": "film", "url": FILM_ROOT, "lookupId": found["lookupId"],
        "sections": [{"ref": "evenings", "target": "exclude"}, {"ref": "tribute", "target": "own"}, {"ref": "harbour", "target": "own"}],
    })
    assert response.status_code == 201, response.text
    page = response.json()
    # Only the movie that wasn't in the library is looked up, and neither becomes a collection.
    assert film == [["harbour"]]
    assert page["collections"] == []
    assert sorted(movie["slug"] for movie in page["movies"]) == ["harbour", "tribute"]
    assert all(section["movieJoined"] for section in page["accounts"][0]["sections"] if section["kind"] == "item")
    assert page["accounts"][0]["movies"] is True
    session.expire_all()
    assert set(session.scalars(select(Movie.creator_id))) == {page["id"]}


def test_a_movie_that_stays_apart_keeps_out_of_the_host_and_can_join_later(client, session, film):
    from backend.db.models import Movie

    _movie(session, "tribute", "A Tribute")
    response = client.post("/api/creators", json={
        "sourceKey": "film", "url": FILM_ROOT,
        "sections": [{"ref": "evenings", "target": "own"}, {"ref": "tribute", "target": "exclude"}, {"ref": "harbour", "target": "exclude"}],
    })
    assert response.status_code == 201, response.text
    page = response.json()
    assert page["movies"] == [] and film == [[]]
    assert session.scalar(select(Movie.creator_id).where(Movie.slug == "tribute")) is None

    # From the host's page, the movie in the library joins and the other one is added.
    account = page["accounts"][0]["id"]
    response = client.post(f"/api/creators/{page['slug']}/accounts/{account}/sections", json={
        "sections": [{"ref": "tribute", "target": "own"}, {"ref": "harbour", "target": "own"}],
    })
    assert response.status_code == 200, response.text
    assert sorted(movie["slug"] for movie in response.json()["movies"]) == ["harbour", "tribute"]
    assert film[-1] == ["harbour"]
    assert [collection["slug"] for collection in response.json()["collections"]] == ["evenings"]


def test_a_hosts_movies_leave_with_them_and_stay_in_the_library(client, session, film):
    from backend.db.models import Movie

    page = client.post("/api/creators", json={
        "sourceKey": "film", "url": FILM_ROOT, "sections": [{"ref": "harbour", "target": "own"}],
    }).json()
    assert client.delete(f"/api/creators/{page['slug']}").status_code in (200, 204)
    session.expire_all()
    assert list(session.scalars(select(Movie.slug).where(Movie.creator_id.is_(None)))) == ["harbour"]


def test_each_new_collection_takes_the_type_and_identification_chosen_for_it(client, session):
    from backend.db.models import Collection

    # Only an artist's collections hold music.
    refused = client.post("/api/creators", json={
        "sourceKey": "tube", "url": ROOT, "sections": [{"ref": "PLmembers", "target": "own", "type": "music"}],
    })
    assert refused.status_code == 422 and "music artist" in refused.text
    response = client.post("/api/creators", json={
        "sourceKey": "tube", "url": ROOT, "type": "podcast", "episodeIdentifier": "date_based",
        "sections": [
            {"ref": "videos", "target": "main"},
            {"ref": "PLcabin", "target": "own", "type": "series", "episodeIdentifier": "seasonal"},
            {"ref": "PLtools", "target": "own"},
        ],
    })
    assert response.status_code == 201, response.text
    session.expire_all()
    assert {
        collection.slug: (collection.type, collection.episode_identifier) for collection in session.scalars(select(Collection))
    } == {
        # A list is its collection's one season, so without a choice of its own it is numbered in the list's order.
        "UCworkshop": ("podcast", "date_based"), "PLcabin": ("series", "seasonal"), "PLtools": ("podcast", "numbered"),
    }


def test_each_kind_of_list_has_its_own_setting_for_new_ones(client, session, tube, monkeypatch):
    from dataclasses import replace

    import sys

    from backend.db.models import Collection, Creator

    albums = SectionType("album", SectionKind.LIST, Names("album", "albums"), albums=True)
    playlists = SectionType("playlist", SectionKind.LIST, Names("playlist", "playlists"))
    monkeypatch.setattr(type(tube), "sites", (replace(tube.sites[0], section_types=(VIDEOS, LIVE, SHORTS, albums, playlists)),))
    sections = tuple(replace(section, type=playlists) if section.kind is SectionKind.LIST else section for section in SECTIONS)
    monkeypatch.setattr(sys.modules[__name__], "SECTIONS", sections)
    _one_show(client)
    client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLcabin", "target": "main"}]})
    page = client.patch("/api/creators/workshop", json={"newLists": {"tube": {"album": "season"}}}).json()
    assert [(setting["key"], setting["names"]["plural"], setting["albums"], setting["action"]) for setting in page["newLists"]] == [
        ("album", "albums", True, "season"), ("playlist", "playlists", False, "ask"),
    ]
    refused = client.patch("/api/creators/workshop", json={"newLists": {"tube": {"list": "season"}}})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "This creator's sites have no lists of the kind list on tube"
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    session.refresh(main)
    assert main.new_lists == {"album": "add", "playlist": "ask"}
    assert session.scalar(select(Creator)).new_lists == {"tube": {"album": "season", "playlist": "ask"}}
    album = replace(NEW_LIST, ref="PLalbum", url="https://tube.example/playlist?list=PLalbum", title="Album", type=albums)
    playlist = replace(NEW_LIST, type=playlists)

    result = _follow(session, tube, (album, playlist, *sections))

    # The album is added by itself; the playlist waits for the user's choice.
    assert ([section.ref for section in result.added], [section.ref for section in result.asked]) == (["PLalbum"], ["PLbarn"])


def test_deleting_an_accounts_own_collection_keeps_the_account(client, tube, session):
    registry.register(ClipsSource())
    _one_show(client)
    assert _add_clips(client, into="workshop").status_code == 201
    page = client.get("/api/creators/workshop").json()
    clips = next(account for account in page["accounts"] if account["site"]["key"] == "clips")

    assert client.delete(f"/api/collections/{clips['mainCollectionSlug']}").status_code == 200

    page = client.get("/api/creators/workshop").json()
    assert [account["site"]["key"] for account in page["accounts"]] == ["tube", "clips"]
    assert page["accounts"][1]["mainCollectionSlug"] is None
    assert clips["mainCollectionSlug"] not in {collection["slug"] for collection in page["collections"]}


def test_a_section_whose_id_is_a_path_gets_a_collection_its_link_can_open(client, session, monkeypatch):
    import test_creators
    from backend.db.models import Collection

    album = SectionRef("workshop/sets/cabin-songs", f"{ROOT}/sets/cabin-songs", PLAYLISTS, "Cabin Songs", item_count=9)
    monkeypatch.setattr(test_creators, "SECTIONS", (*SECTIONS, album))

    added = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": album.ref, "target": "own"},
    ]})

    assert added.status_code == 201, added.text
    assert session.scalar(select(Collection.slug).where(Collection.sharing_url == album.url)) == "workshop-sets-cabin-songs"
    sections = {section["ref"]: section for section in added.json()["accounts"][0]["sections"]}
    assert sections[album.ref]["collectionSlug"] == "workshop-sets-cabin-songs"
    assert added.json()["collections"][0]["slug"] == "workshop-sets-cabin-songs"
