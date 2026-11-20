"""Moving a creator's feeds and lists from its Edit page: Shorts to a collection of their own and back, livestreams out
of the Library, several at once, what the dialog shows before saving, and numbering again afterwards."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from sources import VideoDetails
from test_creators import ROOT, client, tube  # noqa: F401
from test_reassigned import _download, _episode, _profile, _save, _settled
from test_ytdlp_collections import session  # noqa: F401


def _video(slug: str, day: int = 1, tag: str = "ep") -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://tube.example/watch?v={slug}", title=f"Video {slug}", duration=60.0,
        published_at=datetime(2025, 1, day, tzinfo=timezone.utc), tag=tag,
    )


@pytest.fixture
def feeds(client, session, monkeypatch):
    """A creator whose own collection lists its Videos, Shorts and Livestreams: two uploads, two Shorts (s1 downloaded)
    and two livestreams (l1 downloaded)."""
    import test_creators
    from dataclasses import replace

    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    # The test Site's Shorts and livestreams get their own tags, as YouTube's do.
    monkeypatch.setattr(test_creators, "SHORTS", replace(test_creators.SHORTS, episode_tag="short"))
    site = test_creators.CreatorSource.sites[0]
    types = tuple(
        replace(type_, episode_tag={"shorts": "short", "live": "livestream"}.get(type_.key, type_.episode_tag))
        for type_ in site.section_types
    )
    monkeypatch.setattr(test_creators.CreatorSource, "sites", (replace(site, section_types=types),))

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "shorts", "target": "main"}, {"ref": "streams", "target": "main"},
    ]})
    assert response.status_code == 201, response.text
    main_id = session.scalar(select(Collection.id).where(Collection.slug == "UCworkshop"))
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[
        _video("v1"), _video("v2", 2), _video("s1", 3, "short"), _video("s2", 4, "short"),
        _video("l1", 5, "livestream"), _video("l2", 6, "livestream"),
    ]))
    session.expire_all()
    main = session.get(Collection, main_id)
    local = _profile(session, "shows")
    _download(session, _episode(session, main, "s1"), local)
    _download(session, _episode(session, main, "l1"), local)
    session.commit()
    _settled()
    return session.get(Collection, main_id)


def _operations(session, kind):
    from task_manager.scheduler.db import TaskOperation

    session.expire_all()
    return list(session.scalars(select(TaskOperation).where(TaskOperation.kind == kind)))


def test_shorts_become_a_collection_of_their_own_with_their_files(feeds, client, session):
    from backend.db.models import Collection
    from backend.db.models.media_download import EpisodeMediaDownload

    main_id = feeds.id
    moved = _save(client, "shorts", "own")

    assert moved.status_code == 200, moved.text
    session.expire_all()
    shorts = session.scalar(select(Collection).where(Collection.slug == "UCworkshop-shorts"))
    main = session.get(Collection, main_id)
    assert shorts is not None and shorts.title == "Northwind Workshop Shorts"
    assert sorted(main.feeds) == ["streams", "videos"]
    assert _episode(session, main, "s1") is None and _episode(session, main, "s2") is None
    s1 = _episode(session, shorts, "s1")
    assert s1.episode_identifier.startswith("short.")
    # Its file moves along, as a manual download, since the new collection has no Download Profile yet.
    [download] = session.scalars(select(EpisodeMediaDownload).where(EpisodeMediaDownload.media_item_id == s1.id)).all()
    assert download.download_profile_id is None
    sections = {section["ref"]: section for section in moved.json()["accounts"][0]["sections"]}
    assert sections["shorts"]["collectionSlug"] == "UCworkshop-shorts"
    # The new collection renames the moved file and rewrites its metadata, showing on the Shorts row.
    renumbers = {operation.resource_id: operation for operation in _operations(session, "collection.renumber")}
    assert renumbers[shorts.id].context["sections"] == ["1:shorts"]
    # One action for the whole move tells the user; the new collection's numbering and its indexing are its parts.
    [move] = _operations(session, "creator.move_sections")
    assert (move.resource_type, move.source, move.context["sections"]) == ("creator", "UI", ["1:shorts"])
    assert move.context["names"]["plural"] == "shorts"
    assert sorted(dependency.child_operation.kind for dependency in move.dependencies) == [
        "collection.index", "collection.renumber",
    ]
    assert {dependency.child_operation.source for dependency in move.dependencies} == {"SYSTEM"}


def test_shorts_join_the_creators_collection_again_and_their_collection_goes(feeds, client, session):
    from backend.db.models import Collection, Episode
    from backend.db.models.media_download import EpisodeMediaDownload

    main_id = feeds.id
    assert _save(client, "shorts", "own").status_code == 200
    session.expire_all()
    shorts_id = session.scalar(select(Collection.id).where(Collection.slug == "UCworkshop-shorts"))
    download_id = session.scalar(select(EpisodeMediaDownload.id).join(Episode, Episode.id == EpisodeMediaDownload.media_item_id).where(
        Episode.collection_id == shorts_id,
    ))

    _settled()
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "shorts", "target": "main"},
    ]})
    assert preview.status_code == 200, preview.text
    states = {item["slug"]: item["state"] for item in preview.json()["collections"]}
    assert states == {"UCworkshop": "existing", "UCworkshop-shorts": "deleted"}

    back = _save(client, "shorts", "main")

    assert back.status_code == 200, back.text
    session.expire_all()
    assert session.get(Collection, shorts_id) is None
    assert sorted(session.get(Collection, main_id).feeds) == ["shorts", "streams", "videos"]
    assert session.get(EpisodeMediaDownload, download_id).media.collection_id == main_id


def test_livestreams_leave_the_library_with_their_files(feeds, client, session):
    from backend.db.models import Collection, CreatorSection

    main_id = feeds.id
    out = _save(client, "streams", "exclude")

    assert out.status_code == 200, out.text
    session.expire_all()
    main = session.get(Collection, main_id)
    assert sorted(main.feeds) == ["shorts", "videos"]
    # The one without files is gone at once; the downloaded one leaves once its files are deleted.
    assert _episode(session, main, "l2") is None
    assert _episode(session, main, "l1").from_link_season
    assert session.scalar(select(CreatorSection.status).where(CreatorSection.ref == "streams")) == "ignored"
    assert _episode(session, main, "v1") is not None and _episode(session, main, "s1") is not None
    # Deleting the downloaded one's files runs as a task of the move's own operation, so its progress counts too.
    [move] = _operations(session, "creator.move_sections")
    assert [(target.task_key, target.resource_id) for target in move.targets] == [("remove_left_episodes", main_id)]


def test_the_videos_feed_never_becomes_a_collection_of_its_own(feeds, client):
    refused = _save(client, "videos", "own")
    assert refused.status_code == 422 and "stays in it or leaves your library" in refused.text


def test_the_preview_shows_what_saving_does_and_changes_nothing(feeds, client, session):
    from backend.db.models import Collection

    main_id = feeds.id
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "shorts", "target": "own"}, {"accountId": 1, "ref": "streams", "target": "exclude"},
    ]})

    assert preview.status_code == 200, preview.text
    collections = {item["title"]: item for item in preview.json()["collections"]}
    main, shorts = collections["Northwind Workshop"], collections["Northwind Workshop Shorts"]
    assert shorts["state"] == "new" and shorts["indexed"]
    parts = {(part["sectionTitle"], part["direction"]): part for part in main["parts"]}
    assert parts[("Shorts", "out")]["count"] == 2 and parts[("Shorts", "out")]["otherTitle"] == "Northwind Workshop Shorts"
    leaving = parts[("Livestreams", "leave")]
    assert (leaving["count"], leaving["downloadsDeleted"], leaving["deletingProfiles"]) == (2, 1, ["Shows"])
    assert leaving["examples"] == ["Video l2", "Video l1"]
    [moved_in] = shorts["parts"]
    assert (moved_in["direction"], moved_in["count"], moved_in["filesMoved"]) == ("in", 2, 1)
    # Nothing moved.
    session.expire_all()
    assert session.scalar(select(Collection.id).where(Collection.slug == "UCworkshop-shorts")) is None
    assert session.get(Collection, main_id).feeds == ["shorts", "streams", "videos"]
    assert _operations(session, "collection.renumber") == []


def _with_gaps(main_id):
    """Number the creator's collection's uploads 10 and 20, as gaps left by videos that went would."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, Episode

    def gap(w):
        w.get(Collection, main_id).episode_identifier = "numbered"
        for number, episode in enumerate(w.scalars(select(Episode).where(
            Episode.collection_id == main_id, Episode.episode_identifier.like("ep.%"),
        ).order_by(Episode.published_date)), start=1):
            episode.episode_identifier = f"ep.{number * 10}"

    run_write_transaction(gap)


