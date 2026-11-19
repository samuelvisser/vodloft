"""Reassigned: a creator keeps each video in one collection, and a downloaded video that a list of another collection
holds now waits there, files and all, until it is moved."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from sources import VideoDetails
from test_creators import ROOT, client, tube  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401


def _video(slug: str, day: int = 1) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://tube.example/watch?v={slug}", title=f"Video {slug}", duration=60.0,
        published_at=datetime(2025, 1, day, tzinfo=timezone.utc),
    )


@pytest.fixture
def creator(client, session):
    """A creator whose own collection takes its uploads with Building the Cabin as a season, and whose Tool Reviews
    playlist is a collection of its own. Upload t1 is in Tool Reviews, c1 in both playlists."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CollectionList, CollectionListItem
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLcabin", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    assert response.status_code == 201, response.text
    main = session.scalar(select(Collection).where(Collection.slug == "UCworkshop"))
    tools = session.scalar(select(Collection).where(Collection.slug == "PLtools"))
    main_id, tools_id = main.id, tools.id
    cabin = next(link for link in main.lists if link.ref == "PLcabin")
    session.add(CollectionListItem(list_id=cabin.id, source_slug="c1", position=1))
    session.commit()
    # Indexed before the creator knew Tool Reviews had t1.
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[_video("t1"), _video("t2", 2), _video("c1", 3)]))
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=tools_id, found=[_video("t1"), _video("t2", 2), _video("c1", 3)]))
    session.expire_all()
    assert session.scalar(select(CollectionList.id).where(CollectionList.id == cabin.id)) is not None
    return session.get(Collection, main_id), session.get(Collection, tools_id)


def _episode(session, collection, slug):
    from backend.db.models import Episode

    return session.scalar(select(Episode).where(Episode.collection_id == collection.id, Episode.source_slug == slug))


def _profile(session, slug):
    from backend.db.models import CollectionLocalMediaProfile

    profile = CollectionLocalMediaProfile(
        slug=slug, name=slug.title(), preferred_format="format_1080p",
        output_template=f"/downloads/{slug}/{{{{ collection_title }}}}/{{{{ episode_title }}}}.ext",
    )
    session.add(profile)
    session.flush()
    return profile


def _download(session, episode, local, download_profile=None, status="available"):
    from backend.db.models.media_download import EpisodeMediaDownload

    download = EpisodeMediaDownload(
        media=episode, local_media_profile=local, type="episode", file_path=f"/downloads/{episode.slug}.mp4",
        artifact_status=status, download_profile_id=download_profile.id if download_profile else None,
        **({"artifact_stat_dev": "1", "artifact_stat_ino": "2", "artifact_size_bytes": 3, "artifact_fingerprint": "f" * 64}
           if status == "available" else {}),
    )
    session.add(download)
    session.flush()
    return download


def _download_profile(session, collection, local):
    from backend.db.models import DownloadProfile

    profile = DownloadProfile(collection_id=collection.id, local_media_profile_id=local.id, enable_profile=True)
    session.add(profile)
    session.flush()
    return profile


def test_a_downloaded_video_a_playlist_of_another_collection_holds_is_reassigned(creator, session):
    from backend.services.reassigned import awaiting_move, reassigned_episodes, settle_creator
    from backend.db.core import run_write_transaction

    main, tools = creator
    local = _profile(session, "shows")
    _download(session, _episode(session, main, "t1"), local, _download_profile(session, main, local))
    session.commit()

    assert [(item.episode.source_slug, item.target.collection.slug) for item in reassigned_episodes(session, main)] == [
        ("t1", "PLtools"),
    ]
    # Tool Reviews leaves it alone until it is moved there, so it is not downloaded twice.
    assert awaiting_move(session, tools) == {_episode(session, tools, "t1").id}
    # c1 is in a playlist season of the creator's own collection too, so it stays where it is.
    assert reassigned_episodes(session, tools) == []

    # One that is not downloaded simply leaves for its playlist's collection.
    assert run_write_transaction(lambda w: settle_creator(w, w.get(type(main), main.id))) == 1
    session.expire_all()
    assert _episode(session, main, "t2") is None and _episode(session, tools, "t2") is not None
    assert _episode(session, main, "t1") is not None


