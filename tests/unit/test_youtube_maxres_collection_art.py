"""Existing yt-dlp Collections move to YouTube's 16:9 maxresdefault still."""
from __future__ import annotations

import asyncio
import importlib

import pytest
from conftest import use_database
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

MIGRATION = "backend.db.background_migrations.versions.9b3e5d7a1c62_youtube_maxres_collection_art"
HQ = "https://i.ytimg.com/vi/VsUtykQi2uE/hqdefault.jpg?sqp=abc"
MAXRES = "https://i.ytimg.com/vi/VsUtykQi2uE/maxresdefault.jpg"
OLD = "https://i.ytimg.com/vi/FqhihBhJkbQ/hqdefault.jpg"


class _Context:
    def __init__(self):
        self.progress = []

    def raise_if_canceled(self):
        return None

    def update_progress(self, current, total, message=None):
        self.progress.append((current, total))


@pytest.fixture
def migration(monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    factory = sessionmaker(engine)
    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    yield module, factory
    engine.dispose()


def _collection(session, slug, source_key, image):
    from backend.db.models import Collection
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    session.add(Collection(
        source_key=source_key, uuid=f"{slug}-uuid", slug=slug, title=slug, description=None,
        sharing_url=f"https://example.com/{slug}", membership_level="FREE", type=CollectionType.SERIES.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="A", author_slug="a",
        thumbnail_landscape_path=image, background_image_path=image,
    ))


def test_migration_moves_ytdlp_collections_to_maxresdefault_when_youtube_has_it(migration, monkeypatch):
    module, factory = migration
    with factory() as session:
        _collection(session, "eighty-years-war", "ytdlp", HQ)
        _collection(session, "kinderliedjes", "ytdlp", OLD)
        _collection(session, "a-daily-wire-show", "dailywire", HQ)
        session.commit()
    looked_up = []

    def widest_still(url):
        looked_up.append(url)
        return MAXRES if url == HQ else url

    monkeypatch.setattr(module, "widest_still", widest_still)
    context = _Context()
    asyncio.run(module.migrate(context))

    from backend.db.models import Collection
    with factory() as session:
        art = {c.slug: (c.thumbnail_landscape_path, c.background_image_path) for c in session.scalars(select(Collection))}
    assert art == {
        "eighty-years-war": (MAXRES, MAXRES),
        "kinderliedjes": (OLD, OLD),
        "a-daily-wire-show": (HQ, HQ),
    }
    assert looked_up == [HQ, OLD]
    assert context.progress[0] == (0, 2) and context.progress[-1] == (2, 2)


def test_migration_does_nothing_without_ytdlp_collections(migration, monkeypatch):
    module, _factory = migration
    monkeypatch.setattr(module, "widest_still", lambda url: pytest.fail("no lookup expected"))
    context = _Context()
    asyncio.run(module.migrate(context))
    assert context.progress == []
