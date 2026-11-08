"""Media a Source keeps for members or subscribers: locked without an error, and checked again later."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def _media():
    from backend.db.models import Video

    return Video(source_key="dailywire", access_checks=0)


def test_refused_media_is_checked_after_a_day_three_days_a_week_then_weekly_for_five_weeks():
    from backend.services.media_access import lock_refused, media_locked, record_check

    media = _media()
    lock_refused(media, "INSIDER", now=NOW)
    assert media_locked(media)
    checks = [media.access_check_at]
    while media.access_check_at is not None:
        record_check(media, "INSIDER", now=media.access_check_at)
        checks.append(media.access_check_at)
    assert [(check - NOW).days for check in checks[:-1]] == [1, 3, 7, 14, 21, 28, 35]
    assert media_locked(media)


def test_a_check_that_finds_the_media_open_for_everyone_unlocks_it():
    from backend.services.media_access import lock_refused, media_locked, record_check

    media = _media()
    lock_refused(media, "members", now=NOW)
    record_check(media, None, now=NOW)
    assert (media.access, media.access_refused_at, media.access_check_at, media.access_checks) == (None, None, None, 0)
    assert not media_locked(media)


@pytest.fixture
def locked_download(task_database, monkeypatch):
    from backend.db import Base
    from backend.services.media_access import lock_refused
    from task_manager.scheduler.db import TaskDefinition
    from test_media_download_operations import _make_download

    with task_database() as session:
        Base.metadata.create_all(session.bind)
        session.add(TaskDefinition(key="download_episode", title="Download", allowed_resource_types=["media_download"]))
        download = _make_download(session)
        lock_refused(download.media, "INSIDER", now=NOW - timedelta(days=2))
        session.commit()
        ids = download.id, download.media_item_id

    from task_manager.tasks.workers.check_locked_media import service
    monkeypatch.setattr(service, "dispatch_queued_media_download_operations", lambda _s: None)
    return task_database, ids


def _answer(monkeypatch, access):
    from task_manager.tasks.workers.check_locked_media import service

    asked = []

    def current_access(*, slug, url):
        asked.append(slug)
        return access
    monkeypatch.setattr(service, "get_source", lambda _key: SimpleNamespace(current_access=current_access))
    return asked


def _state(factory, ids):
    from backend.db.models.media_item import MediaItemBase
    from backend.services.media_access import media_locked
    from task_manager.tasks.media_download_operations import get_active_media_download_operation

    download_id, media_id = ids
    with factory() as session:
        media = session.get(MediaItemBase, media_id)
        return media_locked(media), media.access_checks, get_active_media_download_operation(session, download_id) is not None


def test_a_due_check_downloads_media_that_opened_up(locked_download, monkeypatch):
    from task_manager.tasks.workers.check_locked_media.service import run_access_checks

    factory, ids = locked_download
    asked = _answer(monkeypatch, None)
    with factory() as session:
        result = run_access_checks(session, now=NOW)
    assert asked and result.data == {"checked": 1, "opened": 1}
    assert _state(factory, ids) == (False, 0, True)


def test_a_due_check_leaves_media_that_still_needs_the_access_locked(locked_download, monkeypatch):
    from task_manager.tasks.workers.check_locked_media.service import run_access_checks

    factory, ids = locked_download
    _answer(monkeypatch, "INSIDER")
    with factory() as session:
        run_access_checks(session, now=NOW)
    assert _state(factory, ids) == (True, 1, False)


def test_checking_again_by_hand_tries_one_more_download(locked_download, monkeypatch):
    from backend.db.core import run_write_transaction
    from backend.db.models.media_item import MediaItemBase
    from backend.services.access_checks import ask_for_check
    from task_manager.tasks.workers.check_locked_media.service import run_access_checks

    factory, ids = locked_download
    monkeypatch.setattr("backend.services.access_checks.queue_task_after_commit", lambda *_a, **_k: None)
    run_write_transaction(lambda s: ask_for_check(s, [s.get(MediaItemBase, ids[1])], now=NOW))
    # The site still keeps it for members, but the user may have gained access: the download finds out.
    _answer(monkeypatch, "INSIDER")
    with factory() as session:
        run_access_checks(session, now=NOW)
    assert _state(factory, ids) == (False, 0, True)


def test_yt_dlp_locks_members_only_and_premium_videos_of_any_site():
    from sources.ytdlp.source import YtDlpSource, _access

    assert _access({"availability": "subscriber_only"}) == "members"
    assert _access({"availability": "premium_only"}) == "premium"
    assert _access({"availability": "needs_auth"}) is None
    assert _access({}) is None
    assert YtDlpSource().refused_access("ERROR: Join this channel to get access to members-only content") == "members"
    assert YtDlpSource().refused_access("HTTP Error 500") is None


def test_each_site_names_the_access_its_videos_need():
    from backend.services.media_access import link_access, site_access

    assert site_access("ytdlp", "youtube", "premium").label == "YouTube Premium"
    assert site_access("ytdlp", "twitch", "members").label == "Subscribers only"
    assert site_access("ytdlp", "vimeo", "members").label == "Members only"
    assert site_access("ytdlp", "generic:example.com", "premium").label == "Premium only"
    assert site_access("dailywire", "dailywire", "ALL_ACCESS").label == "All Access"
    assert site_access("npo", "npo", "npo_plus").label == "NPO Plus"
    assert site_access("ytdlp", None, "members") is None
    assert link_access("ytdlp", "https://www.twitch.tv/videos/123", "members").label == "Subscribers only"
