"""Collections added before VODLoft knew Sites get their Site, one at a time."""
from __future__ import annotations

import asyncio
import importlib

import pytest
from conftest import use_database
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

MIGRATION = "backend.db.background_migrations.versions.7ffa406cf785_place_collections_and_videos_on_sites"


class _Context:
    def update_progress(self, current, total, message=None):
        return None


@pytest.fixture
def factory():
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    yield sessionmaker(engine)
    engine.dispose()


def test_a_stopped_run_keeps_the_collections_it_placed(factory, monkeypatch):
    from backend.db.models import Collection

    migration = importlib.import_module(MIGRATION)
    with factory() as session:
        for slug in ("first-show", "second-show"):
            session.add(Collection(
                uuid=f"uuid-{slug}", slug=slug, source_key="dailywire", title=slug,
                sharing_url=f"https://www.dailywire.com/show/{slug}", membership_level="FREE", type="podcast",
                episode_identifier="date_based", author_name="A", author_slug="a",
            ))
        session.commit()
    monkeypatch.setattr(migration, "get_session", factory)

    real_place = migration.place_collection

    def place_then_stop(session, collection):
        if collection.slug == "second-show":
            raise RuntimeError("VODLoft stopped")
        real_place(session, collection)

    monkeypatch.setattr(migration, "place_collection", place_then_stop)
    with pytest.raises(RuntimeError):
        asyncio.run(migration.migrate(_Context()))

    with factory() as session:
        sites = {collection.slug: collection.site_key for collection in session.query(Collection)}
    assert sites == {"first-show": "dailywire", "second-show": None}

    # The next run only looks up what has no Site yet.
    monkeypatch.setattr(migration, "place_collection", real_place)
    asyncio.run(migration.migrate(_Context()))
    with factory() as session:
        assert {collection.site_key for collection in session.query(Collection)} == {"dailywire"}