def test_a_collection_does_not_add_a_video_a_playlist_of_another_collection_holds(creator, session):
    from backend.db.core import run_write_transaction
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes, known_episode_slugs

    main, tools = creator
    main_id = main.id
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=tools.id, found=[_video("t3", 4)]))
    session.expire_all()

    assert "t3" in known_episode_slugs(session, session.get(type(main), main_id))
    session.rollback()
    assert run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[_video("t3", 4)])) == 0
    # A collection made from a playlist adds every video of its playlist.
    from backend.services.reassigned import placed_elsewhere

    assert placed_elsewhere(session, session.get(type(tools), tools.id)) == frozenset()


def _move(session, episode):
    from backend.db.core import run_write_transaction
    from backend.services.reassigned import move_and_rename, reassignment_of

    episode_id = episode.id
    session.commit()

    def work(w):
        from backend.db.models import Episode

        return move_and_rename(w, [reassignment_of(w, w.get(Episode, episode_id))])

    result, operations = run_write_transaction(work)
    session.expire_all()
    return result, operations


def test_moving_renames_a_download_the_new_collection_takes_with_the_same_local_media_profile(creator, session):
    main, tools = creator
    shows, other = _profile(session, "shows"), _profile(session, "other")
    download = _download(session, _episode(session, main, "t1"), shows, _download_profile(session, main, shows))
    _download_profile(session, tools, other)
    keeper = _download_profile(session, tools, shows)
    download_id, keeper_id = download.id, keeper.id

    result, operations = _move(session, _episode(session, main, "t1"))

    assert (result.renamed, result.downloading, len(operations)) == (1, 0, 1)
    from backend.db.models.media_download import EpisodeMediaDownload

    moved = session.get(EpisodeMediaDownload, download_id)
    # The profile with the same Local Media Profile keeps it, though another one came first.
    assert (moved.media.collection_id, moved.download_profile_id) == (tools.id, keeper_id)
    assert _episode(session, main, "t1") is None


def test_a_download_no_profile_of_the_new_collection_takes_becomes_manual_and_a_manual_one_stays_manual(creator, session):
    main, tools = creator
    shows = _profile(session, "shows")
    download = _download(session, _episode(session, main, "t1"), shows, _download_profile(session, main, shows))
    download_id = download.id

    result, _operations = _move(session, _episode(session, main, "t1"))

    from backend.db.models.media_download import EpisodeMediaDownload

    moved = session.get(EpisodeMediaDownload, download_id)
    assert result.renamed == 1
    assert (moved.media.collection_id, moved.download_profile_id) == (tools.id, None)


def test_a_new_local_media_profile_downloads_again_and_the_old_files_go_only_once_it_succeeded(creator, session):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.reassigned import awaiting_move, replaced_sources

    main, tools = creator
    shows, music = _profile(session, "shows"), _profile(session, "music")
    _download(session, _episode(session, main, "t1"), shows, _download_profile(session, main, shows))
    music_profile = _download_profile(session, tools, music)
    music_profile_id = music_profile.id

    result, operations = _move(session, _episode(session, main, "t1"))

    assert (result.renamed, result.downloading, operations) == (0, 1, [])
    target = _episode(session, tools, "t1")
    [again] = target.downloads
    assert (again.download_profile_id, again.artifact_status) == (music_profile_id, "absent")
    # The old one stays, Reassigned, with its files, while the new one downloads.
    assert _episode(session, main, "t1") is not None
    assert awaiting_move(session, tools) == set()
    assert replaced_sources(session, main) == []

    done = session.get(EpisodeMediaDownload, again.id)
    done.artifact_status, done.artifact_stat_dev, done.artifact_stat_ino = "available", "1", "3"
    done.artifact_size_bytes, done.artifact_fingerprint = 3, "g" * 64
    session.commit()
    assert [episode.source_slug for episode in replaced_sources(session, main)] == ["t1"]


def test_the_api_shows_and_moves_reassigned_episodes(creator, client, session):
    main, _tools = creator
    shows = _profile(session, "shows")
    _download(session, _episode(session, main, "t1"), shows, _download_profile(session, main, shows))
    t1_slug = _episode(session, main, "t1").slug
    session.commit()

    listed = client.get("/api/collections/UCworkshop/season-settings/reassigned-episodes").json()
    assert listed == {"episodes": [{"episodeSlug": t1_slug, "collectionSlug": "PLtools", "collectionTitle": "Tool Reviews"}]}
    assert t1_slug not in client.get("/api/collections/UCworkshop/season-settings/moved-episodes").json()["episodeSlugs"]
    assert client.get("/api/creators/workshop").json()["reassignedCount"] == 1

    moved = client.post("/api/creators/workshop/move-reassigned")

    assert moved.status_code == 200, moved.text
    assert (moved.json()["episodes"], moved.json()["renamed"]) == (1, 1)
    assert client.get("/api/creators/workshop").json()["reassignedCount"] == 0


