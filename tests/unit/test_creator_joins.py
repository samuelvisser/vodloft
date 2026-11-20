"""A collection that joins a creator in the Library: a playlist takes itself from the creator's own collection, a
collection of all the uploads keeps only what no other collection keeps, and what moves takes its files along, as
the dialog shows before."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import select

from test_creators import ROOT, SECTIONS, _plain_collection, client, tube  # noqa: F401
from test_reassigned import _download, _episode, _profile, _settled
from test_section_moves import _operations, _video
from test_ytdlp_collections import session  # noqa: F401


@pytest.fixture(autouse=True)
def tagged_feeds(monkeypatch):
    """The test Site's Shorts get their own tag, as YouTube's do."""
    import test_creators

    site = test_creators.CreatorSource.sites[0]
    types = tuple(replace(type_, episode_tag="short") if type_.key == "shorts" else type_ for type_ in site.section_types)
    monkeypatch.setattr(test_creators.CreatorSource, "sites", (replace(site, section_types=types),))


def _listed(collection_id, *videos):
    from backend.db.core import run_write_transaction
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=collection_id, found=list(videos)))


def _collection(session, slug):
    from backend.db.models import Collection

    session.expire_all()
    return session.scalar(select(Collection).where(Collection.slug == slug))


def _downloads_of(session, collection):
    from backend.db.models import Episode
    from backend.db.models.media_download import EpisodeMediaDownload

    return sorted(session.scalars(
        select(Episode.source_slug).join(EpisodeMediaDownload, EpisodeMediaDownload.media_item_id == Episode.id)
        .where(Episode.collection_id == collection.id)
    ))


def _slugs(session, collection):
    from backend.db.models import Episode

    return sorted(session.scalars(select(Episode.source_slug).where(Episode.collection_id == collection.id, Episode.part_of.is_(None))))


@pytest.fixture
def cabin_season(client, session):
    """The creator's own collection has Building the Cabin as a season, with k1 (downloaded) and k2, and an upload v1
    that is in no playlist. A plain collection of the playlist, My cabin, has k1 and k2 too."""
    from backend.db.models import CollectionList, CollectionListItem

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})
    assert response.status_code == 201, response.text
    main = _collection(session, "UCworkshop")
    season = session.scalar(select(CollectionList).where(CollectionList.collection_id == main.id, CollectionList.ref == "PLcabin"))
    session.add_all([CollectionListItem(list_id=season.id, source_slug=slug, position=index) for index, slug in enumerate(["k1", "k2"])])
    session.commit()
    _listed(main.id, _video("v1", 1), _video("k1", 2), _video("k2", 3))
    _plain_collection(session, "cabin", SECTIONS[3].url)
    _listed(_collection(session, "cabin").id, _video("k1", 2), _video("k2", 3))
    main = _collection(session, "UCworkshop")
    _download(session, _episode(session, main, "k1"), _profile(session, "shows"))
    session.commit()
    _settled()


def test_a_playlist_takes_itself_from_the_creators_collection_with_its_files(cabin_season, client, session):
    from backend.db.models import CollectionList

    match = json.loads(client.get("/api/collections/cabin/creator/match").text.splitlines()[-1])["match"]
    assert (match["sectionTitle"], match["keptBy"]) == ("Building the Cabin", None)

    preview = client.post("/api/collections/cabin/creator/preview", json={})
    assert preview.status_code == 200, preview.text
    parts = {
        item["slug"]: [(part["direction"], part["count"], part["otherTitle"], part["filesMoved"]) for part in item["parts"]]
        for item in preview.json()["collections"]
    }
    assert parts == {
        "UCworkshop": [("out", 2, "My cabin", 0)],
        "cabin": [("in", 2, "Northwind Workshop", 1)],
    }
    # The preview changed nothing.
    assert _collection(session, "cabin").creator_id is None
    assert _slugs(session, _collection(session, "UCworkshop")) == ["k1", "k2", "v1"]

    joined = client.post("/api/collections/cabin/creator", json={})
    assert joined.status_code == 200, joined.text

    main, cabin = _collection(session, "UCworkshop"), _collection(session, "cabin")
    assert cabin.creator_id == main.creator_id
    season = session.scalar(select(CollectionList).where(CollectionList.collection_id == main.id, CollectionList.ref == "PLcabin"))
    assert season.enabled is False
    assert _slugs(session, main) == ["v1"]
    assert _downloads_of(session, cabin) == ["k1"]
    # One action for the whole join; the playlist's collection renames the file that moved in.
    [move] = _operations(session, "creator.move_sections")
    assert move.context["sections"] == ["1:PLcabin"]
    renumbered = {operation.resource_id for operation in _operations(session, "collection.renumber")}
    assert cabin.id in renumbered


def test_a_collection_of_all_uploads_keeps_only_what_no_other_collection_keeps(client, session):
    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "shorts", "target": "own"}, {"ref": "PLtools", "target": "own"},
    ]})
    assert response.status_code == 201, response.text
    shorts, tools = _collection(session, "UCworkshop-shorts"), _collection(session, "PLtools")
    _listed(shorts.id, _video("s1", 2, "short"))
    _listed(tools.id, _video("t1", 3))
    _plain_collection(session, "uploads", ROOT)
    uploads = _collection(session, "uploads")
    _listed(uploads.id, _video("v1", 1), _video("s1", 2, "short"), _video("t1", 3))
    uploads = _collection(session, "uploads")
    local = _profile(session, "shows")
    _download(session, _episode(session, uploads, "s1"), local)
    _download(session, _episode(session, uploads, "t1"), local)
    session.commit()
    _settled()

    preview = client.post("/api/collections/uploads/creator/preview", json={})
    assert preview.status_code == 200, preview.text
    parts = {
        item["slug"]: sorted((part["sectionTitle"], part["direction"], part["count"]) for part in item["parts"])
        for item in preview.json()["collections"]
    }
    assert parts == {
        "uploads": [("Shorts", "out", 1), ("Tool Reviews", "out", 1)],
        "UCworkshop-shorts": [("Shorts", "in", 1)],
        "PLtools": [("Tool Reviews", "in", 1)],
    }

    joined = client.post("/api/collections/uploads/creator", json={"renumber": {"uploads": False}})
    assert joined.status_code == 200, joined.text

    uploads, shorts, tools = _collection(session, "uploads"), _collection(session, "UCworkshop-shorts"), _collection(session, "PLtools")
    assert "shorts" not in uploads.feeds and "videos" in uploads.feeds
    assert _slugs(session, uploads) == ["v1"]
    assert (_downloads_of(session, shorts), _downloads_of(session, tools)) == (["s1"], ["t1"])
    page = client.get("/api/creators/workshop").json()
    assert {s["ref"]: s["collectionSlug"] for s in page["accounts"][0]["sections"]}["videos"] == "uploads"
    renumber = {operation.resource_id: operation for operation in _operations(session, "collection.renumber")}
    # The collection that keeps its numbers still renames nothing of its own; the others take the moved files.
    assert shorts.id in renumber and tools.id in renumber


def test_a_collection_that_joins_a_new_creator_stays_as_it_is(client, session):
    _plain_collection(session, "tools", SECTIONS[4].url)

    preview = client.post("/api/collections/tools/creator/preview", json={})
    assert preview.status_code == 200, preview.text
    assert preview.json() == {"collections": []}
    assert client.post("/api/collections/tools/creator").status_code == 200
    assert _operations(session, "creator.move_sections") == []
