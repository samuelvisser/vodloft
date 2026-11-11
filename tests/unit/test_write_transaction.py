from __future__ import annotations

import sqlite3
import threading
import time

import pytest
from sqlalchemy import select, text
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


@pytest.fixture
def wal_database(task_database):
    from backend.db import core

    with core.get_engine().connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    return task_database


def _hold_the_writer(core, *, wrote: threading.Event, release: threading.Event, priority="background"):
    from backend.db.models import Settings

    def work(session):
        session.scalar(select(Settings)).onboarding_completed = False
        session.flush()
        wrote.set()
        release.wait(5)

    def run():
        with core.write_priority(priority):
            core.run_write_transaction(work)

    thread = threading.Thread(target=run)
    thread.start()
    assert wrote.wait(5)
    return thread


# On SQLite a concurrent transaction still waits for its turn to write.
@pytest.mark.parametrize("concurrent", [False, True])
def test_a_write_transaction_reads_while_another_one_writes(wal_database, concurrent):
    from backend.db import core
    from backend.db.models import Settings

    wrote, release = threading.Event(), threading.Event()
    holder = _hold_the_writer(core, wrote=wrote, release=release)
    read = threading.Event()
    seen = []

    def work(session):
        settings = session.scalar(select(Settings))
        seen.append(settings.onboarding_completed)
        read.set()
        settings.onboarding_completed = not settings.onboarding_completed

    reader = threading.Thread(target=lambda: core.run_write_transaction(work, concurrent=concurrent))
    reader.start()
    # The read ran while the writer was taken; only the write waits for its turn.
    assert read.wait(5)
    assert reader.is_alive()
    release.set()
    holder.join(5)
    reader.join(5)

    # It read before the other commit, so it ran again on what that one wrote.
    assert seen == [True, False]
    with wal_database() as session:
        assert session.scalar(select(Settings)).onboarding_completed is True


def test_an_interactive_write_goes_before_waiting_background_writes(wal_database):
    from backend.db import core

    wrote, release = threading.Event(), threading.Event()
    holder = _hold_the_writer(core, wrote=wrote, release=release)
    order = []

    def writer(name, priority):
        def work(session):
            session.execute(text("UPDATE settings SET ytdlp_options = :name"), {"name": name})
            order.append(name)

        with core.write_priority(priority):
            core.run_write_transaction(work)

    waiting = []
    for name, priority in (("sync-1", "background"), ("sync-2", "background"), ("save", "interactive")):
        thread = threading.Thread(target=writer, args=(name, priority))
        thread.start()
        waiting.append(thread)
        deadline = time.monotonic() + 5
        while len(core._write_turns.waiters) < len(waiting) and time.monotonic() < deadline:
            time.sleep(0.01)
    assert len(core._write_turns.waiters) == 3

    release.set()
    for thread in (holder, *waiting):
        thread.join(5)
    assert order == ["save", "sync-1", "sync-2"]


def test_a_background_write_that_waited_long_is_not_passed_again(monkeypatch):
    from backend.db import core

    monkeypatch.setattr(core, "_WRITE_TURN_AGING_SECONDS", 0)
    turns = core._WriteTurns()
    turns.waiters = {
        0: core._Waiter(0, "background", time.monotonic() - 1),
        1: core._Waiter(1, "interactive", time.monotonic()),
    }
    assert turns._first(time.monotonic()) == 0


def test_a_transaction_that_only_reads_never_takes_a_turn(wal_database):
    from backend.db import core
    from backend.db.models import Settings

    wrote, release = threading.Event(), threading.Event()
    holder = _hold_the_writer(core, wrote=wrote, release=release)
    try:
        started = time.monotonic()
        assert core.run_write_transaction(lambda session: session.scalar(select(Settings.id))) is not None
        assert time.monotonic() - started < 1
    finally:
        release.set()
        holder.join(5)
