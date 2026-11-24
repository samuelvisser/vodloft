"""Deleting a collection takes its episodes, their downloads and their scheduler work with it, and nothing else."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session():
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    if engine.dialect.name == "sqlite":
        # As VODLoft's own database does: the rows of an episode and a download follow through their foreign keys.
        event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _collection_with_episodes(s: Session, name: str, episodes: int):
    """A collection whose episodes each have metadata, a downloaded file with an asset and history, and a task."""
    from backend.db.models import Collection, CollectionLocalMediaProfile, Episode, Season
    from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadAsset, MediaDownloadHistory
    from backend.types.collection_types import CollectionType, EpisodeIdentifier
    from conftest import available_artifact
    from task_manager.scheduler.db import TaskDefinition, TaskRun
    from task_manager.scheduler.types import ResourceType, TaskStatus

    if s.get(CollectionLocalMediaProfile, 1) is None:
        s.add(CollectionLocalMediaProfile(
            id=1, slug="videos", name="Videos", preferred_format="format_1080p",
            output_template="/downloads/{{ collection_title }}/{{ episode_title }}.ext",
        ))
        s.add(TaskDefinition(
            key="episode_worker", title="Episode worker", description=None,
            allowed_resource_types=["episode", "media_download"], default_max_retries=0,
        ))
        s.flush()
    definition_id = s.scalar(select(TaskDefinition.id))

    collection = Collection(
        source_key="ytdlp", uuid=name, slug=name, title=name, description=None,
        membership_level="FREE", sharing_url=f"https://www.youtube.com/@{name}", type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="Host", author_slug="host",
    )
    season = Season(collection=collection, index=1, slug=f"{name}-videos", name="Videos", season_type="regular")
    s.add_all([collection, season])
    s.flush()
    for index in range(episodes):
        episode = Episode(
            uuid=f"{name}-{index}", source_key="ytdlp", collection_id=collection.id, season_id=season.id, index=index,
            episode_identifier=str(index), slug=f"{name}-{index}", source_slug=f"{name}-{index}",
            publish_status="PUBLISHED", sharing_url=f"https://www.youtube.com/watch?v={name}{index}",
            title=f"Video {index}",
        )
        episode.set_meta("chapters", "[]")
        s.add(episode)
        s.flush()
        download = EpisodeMediaDownload(
            type="episode", media_item_id=episode.id, local_media_profile_id=1,
            file_path=f"/downloads/{name}/{index}.mp4", **available_artifact(),
        )
        download.set_meta("format", "1080p")
        s.add(download)
        s.flush()
        s.add_all([
            MediaDownloadAsset(
                media_download_id=download.id, asset_key="thumbnail", kind="thumbnail",
                path=f"/downloads/{name}/{index}.jpg", suffix=".jpg", size_bytes=None, fingerprint=None,
            ),
            MediaDownloadHistory(media_download_id=download.id, action="downloaded"),
        ] + [
            TaskRun(
                definition_id=definition_id, resource_type=resource_type, resource_id=resource_id,
                status=TaskStatus.SCHEDULED, attempt_count=0, max_retries=0,
                next_retry_at=None, started_at=datetime.now(timezone.utc),
            )
            for resource_type, resource_id in (
                (ResourceType.EPISODE, episode.id), (ResourceType.MEDIA_DOWNLOAD, download.id),
            )
        ])
    s.commit()
    return collection


def _counts(s: Session) -> dict[str, int]:
    from backend.db.models import Episode, MediaDownloadBase, MediaItemBase, Metadata, Season
    from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadAsset, MediaDownloadHistory
    from task_manager.scheduler.db import TaskRun

    tables = {
        "media items": MediaItemBase, "episodes": Episode, "seasons": Season, "metadata": Metadata,
        "downloads": MediaDownloadBase, "episode downloads": EpisodeMediaDownload, "assets": MediaDownloadAsset,
        "history": MediaDownloadHistory, "task runs": TaskRun,
    }
    return {name: s.scalar(select(func.count()).select_from(model)) for name, model in tables.items()}


def test_deleting_collections_takes_their_episodes_and_downloads(session) -> None:
    from backend.api.endpoints.collections.bulk import delete_collections
    from backend.api.models.profile_bulk import BulkSelectionIn
    from backend.db.models import Collection

    kept = _collection_with_episodes(session, "kept", 2)
    alone = _counts(session)
    gone = [_collection_with_episodes(session, f"gone-{index}", 3) for index in range(2)]

    result = delete_collections(session, BulkSelectionIn(ids=[item.id for item in gone]))
    session.commit()

    assert result.done == 2
    assert [item.slug for item in session.query(Collection)] == ["kept"]
    assert _counts(session) == alone
    assert [episode.index for episode in kept.episodes] == [1, 0]


def test_deleting_a_collection_whose_episodes_are_loaded(session) -> None:
    """Episodes and downloads the session already holds do not get in the way."""
    from backend.api.endpoints.collections.service import delete_collection

    collection = _collection_with_episodes(session, "loaded", 2)
    assert [len(episode.downloads) for episode in collection.episodes] == [1, 1]
    assert [len(season.episodes) for season in collection.seasons] == [2]

    delete_collection(session, "loaded")
    session.commit()

    assert set(_counts(session).values()) == {0}
