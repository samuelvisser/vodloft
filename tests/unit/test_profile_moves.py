"""Moving episode downloads from one Local Media Profile to another."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from conftest import available_artifact

OLD = "/downloads/Old/{{ collection_title }}/{{ title }}.ext"
NEW = "/downloads/New/{{ collection_title }}/S01E{{ episode_index }} {{ title }}.ext"


def _session() -> Session:
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def library(tmp_path, monkeypatch):
    from backend.db.models import Collection, Episode, LocalMediaProfile, Season
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.collection_types import CollectionType, EpisodeIdentifier
    from backend.types.media_types import MediaType
    from config import get_settings

    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    session = _session()
    collection = Collection(
        source_key="ytdlp", uuid="c", slug="show", title="Show", description="",
        sharing_url="https://www.youtube.com/@show", membership_level="FREE", type=CollectionType.SERIES.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="Show", author_slug="show",
    )
    season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
    episodes = [
        Episode(
            source_key="ytdlp", uuid=f"e{index}", type=MediaType.EPISODE.value, collection=collection, season=season,
            index=index, episode_identifier=f"ep.{index}", slug=f"episode-{index}", source_slug=f"site{index}",
            title=f"Episode {index}", description="", duration=60, publish_status="published_final",
            sharing_url=f"https://www.youtube.com/watch?v=site{index}",
            published_date=datetime(2024, 1, index, 12, tzinfo=timezone.utc),
        )
        for index in range(1, 5)
    ]
    source = LocalMediaProfile(
        slug="legacy", name="Legacy", output_template=OLD,
        preferred_format="format_1080p", metadata_mode="no_metadata", thumbnail_mode="no_thumbnail",
    )
    target = LocalMediaProfile(
        slug="plex", name="Plex", output_template=NEW,
        preferred_format="format_1080p", metadata_mode="nfo", thumbnail_mode="no_thumbnail",
    )
    session.add_all([collection, season, *episodes, source, target])
    session.flush()

    downloads = []
    for episode in episodes:
        path = tmp_path / "Old" / "Show" / f"{episode.title}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(episode.title.encode())
        download = EpisodeMediaDownload(
            type=MediaType.EPISODE.value, media_item_id=episode.id, local_media_profile_id=source.id,
            file_path=str(path), **available_artifact(path),
        )
        downloads.append(download)
    session.add_all(downloads)
    session.commit()
    return session, collection, source, target, episodes, downloads, tmp_path


def _target_download(session, target, episode, *, path: Path | None = None):
    from backend.db.models.media_download import EpisodeMediaDownload

    fields = available_artifact(path) if path is not None else {"artifact_status": "absent"}
    download = EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=target.id,
        file_path=str(path or "/nowhere.mp4"), **fields,
    )
    session.add(download)
    session.commit()
    return download


def test_the_preview_says_what_happens_to_each_episode(library):
    from backend.services.profile_moves import plan_profile_move

    session, collection, source, target, episodes, downloads, root = library
    # Episode 2: the target already has a file. Episode 3: its file is gone.
    # Episode 4: the target only has a record without a file.
    taken = root / "New" / "Show" / "S01E2 Episode 2.mp4"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"target copy")
    _target_download(session, target, episodes[1], path=taken)
    Path(downloads[2].file_path).unlink()
    _target_download(session, target, episodes[3])

    (plan,) = plan_profile_move(session, source, target)

    outcomes = {item.episode.title: (item.outcome.value, item.destination) for item in plan.episodes}
    assert outcomes == {
        "Episode 1": ("move", root / "New" / "Show" / "S01E1 Episode 1.mp4"),
        "Episode 2": ("target_has_file", None),
        "Episode 3": ("file_missing", None),
        "Episode 4": ("replace", root / "New" / "Show" / "S01E4 Episode 4.mp4"),
    }
    assert plan.in_scope and not plan.blocked and not plan.can_move_download_profile


def test_a_file_vodloft_does_not_manage_keeps_its_path(library):
    from backend.services.profile_moves import plan_profile_move

    session, collection, source, target, episodes, downloads, root = library
    stranger = root / "New" / "Show" / "S01E1 Episode 1.mp4"
    stranger.parent.mkdir(parents=True)
    stranger.write_bytes(b"not ours")

    (plan,) = plan_profile_move(session, source, target)

    assert plan.episodes[0].outcome.value == "path_taken"


def test_two_episodes_with_one_new_path_block_the_collection(library):
    from backend.services.profile_moves import plan_profile_move

    session, collection, source, target, episodes, downloads, root = library
    target.output_template = "/downloads/New/{{ collection_title }}.ext"
    session.commit()

    (plan,) = plan_profile_move(session, source, target)

    assert plan.blocked
    assert {item.outcome.value for item in plan.episodes} == {"same_path"}


def test_moving_hands_the_downloads_over_and_moves_their_files(library):
    from backend.db.models import DownloadProfile, MediaDownloadHistory
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.profile_moves import move_collection_downloads

    session, collection, source, target, episodes, downloads, root = library
    subtitle = root / "Old" / "Show" / "Episode 1.en.srt"
    subtitle.write_bytes(b"1")
    download_profile = DownloadProfile(collection=collection, local_media_profile=source, enable_profile=False)
    session.add(download_profile)
    session.flush()
    downloads[0].kept = True
    for download in downloads:
        download.download_profile_id = download_profile.id
    taken = root / "New" / "Show" / "S01E2 Episode 2.mp4"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"target copy")
    _target_download(session, target, episodes[1], path=taken)
    _target_download(session, target, episodes[3])

    result = move_collection_downloads(
        session, source_id=source.id, target_id=target.id, collection_id=collection.id,
        move_download_profile=True,
    )

    assert (result.moved, result.skipped, result.download_profiles_moved) == (3, 1, 1)
    moved = session.get(EpisodeMediaDownload, downloads[0].id)
    assert moved.local_media_profile_id == target.id and moved.kept
    assert moved.file_path == str(root / "New" / "Show" / "S01E1 Episode 1.mp4")
    assert Path(moved.file_path).read_bytes() == b"Episode 1"
    assert not (root / "Old" / "Show" / "Episode 1.mp4").exists()
    # Episode 2 stayed, so its folder is still there.
    assert (root / "Old" / "Show").is_dir()
    # The subtitle next to the file moved along; the NFO the target asks for was written.
    assert sorted((asset.kind, Path(asset.path).name) for asset in moved.assets) == [
        ("nfo", "S01E1 Episode 1.nfo"), ("subtitle", "S01E1 Episode 1.en.srt"),
    ]
    assert (root / "New" / "Show" / "S01E1 Episode 1.nfo").read_bytes().startswith(b"<?xml")
    actions = [entry.action for entry in session.scalars(select(MediaDownloadHistory).where(
        MediaDownloadHistory.media_download_id == moved.id,
    ))]
    assert sorted(actions) == ["artifact_renamed", "moved"]

    # Episode 2 stays with the source, its file untouched.
    stayed = session.get(EpisodeMediaDownload, downloads[1].id)
    assert stayed.local_media_profile_id == source.id and Path(stayed.file_path).exists()
    assert stayed.download_profile_id is None
    # Episode 4's empty target record made way for the moved download.
    replaced = session.scalars(select(EpisodeMediaDownload).where(
        EpisodeMediaDownload.media_item_id == episodes[3].id,
        EpisodeMediaDownload.local_media_profile_id == target.id,
    )).one()
    assert replaced.id == downloads[3].id
    # The Download Profile moved along and still manages the moved downloads.
    assert download_profile.local_media_profile_id == target.id
    assert moved.download_profile_id == download_profile.id


def test_retention_counts_the_moved_episodes_the_target_would_delete(library):
    from backend.db.models import DownloadProfile
    from backend.services.profile_moves import plan_profile_move

    session, collection, source, target, episodes, downloads, root = library
    downloads[0].kept = True
    session.add(DownloadProfile(
        collection=collection, local_media_profile=target, download_episode_count=1, delete_older_episodes=True,
    ))
    session.commit()

    (plan,) = plan_profile_move(session, source, target)

    # The newest episode stays inside the window and the oldest is kept; two would go.
    assert plan.retention_at_risk == 2


def test_requesting_a_move_pauses_the_download_profiles_and_refuses_a_blocked_collection(library, monkeypatch):
    from backend.api.endpoints.local_media_profiles import move
    from backend.api.models.local_media_profile_move import LocalMediaProfileMoveAPIRequest
    from backend.db.models import DownloadProfile

    session, collection, source, target, episodes, downloads, root = library
    download_profile = DownloadProfile(collection=collection, local_media_profile=source, enable_profile=True)
    session.add(download_profile)
    session.commit()
    queued = []
    monkeypatch.setattr(move, "queue_operation_target_dispatch", lambda s, operation_id, slot: queued.append(slot))
    request = LocalMediaProfileMoveAPIRequest.model_validate({
        "targetSlug": "plex", "collections": [{"collectionId": collection.id, "moveDownloadProfile": True}],
    })

    result = move.request_move(session, "legacy", request)

    assert (result["episodes_queued"], result["download_profiles_paused"]) == (4, 1)
    assert download_profile.enable_profile is False
    assert queued == [f"collection:{collection.id}"]

    target.output_template = "/downloads/New/{{ collection_title }}.ext"
    session.commit()
    with pytest.raises(HTTPException, match="same path"):
        move.request_move(session, "legacy", request)


def test_the_preview_reads_as_the_api_shows_it(library):
    from backend.api.endpoints.local_media_profiles.move import get_move_preview

    session, collection, source, target, episodes, downloads, root = library

    preview = get_move_preview(session, "legacy", "plex").model_dump(by_alias=True, mode="json")

    assert preview["target"]["slug"] == "plex"
    (entry,) = preview["collections"]
    assert entry["collectionTitle"] == "Show" and entry["inScope"] is True
    assert entry["episodes"][0] == {
        "mediaDownloadId": downloads[0].id, "episodeId": episodes[0].id, "episodeSlug": "episode-1",
        "episodeTitle": "Episode 1", "outcome": "move",
        "sourcePath": str(root / "Old" / "Show" / "Episode 1.mp4"),
        "destinationPath": str(root / "New" / "Show" / "S01E1 Episode 1.mp4"),
    }


def test_folders_the_move_leaves_empty_are_removed(library):
    from backend.services.profile_moves import move_collection_downloads

    session, collection, source, target, episodes, downloads, root = library

    result = move_collection_downloads(
        session, source_id=source.id, target_id=target.id, collection_id=collection.id,
        move_download_profile=False,
    )

    assert result.moved == 4
    assert not (root / "Old").exists()
    assert root.is_dir()
