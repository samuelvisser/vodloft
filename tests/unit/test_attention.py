"""Needs attention: states that open once, tell once, refresh quietly and resolve themselves."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from test_notifications import NOW, _device, db  # noqa: F401


def _states(session, *, open_only=True):
    from backend.db.models import AttentionState

    query = select(AttentionState).order_by(AttentionState.id)
    if open_only:
        query = query.where(AttentionState.resolved_at.is_(None))
    return list(session.scalars(query))


def _told(session, kind):
    from backend.db.models import NotificationEvent

    return list(session.scalars(select(NotificationEvent).where(NotificationEvent.event == kind.value)))


def _access(levels):
    from backend.security.access import Access

    return Access.for_user(
        user_id=7, username="viewer", levels=levels, source_limits=None, members_only=False, delete_files=False,
        must_change_password=False, template_key=None, session_version=0,
    )


def test_an_almost_full_disk_is_one_problem_until_there_is_room_again(db, monkeypatch):
    from config import get_settings
    from backend.services.notifications.checks import disk_check
    from backend.types.happenings import Happening

    monkeypatch.setattr(get_settings().health, "min_free_disk_mb", 1024)
    assert disk_check(db, SimpleNamespace(free_bytes=100 * 1024 ** 2))
    assert disk_check(db, SimpleNamespace(free_bytes=50 * 1024 ** 2))
    (state,) = _states(db)
    assert (state.kind, state.severity, state.title) == ("disk_almost_full", "problem", "The disk is almost full")
    assert "0.0 GB" in state.body
    assert [event.severity for event in _told(db, Happening.DISK_ALMOST_FULL)] == ["problem"]

    assert disk_check(db, SimpleNamespace(free_bytes=2048 * 1024 ** 2))
    assert _states(db) == []
    # Once it has room, there is nothing left to write.
    assert not disk_check(db, SimpleNamespace(free_bytes=2048 * 1024 ** 2))

    disk_check(db, SimpleNamespace(free_bytes=0))
    assert len(_states(db)) == 1 and len(_states(db, open_only=False)) == 2
    assert len(_told(db, Happening.DISK_ALMOST_FULL)) == 2


def test_a_failing_task_stays_a_problem_until_a_run_succeeds(db):
    from task_manager.scheduler.db import TaskDefinition, TaskRun
    from task_manager.scheduler.types import ResourceType, TaskStatus
    from backend.services.notifications.checks import failing_tasks
    from backend.types.happenings import Happening

    definition = TaskDefinition(key="collection_health", title="Collection health")
    db.add(definition)
    db.flush()

    def run(status, minutes):
        at = NOW + timedelta(minutes=minutes)
        db.add(TaskRun(
            definition=definition, resource_type=ResourceType("system"), status=TaskStatus(status),
            started_at=at, finished_at=at, created_at=at, last_error="It broke",
        ))
        db.flush()

    for minute in range(2):
        run("FAILED", minute)
    failing_tasks(db, NOW + timedelta(minutes=5))
    assert _states(db) == []

    run("FAILED", 2)
    failing_tasks(db, NOW + timedelta(minutes=5))
    (state,) = _states(db)
    assert (state.subject_key, state.title, state.url) == ("task:collection_health", "Collection health keeps failing", "/tasks")
    # Long after its last failed run, it still fails: nothing ran fine since.
    failing_tasks(db, NOW + timedelta(days=3))
    assert len(_states(db)) == 1 and len(_told(db, Happening.TASK_FAILING)) == 1

    run("SUCCEEDED", 10)
    failing_tasks(db, NOW + timedelta(minutes=15))
    assert _states(db) == []


def test_home_shows_a_state_only_to_whoever_may_see_it(db):
    from backend.security.access import Access, Area, Level
    from backend.services.attention import open_state, open_states
    from backend.types.happenings import Happening

    open_state(db, Happening.DISK_ALMOST_FULL, "disk", title="The disk is almost full", now=NOW)
    open_state(db, Happening.TASK_FAILING, "task:x", title="X keeps failing", now=NOW + timedelta(minutes=1))

    assert [state.kind for state in open_states(db, Access.full())] == ["task_failing", "disk_almost_full"]
    tasks_only = _access({Area.TASKS: Level.VIEW})
    assert [state.kind for state in open_states(db, tasks_only)] == ["task_failing"]
    assert open_states(db, _access({Area.LIBRARY: Level.VIEW})) == []


def test_an_open_state_tells_the_default_rule_once(db):
    from backend.db.models import NotificationDelivery
    from backend.services.attention import open_state, resolve_state
    from backend.services.notifications.rules import restore_default_rules
    from backend.types.happenings import Happening

    restore_default_rules(db)
    _device(db)
    for _ in range(3):
        open_state(db, Happening.DESTINATION_FAILING, "destination:1", title="Plex keeps failing", now=NOW)
    assert len(list(db.scalars(select(NotificationDelivery)))) == 1
    assert resolve_state(db, Happening.DESTINATION_FAILING, "destination:1")
    assert not resolve_state(db, Happening.DESTINATION_FAILING, "destination:1")
