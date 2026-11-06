from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError


def _locked() -> OperationalError:
    return OperationalError("UPDATE task_runs", {}, sqlite3.OperationalError("database is locked"))


def test_a_locked_database_runs_the_whole_write_again(task_database, monkeypatch):
    from backend.db import core
    from backend.db.models import Settings

    monkeypatch.setattr(core, "_WRITE_RETRY_DELAY_SECONDS", 0)
    attempts = []

    def work(session):
        attempts.append(1)
        session.scalar(select(Settings)).onboarding_completed = False
        if len(attempts) == 1:
            raise _locked()
        return "written"

    assert core.run_write_transaction(work) == "written"
    assert len(attempts) == 2
    with task_database() as session:
        assert session.scalar(select(Settings)).onboarding_completed is False


def test_a_lock_that_stays_is_raised_after_the_last_attempt(task_database, monkeypatch):
    from backend.db import core

    monkeypatch.setattr(core, "_WRITE_RETRY_DELAY_SECONDS", 0)
    attempts = []

    def work(_session):
        attempts.append(1)
        raise _locked()

    with pytest.raises(OperationalError):
        core.run_write_transaction(work, attempts=3)
    assert len(attempts) == 3


def test_other_database_errors_are_not_tried_again(task_database):
    from backend.db import core

    attempts = []

    def work(_session):
        attempts.append(1)
        raise OperationalError("SELECT", {}, sqlite3.OperationalError("no such table: missing"))

    with pytest.raises(OperationalError):
        core.run_write_transaction(work)
    assert len(attempts) == 1


def test_reading_operations_writes_nothing(task_database):
    from task_manager.scheduler.db import TaskOperation
    from task_manager.scheduler.operations import create_operation, get_operation, list_operations

    with task_database() as session:
        operation = create_operation(
            session, kind="example", resource_type="system", resource_id=None, title="Example", targets=[],
        )
        operation_id = operation.id
        session.commit()
        stored = session.get(TaskOperation, operation_id)
        # Canceled, but not yet stored as such: a read shows it canceled.
        stored.status = "RUNNING"
        stored.context = {"cancel_requested": True}
        session.commit()

    assert get_operation(operation_id).status == "CANCELED"
    assert [snapshot.status for snapshot in list_operations(relevant=True)] == ["CANCELED"]

    with task_database() as session:
        assert session.get(TaskOperation, operation_id).status == "RUNNING"
