from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.pool import QueuePool

from conftest import POSTGRESQL_TEST_URL


def _configure(monkeypatch, url: str, database_path=None):
    from backend.db import core

    settings = SimpleNamespace(database_path=database_path, resolved_database_url=url)
    monkeypatch.setattr(core, "get_settings", lambda: settings)
    for name in ("_engine", "_SessionLocal", "_database_url", "_db_path"):
        monkeypatch.setattr(core, name, None)
    core.configure_db()
    return core.get_engine()


def test_sqlite_connections_are_kept_open_and_never_waited_for(tmp_path, monkeypatch):
    database_path = tmp_path / "vodloft.db"
    engine = _configure(monkeypatch, f"sqlite:///{database_path.as_posix()}", database_path)
    try:
        assert isinstance(engine.pool, QueuePool)
        # More connections than the pool keeps are opened at once, not waited for.
        connections = [engine.connect() for _ in range(engine.pool.size() + 5)]
        for connection in connections:
            connection.close()
        # The next Session gets one that is already open, with its settings still applied.
        assert engine.pool.checkedin() == engine.pool.size()
        with engine.connect() as connection:
            assert engine.pool.checkedin() == engine.pool.size() - 1
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        engine.dispose()


def test_a_database_server_gets_a_pool_that_outgrows_the_scheduler_workers(monkeypatch):
    # Creating the engine does not connect, so no server is needed.
    engine = _configure(monkeypatch, "postgresql+psycopg://vodloft:secret@db.invalid/vodloft")
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() + engine.pool._max_overflow >= 60
        assert engine.pool._pre_ping
    finally:
        engine.dispose()


def test_the_database_label_hides_the_password(monkeypatch):
    from backend.db import core

    _configure(monkeypatch, "postgresql+psycopg://vodloft:secret@db.invalid/vodloft")
    try:
        assert core.get_database_label() == "postgresql+psycopg://vodloft:***@db.invalid/vodloft"
        assert core.get_sqlite_database_path() is None
    finally:
        core.get_engine().dispose()


@pytest.mark.skipif(not POSTGRESQL_TEST_URL, reason="Needs VL_TEST_POSTGRESQL_URL")
def test_postgresql_compiles_no_queries_on_the_fly(monkeypatch):
    """PostgreSQL's JIT compiler took seconds to compile the Downloads page's query, which then ran
    in a few hundred milliseconds. Options the database URL sets are kept."""
    url = make_url(POSTGRESQL_TEST_URL).update_query_dict({"options": "-c work_mem=7MB"})
    engine = _configure(monkeypatch, url.render_as_string(hide_password=False))
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SHOW jit").scalar() == "off"
            assert connection.exec_driver_sql("SHOW work_mem").scalar() == "7MB"
    finally:
        engine.dispose()
