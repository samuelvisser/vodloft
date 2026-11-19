"""A download delay per Site, and the throttle guard: a throttled try waits, pauses its Site and is tried again."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.types.link_season_types import OutsideVideos

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def site_settings():
    from config.registry import get_settings, replace_settings
    from config.settings.site_settings import SiteSettingValues

    original = get_settings()

    def apply(**own: dict):
        replace_settings(original.model_copy(update={
            "site_settings": {key: SiteSettingValues(**values) for key, values in own.items()},
        }))

    yield apply
    replace_settings(original)


@pytest.fixture
def throttled_download(task_database, monkeypatch):
    from backend.db import Base
    from backend.db.models import Site
    from task_manager.scheduler.db import TaskDefinition
    from task_manager.tasks import media_download_operations
    from test_media_download_operations import _make_download

    with task_database() as session:
        Base.metadata.create_all(session.bind)
        session.add(TaskDefinition(key="download_episode", title="Download", allowed_resource_types=["media_download"]))
        session.add(Site(key="youtube", name="YouTube", domains=["youtube.com"]))
        download = _make_download(session)
        download.media.collection.site_key = "youtube"
        session.commit()
        download_id = download.id
    monkeypatch.setattr(media_download_operations, "_schedule_delayed_media_download_dispatch", lambda *_a, **_k: None)
    monkeypatch.setattr(media_download_operations, "queue_task_after_commit", lambda *_a, **_k: None)
    return task_database, download_id


def _throttle(download_id: int, now: datetime = NOW):
    from backend.db.core import run_write_transaction
    from backend.services.throttle_guard import record_throttled

    return run_write_transaction(lambda w: record_throttled(w, download_id, height=360, now=now, metadata={}))


def test_each_site_can_have_a_download_delay_of_its_own_or_none(site_settings):
    from types import SimpleNamespace

    from backend.services.episode_download_delay import episode_download_delay_ready_at
    from backend.types.episode_types import EpisodePublishStatus

    from config import get_settings

    published = NOW - timedelta(minutes=1)

    def episode(site_key):
        return SimpleNamespace(
            collection=SimpleNamespace(site_key=site_key, outside_videos=OutsideVideos.LEAVE_OUT), publish_status=EpisodePublishStatus.PUBLISHED_FINAL,
            published_date=published, safe_published_final=None, recorded_published_final=None,
            went_live_date=None, scheduled_date=None, last_known_pending=None,
        )

    system = get_settings().download_settings.episode_download_delay_minutes
    site_settings(youtube={"download_delay_minutes": 0}, dailywire={"download_delay_minutes": 30})
    assert episode_download_delay_ready_at(episode("youtube")) is None
    assert episode_download_delay_ready_at(episode("dailywire")) == published + timedelta(minutes=30)
    # A Site without a value of its own follows the system setting.
    assert episode_download_delay_ready_at(episode("npo")) == published + timedelta(minutes=system)


def test_a_throttled_try_pauses_its_site_and_the_third_try_keeps_the_file(throttled_download):
    from backend.db.models import Site
    from backend.services.throttle_guard import THROTTLE_PAUSE, refuses_throttled

    factory, download_id = throttled_download
    with factory() as session:
        assert refuses_throttled(session, download_id)
    assert _throttle(download_id) == NOW + THROTTLE_PAUSE
    with factory() as session:
        assert session.get(Site, "youtube").downloads_paused_until == NOW + THROTTLE_PAUSE
        assert refuses_throttled(session, download_id)
    _throttle(download_id)
    with factory() as session:
        # The third try keeps what it gets; the upgrade check finds the better version later.
        assert not refuses_throttled(session, download_id)


def test_a_throttled_download_is_queued_again_and_waits_for_its_site(throttled_download):
    from backend.db.core import run_write_transaction
    from backend.db.models.media_download import MediaDownloadBase
    from task_manager.scheduler.operations import operation_admission_wait_state
    from task_manager.scheduler.types import OperationSource, OperationStatus
    from task_manager.tasks.media_download_operations import (
        MEDIA_DOWNLOAD_SITE_THROTTLED_REASON,
        create_media_download_operation,
        dispatch_queued_media_download_operations,
        get_active_media_download_operation,
        queue_throttled_download_again,
    )

    _factory, download_id = throttled_download
    _throttle(download_id)

    def queue_and_dispatch(w):
        queue_throttled_download_again(w, download_id)
        dispatch_queued_media_download_operations(w)
        operation = get_active_media_download_operation(w, download_id)
        return operation.status, operation_admission_wait_state(operation)

    status, wait = run_write_transaction(queue_and_dispatch)
    assert status == OperationStatus.WAITING.value
    assert wait["reason"] == MEDIA_DOWNLOAD_SITE_THROTTLED_REASON and "YouTube" in wait["message"]

    # A download asked for in the UI starts anyway.
    def manual(w):
        operation = get_active_media_download_operation(w, download_id)
        operation.status = OperationStatus.CANCELED.value
        w.flush()
        create_media_download_operation(w, w.get(MediaDownloadBase, download_id), source=OperationSource.UI.value)
        return dispatch_queued_media_download_operations(w)

    assert run_write_transaction(manual) == 1