@pytest.mark.parametrize("again", [True, False])
def test_a_collection_that_lost_videos_numbers_the_rest_again_unless_told_not_to(feeds, client, session, again):
    main_id = feeds.id
    _with_gaps(main_id)
    preview = client.post("/api/creators/workshop/moves/preview", json={"moves": [
        {"accountId": 1, "ref": "shorts", "target": "own"},
    ]})
    main = next(item for item in preview.json()["collections"] if item["slug"] == "UCworkshop")
    assert main["renumberOffered"]
    assert [(change["before"], change["after"]) for change in main["changes"]] == [("20", "2"), ("10", "1")]

    saved = _save(client, "shorts", "own", renumber={} if again else {"UCworkshop": False})

    assert saved.status_code == 200, saved.text
    renumbers = {operation.resource_id: operation for operation in _operations(session, "collection.renumber")}
    if again:
        assert renumbers[main_id].context["renumber"] is True
    else:
        # Nothing moved into it and it keeps its numbers, so its files stay as they are.
        assert main_id not in renumbers


def test_renumbering_again_keeps_the_identification_and_gives_the_numbers_again(feeds, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode
    from backend.services.episode_identification import change_identification
    from backend.types.collection_types import EpisodeIdentifier

    main_id = feeds.id
    _with_gaps(main_id)
    renumbered, _profiles = run_write_transaction(
        lambda w: change_identification(w, main_id, EpisodeIdentifier.NUMBERED, episode_order=None),
    )

    assert renumbered == 2
    session.expire_all()
    assert sorted(session.scalars(select(Episode.episode_identifier).where(
        Episode.collection_id == main_id, Episode.episode_identifier.like("ep.%"),
    ))) == ["ep.1", "ep.2"]