def _cabin_video(session, main):
    """k1, an upload of the creator that only its Building the Cabin playlist season has, downloaded."""
    from backend.db.core import run_write_transaction
    from backend.db.models import CollectionList, CollectionListItem
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    main_id = main.id
    cabin = session.scalar(select(CollectionList).where(CollectionList.collection_id == main_id, CollectionList.ref == "PLcabin"))
    session.add(CollectionListItem(list_id=cabin.id, source_slug="k1", position=2))
    session.commit()
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=main_id, found=[_video("k1", 5)]))
    session.expire_all()
    shows = _profile(session, "shows")
    _download(session, _episode(session, session.get(type(main), main_id), "k1"), shows)
    session.commit()


def test_a_playlist_season_moves_to_a_collection_of_its_own_with_its_files(creator, client, session):
    from backend.db.models import Collection, CollectionList
    from backend.db.models.media_download import EpisodeMediaDownload

    main, _tools = creator
    _cabin_video(session, main)

    moved = client.post("/api/creators/workshop/accounts/1/sections/PLcabin/move", json={"target": "own"})

    assert moved.status_code == 200, moved.text
    session.expire_all()
    cabin = session.scalar(select(Collection).where(Collection.sharing_url == "https://tube.example/playlist?list=PLcabin"))
    assert cabin is not None and cabin.creator_id == main.creator_id
    k1 = _episode(session, cabin, "k1")
    # The download moved along, as a manual download, since the new collection has no Download Profile yet.
    [download] = session.scalars(select(EpisodeMediaDownload).where(EpisodeMediaDownload.media_item_id == k1.id)).all()
    assert download.download_profile_id is None
    assert _episode(session, main, "k1") is None
    assert session.scalar(select(CollectionList.enabled).where(
        CollectionList.collection_id == main.id, CollectionList.ref == "PLcabin",
    )) is False
    page = moved.json()
    assert {section["ref"]: section["collectionSlug"] for section in page["accounts"][0]["sections"]}["PLcabin"] == cabin.slug


def test_a_playlist_collection_becomes_a_season_and_goes_once_it_is_empty(creator, client, session):
    from backend.db.models import Collection
    from backend.db.models.media_download import EpisodeMediaDownload

    main, tools = creator
    shows = _profile(session, "shows")
    download = _download(session, _episode(session, tools, "t1"), shows)
    download_id, tools_id = download.id, tools.id
    session.commit()

    moved = client.post("/api/creators/workshop/accounts/1/sections/PLtools/move", json={"target": "main"})

    assert moved.status_code == 200, moved.text
    session.expire_all()
    assert session.get(Collection, tools_id) is None
    assert session.get(EpisodeMediaDownload, download_id).media.collection_id == main.id
    season = _episode(session, main, "t1").season
    assert season.name == "Tool Reviews"


def test_a_playlist_season_leaves_the_library_and_a_collection_of_its_own_must_be_deleted_instead(creator, client, session):
    out = client.post("/api/creators/workshop/accounts/1/sections/PLcabin/move", json={"target": "skip"})
    assert out.status_code == 200, out.text
    sections = {section["ref"]: section for section in out.json()["accounts"][0]["sections"]}
    assert (sections["PLcabin"]["collectionSlug"], sections["PLcabin"]["status"]) == (None, "ignored")

    refused = client.post("/api/creators/workshop/accounts/1/sections/PLtools/move", json={"target": "skip"})
    assert refused.status_code == 422 and "delete that collection" in refused.text


def test_a_video_only_the_playlist_collection_has_joins_the_creators_collection_with_its_files(creator, client, session):
    from backend.db.core import run_write_transaction
    from backend.db.models.media_download import EpisodeMediaDownload
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    main, tools = creator
    main_id, tools_id = main.id, tools.id
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=tools_id, found=[_video("t4", 6)]))
    session.expire_all()
    download = _download(session, _episode(session, session.get(type(tools), tools_id), "t4"), _profile(session, "shows"))
    download_id = download.id
    session.commit()

    assert client.post("/api/creators/workshop/accounts/1/sections/PLtools/move", json={"target": "main"}).status_code == 200

    session.expire_all()
    moved = session.get(EpisodeMediaDownload, download_id)
    assert (moved.media.collection_id, moved.media.season.name) == (main_id, "Tool Reviews")
