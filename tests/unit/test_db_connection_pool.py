from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.pool import NullPool, QueuePool


def _configure(monkeypatch, url: str, database_path=None):
    from backend.db import core

    settings = SimpleNamespace(database_path=database_path, resolved_database_url=url)
    monkeypatch.setattr(core, "get_settings", lambda: settings)
    for name in ("_engine", "_SessionLocal", "_database_url", "_db_path"):
        monkeypatch.setattr(core, name, None)
    core.configure_db()
    return core.get_engine()


def test_configure_db_does_not_bound_sqlite_connections(tmp_path, monkeypatch):
    database_path = tmp_path / "vodloft.db"
    engine = _configure(monkeypatch, f"sqlite:///{database_path.as_posix()}", database_path)
    try:
        assert isinstance(engine.pool, NullPool)
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
