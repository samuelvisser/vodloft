"""Daily Wire episodes keep the membership level they are for up to date, also those added before VODLoft kept it."""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

from conftest import use_database
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from test_episode_publication_reconciliation import _episode_detail, _make_collection_and_episode


def _detail(available_for):
    from sources.dailywire.api.utils.validators.available_for_list import parse_tiers

    return _episode_detail(slug="the-ben-shapiro-show-2500", publish_status="PUBLISHED").model_copy(
        update={"available_for": parse_tiers(available_for)},
    )


def test_a_metadata_refresh_gives_an_episode_the_level_it_is_for():
    from backend.db.models import Episode
    from task_manager.tasks.helpers.episodes.metadata import update_episode_from_dailywire

    episode = Episode(access=None, access_checks=0)
    update_episode_from_dailywire(episode, _detail(["INSIDER", "ALL_ACCESS"]))
    assert episode.access == "INSIDER"

    # A record without levels says nothing about them.
    update_episode_from_dailywire(episode, _detail([]))
    assert episode.access == "INSIDER"

    update_episode_from_dailywire(episode, _detail(["FREE", "INSIDER"]))
    assert episode.access is None


class _Context:
    def __init__(self):
        self.progress = []

    def raise_if_canceled(self):
        return None

    def update_progress(self, current, total, message=None):
        self.progress.append((current, total))


def test_older_episodes_get_their_level_from_one_listing_of_each_show(monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from backend.db.models import Episode
    from sources.dailywire.api.dw_api.client import EpisodesPaginatedResult
    from sources.dailywire.api.utils.validators.available_for_list import parse_tiers

    migration = importlib.import_module(
        "backend.db.background_migrations.versions.536d9eeb6f76_daily_wire_episode_access"
    )
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    with Session(engine) as session:
        _, episode = _make_collection_and_episode(session, identifier="ep.2500")
        episode_id, slug = episode.id, episode.slug

    pages = []

    class FakeClient:
        def __init__(self, *, access_token=None):
            pass

        def get_show_page(self, _slug, *, membership_plan=None):
            assert membership_plan == "FREE"
            return SimpleNamespace(seasons=[SimpleNamespace(dw_id="season-1")])

        def get_episodes_paginated(self, _slug, selector):
            pages.append(selector)
            if len(pages) == 1:
                return EpisodesPaginatedResult([SimpleNamespace(slug="other", available_for=[])], "next", True)
            return EpisodesPaginatedResult([SimpleNamespace(slug=slug, available_for=parse_tiers(["INSIDER"]))], None, False)

    monkeypatch.setattr(migration, "MiddlewareClient", FakeClient)
    monkeypatch.setattr(migration, "DeviceAuthClient", lambda: SimpleNamespace(get_token=lambda: None))

    context = _Context()
    asyncio.run(migration.migrate(context))

    with Session(engine) as session:
        assert session.get(Episode, episode_id).access == "INSIDER"
    assert len(pages) == 2 and context.progress[-1] == (1, 1)
    engine.dispose()
