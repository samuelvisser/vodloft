"""A playlist that becomes a collection of its own takes its videos out of each other collection of the creator, as
that collection's setting for a video in several seasons says. One episode per video: every video of the playlist
leaves, also one another playlist season there has. An episode in each season: only the videos the collection has
from its feeds leave, and the ones a playlist season there has stay. The move dialog says what saving then does."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from test_creators import ROOT, client, tube  # noqa: F401
from test_pending_lists import _video
from test_reassigned import _download, _episode, _profile, _settled
from test_ytdlp_collections import session  # noqa: F401


@pytest.fixture
def creator(client, session):
    """The creator's own collection takes its uploads v1, t1 and t2, with Building the Cabin, which has t2, as a
    season. Tool Reviews, with t1 and t2, waits for the user's choice; t1 is downloaded."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CollectionListItem, CreatorSection, CreatorSectionItem
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})
    assert response.status_code == 201, response.text
    tools = session.scalar(select(CreatorSection).where(CreatorSection.ref == "PLtools"))
    tools.status = "new"
    session.add_all([CreatorSectionItem(section_id=tools.id, source_slug=slug) for slug in ("t1", "t2")])
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    cabin = next(link for link in main.lists if link.ref == "PLcabin")
    session.add(CollectionListItem(list_id=cabin.id, source_slug="t2", position=1))
    session.commit()
    main_id = main.id
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[
        _video("v1"), _video("t1", 2), _video("t2", 3),
    ]))
    session.expire_all()
    main = session.get(Collection, main_id)
    _download(session, _episode(session, main, "t1"), _profile(session, "shows"))
    session.commit()
    _settled()
    return main_id


def _repeat(session, main_id, value):
    from backend.db.models import Collection

    session.get(Collection, main_id).repeat_videos = value
    session.commit()


def _own(client, *, preview=False):
    _settled()
    moves = {"moves": [{"accountId": 1, "ref": "PLtools", "target": "own"}]}
    if preview:
        return client.post("/api/creators/workshop/moves/preview", json=moves)
    return client.patch("/api/creators/workshop", json=moves)


def _main_part(preview):
    [main] = [item for item in preview.json()["collections"] if item["slug"] == "UCworkshop"]
    return [(part["direction"], part["count"], sorted(part["examples"])) for part in main["parts"]]


def test_with_one_episode_per_video_every_video_of_the_playlist_leaves(creator, client, session):
    from backend.db.models import Collection

    preview = _own(client, preview=True)
    assert preview.status_code == 200, preview.text
    assert _main_part(preview) == [("out", 2, ["Video t1", "Video t2"])]

    assert _own(client).status_code == 200
    session.expire_all()
    main = session.get(Collection, creator)
    assert _episode(session, main, "t2") is None
    assert _episode(session, main, "v1") is not None


def test_with_an_episode_in_each_season_a_video_a_playlist_season_has_stays(creator, client, session):
    from backend.db.models import Collection

    _repeat(session, creator, "each_season")
    preview = _own(client, preview=True)
    assert preview.status_code == 200, preview.text
    assert _main_part(preview) == [("out", 1, ["Video t1"])]

    assert _own(client).status_code == 200
    session.expire_all()
    main = session.get(Collection, creator)
    assert _episode(session, main, "t2") is not None
    tools = session.scalar(select(Collection).where(Collection.title == "Tool Reviews"))
    assert _episode(session, tools, "t1") is not None and _episode(session, tools, "t2") is not None


def test_a_skipped_playlist_is_listed_first_and_then_moves_as_a_waiting_one(creator, client, session, tube, monkeypatch):
    from backend.db.models import Collection, CreatorSection, CreatorSectionItem
    from sources import ItemRef

    tools = session.scalar(select(CreatorSection).where(CreatorSection.ref == "PLtools"))
    tools.status = "ignored"
    session.query(CreatorSectionItem).delete()
    session.commit()
    asked = []

    def list_items(url):
        asked.append(url)
        return tuple(ItemRef(slug, f"https://tube.example/watch?v={slug}") for slug in ("t1", "t2"))

    monkeypatch.setattr(tube, "list_items", list_items, raising=False)

    preview = _own(client, preview=True)
    assert preview.status_code == 200, preview.text
    assert _main_part(preview) == [("out", 2, ["Video t1", "Video t2"])]
    assert asked == ["https://tube.example/playlist?list=PLtools"]
    # The preview changed nothing.
    session.expire_all()
    assert session.scalar(select(CreatorSectionItem.source_slug)) is None

    assert _own(client).status_code == 200
    session.expire_all()
    main = session.get(Collection, creator)
    assert _episode(session, main, "t2") is None
    assert session.scalar(select(CreatorSection.status).where(CreatorSection.ref == "PLtools")) == "known"


def test_a_skipped_playlist_that_could_not_be_listed_does_not_move(creator, client, session, tube, monkeypatch):
    from backend.db.models import CreatorSection, CreatorSectionItem

    session.scalar(select(CreatorSection).where(CreatorSection.ref == "PLtools")).status = "ignored"
    session.query(CreatorSectionItem).delete()
    session.commit()

    def list_items(url):
        raise RuntimeError("offline")

    monkeypatch.setattr(tube, "list_items", list_items, raising=False)

    preview = _own(client, preview=True)
    assert preview.status_code == 422 and "could not look up what Tool Reviews has" in preview.text
