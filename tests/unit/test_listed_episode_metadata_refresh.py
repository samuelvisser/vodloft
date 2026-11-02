"""The per-episode metadata refresh only reads episodes from The Daily Wire, never listed episodes."""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import Feature, Source, registry


class ListedSource(Source):
    id = "listed"
    name = "Listed"
    domains = ("listed.example",)
    features = frozenset({Feature.COLLECTIONS, Feature.EPISODE_LISTS})

    def resolve(self, url):
        return None

    def episode_media(self, **_kwargs):
        raise NotImplementedError

    def movie_playback(self, **_kwargs):
        raise NotImplementedError


@pytest.fixture
def listed(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(ListedSource())


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _collection(session, source_key="listed"):
    from backend.db.models import Collection

    collection = Collection(
        uuid="uuid-PL1", slug="PL1", source_key=source_key, title="A playlist",
        sharing_url="https://www.youtube.com/playlist?list=PL1", membership_level="FREE",
        type="podcast", episode_identifier="date_based", author_name="A Channel", author_slug="a-channel",
    )
    session.add(collection)
    session.commit()
    return collection


def _episode(session, collection, slug, identifier, *, status="published_final", metadata_is_final=True):
    from backend.db.models import Episode, Season

    season = collection.seasons[0] if collection.seasons else Season(
        collection_id=collection.id, index=1, slug="2021", name="2021", season_number=2021,
    )
    if season.id is None:
        session.add(season)
        session.flush()
        session.refresh(collection)
    episode = Episode(
        uuid=f"uuid-{slug}", type="episode", source_key=collection.source_key, collection_id=collection.id,
        season_id=season.id, index=1,
        episode_identifier=identifier, slug=slug, source_slug=slug, publish_status=status,
        metadata_is_final=metadata_is_final, sharing_url=f"https://www.youtube.com/watch?v={slug}",
        published_date=datetime(2021, 1, 1, tzinfo=timezone.utc), title=f"Video {slug}",
    )
    session.add(episode)
    session.commit()
    return episode


def test_the_refresh_worker_never_asks_the_daily_wire_about_a_listed_episode(listed, session, monkeypatch):
    from task_manager.tasks.workers.refresh_episode_metadata import service

    collection = _collection(session)
    episode = _episode(session, collection, "VsUtykQi2uE", "ep.2021-01-01T00:00:00.000000", metadata_is_final=False)

    def daily_wire(**_kwargs):
        raise AssertionError("The Daily Wire was asked about a listed episode")

    removed: list[int] = []
    monkeypatch.setattr(service, "_fetch_episode_from_dailywire", daily_wire)
    monkeypatch.setattr(service, "remove_episode_metadata_jobs", removed.append)

    assert asyncio.run(service.run_refresh_episode_metadata(session, episode_id=episode.id, refresh=True)) is False

    session.refresh(episode)
    assert episode.publish_status == "published_final"
    assert episode.episode_identifier == "ep.2021-01-01T00:00:00.000000"
    assert episode.metadata_is_final is True
    assert removed == [episode.id]


def test_metadata_refresh_cannot_be_requested_for_listed_episodes(listed, session):
    from backend.api.endpoints.collections.service import request_collection_metadata_refresh
    from backend.api.endpoints.episodes.service import request_episode_metadata_refresh

    collection = _collection(session)
    _episode(session, collection, "VsUtykQi2uE", "ep.2021-01-01T00:00:00.000000")

    with pytest.raises(HTTPException) as collection_refresh:
        request_collection_metadata_refresh(session, "PL1")
    assert collection_refresh.value.status_code == 409
    with pytest.raises(HTTPException) as episode_refresh:
        request_episode_metadata_refresh(session, "VsUtykQi2uE")
    assert episode_refresh.value.status_code == 409


def test_the_background_migration_restores_listed_episodes_marked_unusable(listed, session):
    from backend.db.models import Episode

    migration = importlib.import_module(
        "backend.db.background_migrations.versions.e7cc98e77a6a_restore_listed_episodes_marked_unusable"
    )
    collection = _collection(session)
    marked = _episode(session, collection, "VsUtykQi2uE", "not-usable.1", status="no_usable_media", metadata_is_final=False)
    marked.set_meta("no_usable_media.previous_identifier", "ep.2021-01-01T00:00:00.000000")
    marked.set_meta("no_usable_media.reason", "not_found")
    marked.set_meta("no_usable_media.since", "2026-11-02T09:11:49+00:00")
    marked.set_meta("ep_status.was_published", "1")
    collection.set_meta("ep_id.latest_not_usable_num", "1")
    session.commit()

    assert migration._restore(session) == 1
    session.commit()

    episode = session.get(Episode, marked.id)
    assert episode.publish_status == "published_final"
    assert episode.episode_identifier == "ep.2021-01-01T00:00:00.000000"
    assert episode.metadata_is_final is True
    assert {item.key for item in episode.meta_items} == {"ep_status.was_published"}
    assert collection.get_meta("ep_id.latest_not_usable_num") is None


def test_the_background_migration_leaves_daily_wire_episodes_alone(session):
    from backend.db.models import Episode

    migration = importlib.import_module(
        "backend.db.background_migrations.versions.e7cc98e77a6a_restore_listed_episodes_marked_unusable"
    )
    collection = _collection(session, source_key="dailywire")
    marked = _episode(session, collection, "gone", "not-usable.1", status="no_usable_media", metadata_is_final=False)
    marked.set_meta("no_usable_media.previous_identifier", "ep.2021-01-01T00:00:00.000000")
    session.commit()

    assert migration._restore(session) == 0
    assert session.get(Episode, marked.id).episode_identifier == "not-usable.1"
