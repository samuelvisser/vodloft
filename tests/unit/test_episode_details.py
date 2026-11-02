"""Every indexed episode has a length and an uploader, for the duration rules of Which episodes."""
from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import Feature, ItemRef, ItemRefresh, VideoDetails, registry
from sources.ytdlp import YtDlpSource

from test_catalogue_refresh import RefreshingSource
from test_youtube_catalogue import lookups, ytdlp_dir  # noqa: F401
from test_ytdlp_collections import ListedSource, _video

MIGRATION = "backend.db.background_migrations.versions.4dac3ac7c70e_episode_details"
CHANNEL = "https://www.youtube.com/channel/UC1/videos"


class _Context:
    def raise_if_cancelled(self):
        return None

    def update_progress(self, current, total, message=None):
        return None


@pytest.fixture
def factory():
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


@pytest.fixture
def sources(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(ListedSource()), registry.register(RefreshingSource())


def _collection(session, slug: str, source_key: str):
    from backend.db.models import Collection

    collection = Collection(
        uuid=f"uuid-{slug}", slug=slug, source_key=source_key, title=slug, sharing_url=f"https://listed.example/{slug}",
        membership_level="FREE", type="podcast", episode_identifier="numbered", author_name="A", author_slug="a",
    )
    session.add(collection)
    session.commit()
    return collection


def _episodes(session, collection_id):
    from backend.db.models import Episode

    return {e.source_slug: e for e in session.scalars(select(Episode).where(Episode.collection_id == collection_id))}


def test_the_flat_listing_carries_the_length_and_uploader(lookups):
    answers, _ = lookups
    answers[("--flat-playlist", "https://vimeo.com/showcase/1")] = {"entries": [
        {"id": "1", "ie_key": "Vimeo", "url": "https://vimeo.com/1", "title": "One", "duration": 61, "uploader": "Me"},
        {"id": "2", "ie_key": "Vimeo", "url": "https://vimeo.com/2", "title": "Two", "duration": 0},
    ]}

    refresh = YtDlpSource().refresh_items(
        "https://vimeo.com/showcase/1", [ItemRef("vimeo-1", "https://vimeo.com/1"), ItemRef("vimeo-2", "https://vimeo.com/2")],
    )

    assert (refresh.details["vimeo-1"].duration, refresh.details["vimeo-1"].author_name) == (61.0, "Me")
    assert refresh.details["vimeo-2"].duration is None


def test_a_refresh_fills_in_a_missing_length_and_never_clears_one(factory, sources):
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes, refresh_listed_collection

    _listed, refreshing = sources
    with factory() as session:
        collection = _collection(session, "c1", "refreshing")
        add_listed_episodes(session, collection_id=collection.id, found=[
            replace(_video("v1", 2024), duration=None), _video("v2", 2024, 2),
        ])
        session.commit()
        refreshing.refresh = ItemRefresh(details={
            "v1": VideoDetails(slug="v1", url="u", title="Video v1", duration=90.0),
            "v2": VideoDetails(slug="v2", url="u", title="Video v2"),
        })

        refresh_listed_collection(session, collection_id=collection.id, source=refreshing)

        episodes = _episodes(session, collection.id)
        assert episodes["v1"].duration == 90.0
        assert episodes["v2"].duration == 60.0


def test_the_background_migration_looks_up_only_episodes_without_details(factory, sources, monkeypatch):
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    listed, _refreshing = sources
    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    with factory() as session:
        collection = _collection(session, "c1", "listed")
        add_listed_episodes(session, collection_id=collection.id, found=[
            replace(_video("v1", 2024), duration=None),
            replace(_video("v2", 2024, 2), author_name=None),
            _video("v3", 2024, 3),
            replace(_video("gone", 2024, 4), duration=None),
        ])
        session.commit()
        _episodes(session, collection.id)["gone"].removed_from_source = True
        session.commit()
        collection_id = collection.id
    listed.videos = [
        replace(_video("v1", 2024), duration=125.0),
        replace(_video("v2", 2024, 2), author_name="Someone"),
        _video("v3", 2024, 3),
        _video("new", 2024, 5),
    ]

    asyncio.run(module.migrate(_Context()))

    # Only the two incomplete episodes still at the Source were asked for.
    assert listed.known_seen == [frozenset({"v3", "gone"})]
    with factory() as session:
        episodes = _episodes(session, collection_id)
        assert episodes["v1"].duration == 125.0
        assert episodes["v2"].author_name == "Someone"
        assert episodes["gone"].duration == 0
        # A video the collection does not have yet is left for the next index.
        assert "new" not in episodes


def test_the_background_migration_skips_sources_that_do_not_list_episodes(factory, sources, monkeypatch):
    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    with factory() as session:
        _collection(session, "show", "dailywire")

    assert module._collections() == []
