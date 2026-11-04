"""YouTube premieres that were added as livestreams become videos again."""
from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import MAIN_TAG, Feature, registry

from test_ytdlp_collections import ListedSource, _video

MIGRATION = "backend.db.background_migrations.versions.c65c0a26c4e2_premieres_are_videos"


class _Context:
    def raise_if_canceled(self):
        return None

    def update_progress(self, current, total, message=None):
        return None


class CheckingSource(ListedSource):
    """Lists the videos as the YouTube API did, and looks them up as yt-dlp does now."""

    id = "checking"
    features = ListedSource.features | {Feature.QUICK_CHECK}

    def __init__(self):
        super().__init__()
        self.now: dict[str, str] = {}
        self.looked_up: list[str] = []

    def item_details(self, items):
        self.looked_up += [item.slug for item in items]
        return {item.slug: replace(_video(item.slug, 2025), tag=self.now.get(item.slug, "livestream")) for item in items}


@pytest.fixture
def factory():
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(CheckingSource())


@pytest.fixture
def renamed(monkeypatch):
    from task_manager.tasks.helpers.episodes import events

    changed: list[tuple[str, str]] = []
    monkeypatch.setattr(events, "queue_episode_identifier_changed_event", lambda _s, *, episode, old_episode_identifier: (
        changed.append((old_episode_identifier, episode.episode_identifier))
    ))
    return changed


def _add(factory, scheme: str):
    from backend.db.models import Collection
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    with factory() as session:
        collection = Collection(
            uuid=f"uuid-{scheme}", slug=scheme, source_key="checking", title=scheme,
            sharing_url=f"https://listed.example/{scheme}", membership_level="FREE", type="podcast",
            episode_identifier=scheme, author_name="A", author_slug="a",
        )
        session.add(collection)
        session.commit()
        # Episode 1 and 4 were premieres the API listing called livestreams; "stream" really was one.
        add_listed_episodes(session, collection_id=collection.id, found=[
            replace(_video("e1", 2025, 1), tag="livestream"),
            _video("e2", 2025, 2),
            _video("e3", 2025, 3),
            replace(_video("e4", 2025, 4), tag="livestream"),
            _video("e5", 2025, 5),
            replace(_video("stream", 2025, 6), tag="livestream"),
        ])
        session.commit()
        return collection.id


def _identifiers(factory, collection_id):
    from backend.db.models import Episode

    with factory() as session:
        return dict(session.execute(
            select(Episode.source_slug, Episode.episode_identifier).where(Episode.collection_id == collection_id)
        ).all())


def _migrate(factory, monkeypatch):
    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    asyncio.run(module.migrate(_Context()))


def test_premieres_take_their_place_in_upload_order(factory, source, renamed, monkeypatch):
    collection_id = _add(factory, "seasonal")
    assert _identifiers(factory, collection_id) == {
        "e1": "livestream.1", "e2": "ep.S2025E01", "e3": "ep.S2025E02", "e4": "livestream.2", "e5": "ep.S2025E03",
        "stream": "livestream.3",
    }
    source.now = {"e1": MAIN_TAG, "e4": MAIN_TAG}

    _migrate(factory, monkeypatch)

    assert sorted(source.looked_up) == ["e1", "e4", "stream"]
    assert _identifiers(factory, collection_id) == {
        "e1": "ep.S2025E01", "e2": "ep.S2025E02", "e3": "ep.S2025E03", "e4": "ep.S2025E04", "e5": "ep.S2025E05",
        "stream": "livestream.3",
    }
    # Downloaded files follow every identifier that changed.
    assert sorted(renamed) == [
        ("ep.S2025E01", "ep.S2025E02"), ("ep.S2025E02", "ep.S2025E03"), ("ep.S2025E03", "ep.S2025E05"),
        ("livestream.1", "ep.S2025E01"), ("livestream.2", "ep.S2025E04"),
    ]


def test_a_date_based_premiere_only_changes_itself(factory, source, renamed, monkeypatch):
    collection_id = _add(factory, "date_based")
    before = _identifiers(factory, collection_id)
    source.now = {"e4": MAIN_TAG}

    _migrate(factory, monkeypatch)

    after = _identifiers(factory, collection_id)
    assert after["e4"] == "ep.2025-04-01T00:00:00.000000"
    assert {slug: identifier for slug, identifier in after.items() if slug != "e4"} == {
        slug: identifier for slug, identifier in before.items() if slug != "e4"
    }
    assert renamed == [("livestream.2", "ep.2025-04-01T00:00:00.000000")]


def test_nothing_changes_when_every_livestream_really_was_one(factory, source, renamed, monkeypatch):
    collection_id = _add(factory, "numbered")
    before = _identifiers(factory, collection_id)

    _migrate(factory, monkeypatch)

    assert _identifiers(factory, collection_id) == before
    assert renamed == []
