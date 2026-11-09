from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config.settings.site_settings import DEFAULT_SPONSORBLOCK_SEGMENTS

# What every Download Profile request names; the UI starts them from the Site's settings.
PROFILE_CHOICES = dict(
    auto_subtitles="fallback", sponsorblock_enabled=False, sponsorblock_segments=dict(DEFAULT_SPONSORBLOCK_SEGMENTS),
    upgrade_check=False, upgrade_after_days=7, upgrade_repeat="once", upgrade_improvements=[], upgrade_length_minutes=5,
)



def _make_collection(session: Session, *, slug: str, collection_type: str):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier

    collection = Collection(
        source_key="dailywire",
        uuid=f"{slug}-uuid",
        slug=slug,
        title="Test Show",
        description=None,
        sharing_url=f"https://example.test/{slug}",
        membership_level="FREE",
        type=collection_type,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host",
        author_slug="host",
    )
    session.add(collection)
    session.flush()
    return collection


def _make_local_media_profile(session: Session, *, slug: str):
    from backend.db.models import LocalMediaProfile

    profile = LocalMediaProfile(
        slug=slug,
        name=slug,
        output_template="/downloads/{collection}/{episode}.ext",
        preferred_format="format_audio_only",
    )
    session.add(profile)
    session.flush()
    return profile


@pytest.fixture
def db_session():
    from backend.db import Base
    from backend.db.core import load_database_models

    load_database_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _capture_event(event_name: str) -> list[dict]:
    from task_manager.events.registry import VodloftEventLinker

    observed: list[dict] = []
    VodloftEventLinker.subscribe(
        event_name,
        event_callback=lambda **event_data: observed.append(event_data),
    )
    return observed


def test_podcast_profile_create_and_update_fire_transactional_events(db_session):
    from backend.api.endpoints.download_profiles.service import (
        create_download_profile,
        update_download_profile,
    )
    from backend.api.models.download_profile import (
        DownloadProfileAPICreate,
        DownloadProfileAPIUpdate,
    )
    from backend.types.collection_types import CollectionType
    from task_manager.events.registry import VodloftEventLinker, wait_for_events
    from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

    collection = _make_collection(db_session, slug="podcast", collection_type=CollectionType.PODCAST.value)
    media_profile = _make_local_media_profile(db_session, slug="podcast-audio")

    added = _capture_event("download_profile.added")
    requested = _capture_event(DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT)
    created = create_download_profile(
        db_session,
        DownloadProfileAPICreate(
            collection_id=collection.id,
            local_media_profile_id=media_profile.id,
            enable_profile=True,
            download_with_countdown=False,
            redownload_final=False,
            delete_older_episodes=False,
            **PROFILE_CHOICES,
        ),
    )

    assert added == []
    db_session.commit()
    wait_for_events()
    assert added == [{
        "resource_id": created.id,
        "id": created.id,
        "collection_id": collection.id,
    }]
    assert requested == [{
        "resource_type": "download_profile",
        "resource_id": created.id,
    }]

    VodloftEventLinker.remove_all()
    updated = _capture_event("download_profile.updated")
    requested = _capture_event(DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT)
    result = update_download_profile(
        db_session,
        created.id,
        DownloadProfileAPIUpdate(
            local_media_profile_id=media_profile.id,
            enable_profile=True,
            download_with_countdown=True,
            redownload_final=False,
            delete_older_episodes=False,
            **PROFILE_CHOICES,
        ),
    )

    assert updated == []
    db_session.commit()
    wait_for_events()
    assert result.id == created.id
    assert updated == [{
        "resource_id": created.id,
        "id": created.id,
        "collection_id": collection.id,
    }]
    assert requested == [{
        "resource_type": "download_profile",
        "resource_id": created.id,
    }]


def test_series_profile_create_and_update_fire_transactional_events(db_session):
    from backend.api.endpoints.download_profiles.service import (
        create_download_profile,
        update_download_profile,
    )
    from backend.api.models.season import SeasonAPIRequestDetached
    from backend.api.models.download_profile import (
        DownloadProfileAPICreate,
        DownloadProfileAPIUpdate,
    )
    from backend.db.models import Season
    from backend.types.collection_types import CollectionType
    from task_manager.events.registry import VodloftEventLinker, wait_for_events
    from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

    collection = _make_collection(db_session, slug="series", collection_type=CollectionType.SERIES.value)
    media_profile = _make_local_media_profile(db_session, slug="series-video")
    season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
    db_session.add(season)
    db_session.flush()
    season_input = SeasonAPIRequestDetached(name=season.name, slug=season.slug)

    added = _capture_event("download_profile.added")
    requested = _capture_event(DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT)
    created = create_download_profile(
        db_session,
        DownloadProfileAPICreate(
            collection_id=collection.id,
            local_media_profile_id=media_profile.id,
            enable_profile=True,
            download_with_countdown=False,
            redownload_final=False,
            delete_older_episodes=False,
            **PROFILE_CHOICES,
        ),
    )

    assert added == []
    db_session.commit()
    wait_for_events()
    assert added == [{
        "resource_id": created.id,
        "id": created.id,
        "collection_id": collection.id,
    }]
    assert requested == [{
        "resource_type": "download_profile",
        "resource_id": created.id,
    }]

    VodloftEventLinker.remove_all()
    updated = _capture_event("download_profile.updated")
    requested = _capture_event(DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT)
    result = update_download_profile(
        db_session,
        created.id,
        DownloadProfileAPIUpdate(
            local_media_profile_id=media_profile.id,
            enable_profile=True,
            download_with_countdown=False,
            redownload_final=False,
            delete_older_episodes=False,
            **PROFILE_CHOICES,
        ),
    )

    assert updated == []
    db_session.commit()
    wait_for_events()
    assert result.id == created.id
    assert updated == [{
        "resource_id": created.id,
        "id": created.id,
        "collection_id": collection.id,
    }]
    assert requested == [{
        "resource_type": "download_profile",
        "resource_id": created.id,
    }]


