"""A list the creator added that waits for the user's choice changes nothing: its videos stay where they would be
without it, also downloaded, until the user answers. Answering it moves them at once, with their files, through the
same moves as the Edit page."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from sources import VideoDetails
from test_creators import ROOT, client, tube  # noqa: F401
from test_reassigned import _download, _episode, _profile, _settled
from test_ytdlp_collections import session  # noqa: F401


def _video(slug: str, day: int = 1) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://tube.example/watch?v={slug}", title=f"Video {slug}", duration=60.0,
        published_at=datetime(2025, 1, day, tzinfo=timezone.utc),
    )


@pytest.fixture
def waiting(client, session):
    """A creator whose own collection takes its uploads v1, t1 and t2, with Building the Cabin as a season. Tool
    Reviews, with t1 and t2, is new and waits for the user's choice; t1 is downloaded."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CreatorSection, CreatorSectionItem
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"},
    ]})
    assert response.status_code == 201, response.text
    tools = session.scalar(select(CreatorSection).where(CreatorSection.ref == "PLtools"))
    tools.status = "new"
    session.add_all([CreatorSectionItem(section_id=tools.id, source_slug=slug) for slug in ("t1", "t2")])
    session.commit()
    main_id = session.scalar(select(Collection.id).where(Collection.slug == "UCworkshop"))
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[
        _video("v1"), _video("t1", 2), _video("t2", 3),
    ]))
    session.expire_all()
    main = session.get(Collection, main_id)
    _download(session, _episode(session, main, "t1"), _profile(session, "shows"))
    session.commit()
    _settled()
    return session.get(Collection, main_id)


def _answer(client, target, **move):
    _settled()
    return client.patch("/api/creators/workshop", json={"moves": [{"accountId": 1, "ref": "PLtools", "target": target, **move}]})


def test_a_waiting_list_keeps_nothing_out(waiting, session):
    from backend.db.core import run_write_transaction
    from backend.services.reassigned import left_out, placed_elsewhere, settle_creator

    main_id = waiting.id
    assert left_out(session, waiting) == frozenset()
    assert placed_elsewhere(session, waiting) == frozenset()
    assert run_write_transaction(lambda w: settle_creator(w, w.get(type(waiting), main_id))) == 0
    session.expire_all()
    main = session.get(type(waiting), main_id)
    assert _episode(session, main, "t1") is not None and _episode(session, main, "t2") is not None


def test_skipping_a_list_keeps_nothing_out_and_keeping_it_out_does(waiting, client, session):
    from backend.services.reassigned import left_out

    from backend.db.models import CreatorSection

    skipped = client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [{"ref": "PLtools", "target": "exclude"}]})
    assert skipped.status_code == 200, skipped.text
    session.expire_all()
    assert session.scalar(select(CreatorSection.status).where(CreatorSection.ref == "PLtools")) == "ignored"
    assert left_out(session, waiting) == frozenset()

    session.scalar(select(CreatorSection).where(CreatorSection.ref == "PLtools")).status = "kept_out"
    session.commit()
    assert left_out(session, waiting) == frozenset({"t1", "t2"})


def test_keeping_a_waiting_list_out_takes_its_videos_and_files_out(waiting, client, session):
    from backend.db.models import Collection, CreatorSection
    from backend.services.link_seasons import leaving_outside

    main_id = waiting.id
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "PLtools", "target": "keep_out"},
    ]})
    assert preview.status_code == 200, preview.text
    [collection] = preview.json()["collections"]
    [part] = collection["parts"]
    assert (part["direction"], part["count"], part["downloadsDeleted"]) == ("leave", 2, 1)

    answered = _answer(client, "keep_out")

    assert answered.status_code == 200, answered.text
    session.expire_all()
    main = session.get(Collection, main_id)
    assert session.scalar(select(CreatorSection.status).where(CreatorSection.ref == "PLtools")) == "kept_out"
    # t2 had no files and went at once; t1 goes once its files are deleted.
    assert _episode(session, main, "t2") is None and _episode(session, main, "v1") is not None
    assert [episode.source_slug for episode in leaving_outside(session, main)] == ["t1"]


def test_a_season_kept_out_leaves_with_its_videos(waiting, client, session):
    from backend.db.models import Collection, CreatorSection

    main_id = waiting.id
    assert _answer(client, "main").status_code == 200
    session.expire_all()
    assert _episode(session, session.get(Collection, main_id), "t2").season.name == "Tool Reviews"

    kept = _answer(client, "keep_out")

    assert kept.status_code == 200, kept.text
    session.expire_all()
    main = session.get(Collection, main_id)
    assert session.scalar(select(CreatorSection.status).where(CreatorSection.ref == "PLtools")) == "kept_out"
    assert _episode(session, main, "t2") is None
    from backend.services.link_seasons import leaving_outside

    # The downloaded one goes once its files are deleted.
    assert [episode.source_slug for episode in leaving_outside(session, main)] == ["t1"]


def test_a_waiting_list_that_becomes_a_season_takes_its_videos_and_files_along(waiting, client, session):
    from backend.db.models import Collection, CreatorSection

    main_id = waiting.id
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "PLtools", "target": "main"},
    ]})
    assert preview.status_code == 200, preview.text
    [collection] = preview.json()["collections"]
    assert collection["slug"] == "UCworkshop"
    [part] = collection["parts"]
    assert (part["direction"], part["count"], part["filesMoved"]) == ("season", 2, 1)

    answered = _answer(client, "main")

    assert answered.status_code == 200, answered.text
    session.expire_all()
    main = session.get(Collection, main_id)
    seasons = {_episode(session, main, slug).season.name for slug in ("t1", "t2")}
    assert seasons == {"Tool Reviews"}
    assert _episode(session, main, "v1").season.name != "Tool Reviews"
    assert session.scalar(select(CreatorSection.status).where(CreatorSection.ref == "PLtools")) == "known"
    # Nothing waits to be moved by hand.
    from backend.services.link_seasons import moved_episodes

    assert moved_episodes(session, main) == []


def test_a_waiting_list_that_becomes_a_collection_takes_its_videos_and_files_along(waiting, client, session):
    from backend.db.models import Collection
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.reassigned import reassigned_in_creator

    main_id = waiting.id
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "PLtools", "target": "own"},
    ]})
    assert preview.status_code == 200, preview.text
    states = {item["slug"]: item["state"] for item in preview.json()["collections"]}
    assert set(states.values()) == {"existing", "new"} and states["UCworkshop"] == "existing"

    answered = _answer(client, "own", type="podcast", episodeIdentifier="date_based")

    assert answered.status_code == 200, answered.text
    session.expire_all()
    main = session.get(Collection, main_id)
    tools = session.scalar(select(Collection).where(Collection.title == "Tool Reviews"))
    assert (tools.type, tools.episode_identifier) == ("podcast", "date_based")
    assert _episode(session, main, "t2") is None and _episode(session, main, "v1") is not None
    t1 = _episode(session, tools, "t1")
    assert t1 is not None and _episode(session, tools, "t2") is not None
    # The download moved along at once, so nothing is left reassigned.
    assert session.scalar(select(EpisodeMediaDownload.media_item_id)) == t1.id
    assert reassigned_in_creator(session, tools.creator) == []

