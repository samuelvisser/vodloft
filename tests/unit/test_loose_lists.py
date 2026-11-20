"""A creator's list in the creator's own collection without being a season: its videos go where the ones in no list
go, and it keeps none of them out, unlike a list excluded from the library."""
from __future__ import annotations

from sqlalchemy import select

from test_creators import ROOT, client, tube  # noqa: F401
from test_reassigned import _cabin_video, _download, _episode, _profile, _save, _settled, _video, creator  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401


def _list(session, collection, ref):
    from backend.db.models import CollectionList

    session.expire_all()
    return session.scalar(select(CollectionList).where(CollectionList.collection_id == collection.id, CollectionList.ref == ref))


def _sections(page):
    return {section["ref"]: section for section in page["accounts"][0]["sections"]}


def test_a_playlist_in_the_creators_collection_not_as_a_season_keeps_its_videos_in_the_other_seasons(
    client, session, tube, monkeypatch,
):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, Episode
    from sources import ItemRef
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes, index_listed_collection

    members_url = "https://tube.example/playlist?list=PLmembers"
    monkeypatch.setattr(tube, "list_episodes", lambda url, *, known, feeds=None: iter(
        _video(slug, day) for day, slug in enumerate(["m1", "m2", "v1"], start=1) if slug not in known
    ))
    monkeypatch.setattr(tube, "list_items", lambda url: tuple(
        ItemRef(slug, f"https://tube.example/watch?v={slug}") for slug in {members_url: ["m1", "m2"]}.get(url, [])
    ), raising=False)
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLmembers", "target": "main_loose"},
    ]})
    assert response.status_code == 201, response.text
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    main_id = main.id
    members = _list(session, main, "PLmembers")
    assert (members.enabled, members.as_season) == (True, False)
    session.commit()
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[_video("m1")]))

    index_listed_collection(session, collection_id=main_id, source=tube)
    session.expire_all()

    episodes = list(session.scalars(select(Episode).where(Episode.collection_id == main_id)))
    assert sorted(episode.source_slug for episode in episodes) == ["m1", "m2", "v1"]
    # No season of the playlist's own: they are where the videos in no playlist are.
    assert {episode.season.name for episode in episodes} == {episode.season.name for episode in episodes if episode.source_slug == "v1"}
    section = _sections(client.get("/api/creators/workshop").json())["PLmembers"]
    assert (section["collectionSlug"], section["asSeason"]) == ("UCworkshop", False)


def test_a_playlist_season_stops_being_a_season_and_back_again_with_its_files(creator, client, session):
    from task_manager.scheduler.db import TaskOperation

    from backend.db.core import run_write_transaction
    from backend.services.link_seasons import place_in_link_seasons

    main, _tools = creator
    main_id = main.id
    _cabin_video(session, main)
    run_write_transaction(lambda w: place_in_link_seasons(w, w.get(type(main), main_id), with_files=True))
    session.expire_all()
    main = session.get(type(main), main_id)
    assert _episode(session, main, "k1").season.name == "Building the Cabin"

    _settled()
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "PLcabin", "target": "main_loose"},
    ]})
    assert preview.status_code == 200, preview.text
    [collection] = preview.json()["collections"]
    assert [(part["direction"], part["count"], part["filesMoved"]) for part in collection["parts"]] == [("loose", 2, 1)]
    assert collection["filesFollow"] is True

    loose = _save(client, "PLcabin", "main_loose")

    assert loose.status_code == 200, loose.text
    assert _list(session, main, "PLcabin").as_season is False
    k1 = _episode(session, main, "k1")
    assert k1.season.name != "Building the Cabin"
    assert _sections(loose.json())["PLcabin"]["asSeason"] is False
    # The collection renames the files into their new season.
    session.expire_all()
    assert session.scalars(select(TaskOperation).where(
        TaskOperation.kind == "collection.renumber", TaskOperation.resource_id == main.id,
    )).first() is not None

    back = _save(client, "PLcabin", "main")

    assert back.status_code == 200, back.text
    assert _list(session, main, "PLcabin").as_season is True
    assert _episode(session, main, "k1").season.name == "Building the Cabin"


def test_a_playlist_collection_joins_the_creators_collection_not_as_a_season(creator, client, session):
    from backend.db.models import Collection
    from backend.db.models.media_download import EpisodeMediaDownload

    main, tools = creator
    download = _download(session, _episode(session, tools, "t1"), _profile(session, "shows"))
    download_id, tools_id = download.id, tools.id
    session.commit()

    moved = _save(client, "PLtools", "main_loose")

    assert moved.status_code == 200, moved.text
    session.expire_all()
    assert session.get(Collection, tools_id) is None
    t1 = session.get(EpisodeMediaDownload, download_id).media
    assert t1.collection_id == main.id and t1.season.name != "Tool Reviews"
    assert _list(session, main, "PLtools").as_season is False


def test_a_feed_is_never_in_the_creators_collection_without_being_one_of_its_feeds(creator, client):
    refused = _save(client, "videos", "main_loose")
    assert refused.status_code == 422 and "can't move" in refused.text


def test_a_creator_set_to_add_new_playlists_not_as_seasons_adds_them_to_its_own_collection(client, session, tube):
    from backend.db.models import Collection
    from test_creators import NEW_LIST, SECTIONS, _follow, _one_show

    _one_show(client)
    assert client.patch("/api/creators/workshop", json={"newLists": {"tube": {"list": "loose"}}}).status_code == 200

    result = _follow(session, tube, (NEW_LIST, *SECTIONS))

    assert [section.ref for section in result.added] == ["PLbarn"]
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    session.refresh(main)
    barn = {link.ref: link for link in main.lists}["PLbarn"]
    assert (barn.enabled, barn.as_season) == (True, False)