def test_download_profile_events_are_discarded_on_rollback(db_session):
    from backend.api.endpoints.download_profiles.service import create_download_profile
    from backend.api.models.download_profile import DownloadProfileAPICreate
    from backend.types.collection_types import CollectionType
    from task_manager.events.registry import wait_for_events
    from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

    collection = _make_collection(db_session, slug="rolled-back", collection_type=CollectionType.PODCAST.value)
    media_profile = _make_local_media_profile(db_session, slug="rolled-back-audio")
    added = _capture_event("download_profile.added")
    requested = _capture_event(DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT)

    create_download_profile(
        db_session,
        DownloadProfileAPICreate(
            collection_id=collection.id,
            local_media_profile_id=media_profile.id,
            enable_profile=True,
            download_with_countdown=False,
            redownload_final=False,
            delete_older_episodes=False,
            **PROFILE_CHOICES,
        ),
    )
    db_session.rollback()
    wait_for_events()

    assert added == []
    assert requested == []


def test_download_profile_worker_subscribes_only_to_dedicated_run_event():
    from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT
    from task_manager.tasks.workers.download_profile_worker import download_profile_worker

    event_names = {
        trigger.event_name
        for trigger in download_profile_worker._task_meta.triggers
        if trigger.trigger_type == "event"
    }

    assert DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT in event_names
    assert "collection.indexed" not in event_names
    assert "download_profile.added" not in event_names
    assert "download_profile.updated" not in event_names
    assert "episode.published_final" not in event_names
    assert "episode.published_preliminary" not in event_names


@pytest.mark.parametrize(
    ("resource_type", "resource_id"),
    (
        ("download_profile", 91),
        ("collection", 12),
        ("episode", 501),
    ),
)
def test_download_profile_run_event_dispatches_exact_scope_to_worker(
        monkeypatch,
        resource_type,
        resource_id,
):
    import task_manager.scheduler.executor as executor_module
    import task_manager.scheduler.registry as registry_module
    import task_manager.scheduler.scheduler as scheduler_module
    from config import get_settings
    from controller.app import setup_triggers_from_registry
    from task_manager.events.emitters import emit_event
    from task_manager.events.registry import wait_for_events
    from task_manager.tasks.workers.download_profile_worker.event_adapter import DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT

    download_profile_task = registry_module.get_task("download_profile_worker")
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        {"download_profile_worker": download_profile_task},
    )
    monkeypatch.setattr(get_settings().scheduler, "enabled", True)

    trigger_now = Mock()
    monkeypatch.setattr(executor_module, "trigger_now", trigger_now)

    class FakeScheduler:
        def __init__(self) -> None:
            self.jobs: dict[str, SimpleNamespace] = {}

        def add_job(self, function, **kwargs):
            job_id = kwargs.get("id", f"job-{len(self.jobs) + 1}")
            job_data = dict(kwargs)
            job_data["id"] = job_id
            job_data["function"] = function
            job = SimpleNamespace(**job_data)
            self.jobs[job_id] = job
            return job

    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler_module, "start_scheduler", lambda: fake_scheduler)

    setup_triggers_from_registry()
    emit_event(DOWNLOAD_PROFILE_RUN_REQUESTED_EVENT, {
        "resource_type": resource_type,
        "resource_id": resource_id,
    })
    wait_for_events()

    trigger_now.assert_called_once_with(
        def_key="download_profile_worker",
        resource_type=resource_type,
        resource_id=resource_id,
    )


def test_a_saved_profile_with_nothing_that_counts_as_better_has_the_check_off():
    from backend.api.models.download_profile import DownloadProfileAPIUpdate

    body = {**PROFILE_CHOICES, "enable_profile": True, "download_with_countdown": False, "redownload_final": False,
            "delete_older_episodes": False, "local_media_profile_id": 1}
    assert DownloadProfileAPIUpdate.model_validate({**body, "upgrade_check": True}).upgrade_check is False
    kept = DownloadProfileAPIUpdate.model_validate({**body, "upgrade_check": True, "upgrade_improvements": ["length"]})
    assert kept.upgrade_check is True



def test_a_saved_profile_that_keeps_every_sponsorblock_type_has_sponsorblock_off():
    from backend.api.models.download_profile import DownloadProfileAPIUpdate

    body = {**PROFILE_CHOICES, "enable_profile": True, "download_with_countdown": False, "redownload_final": False,
            "delete_older_episodes": False, "local_media_profile_id": 1, "sponsorblock_enabled": True}
    kept = {category: "keep" for category in DEFAULT_SPONSORBLOCK_SEGMENTS}
    assert DownloadProfileAPIUpdate.model_validate({**body, "sponsorblock_segments": kept}).sponsorblock_enabled is False
    assert DownloadProfileAPIUpdate.model_validate(body).sponsorblock_enabled is True
    with pytest.raises(ValueError):
        DownloadProfileAPIUpdate.model_validate({**body, "sponsorblock_segments": {**kept, "chapter": "cut"}})
