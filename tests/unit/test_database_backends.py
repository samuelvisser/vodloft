"""VODLoft on SQLite and on PostgreSQL.

The PostgreSQL tests run when VL_TEST_POSTGRESQL_URL names an empty database
they may fill, for example
``postgresql+psycopg://postgres@/vodloft_test?host=/var/run/postgresql``.
"""
from __future__ import annotations

import itertools
import os
import threading
import time
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url


POSTGRESQL_TEST_URL = os.environ.get("VL_TEST_POSTGRESQL_URL") or None
needs_postgresql = pytest.mark.skipif(not POSTGRESQL_TEST_URL, reason="Set VL_TEST_POSTGRESQL_URL to test PostgreSQL")
_schema_numbers = itertools.count(1)


def _use_database(monkeypatch, *, database_url: str | None, database_path: Path):
    """Point settings and the shared engine at one database, as a fresh process would."""
    from backend.db import core
    from config import registry

    settings = registry.get_settings().model_copy(update={"database_url": database_url, "database_path": database_path})
    monkeypatch.setattr(registry, "_SETTINGS", settings)
    for name in ("_engine", "_SessionLocal", "_database_url", "_db_path"):
        monkeypatch.setattr(core, name, None)
    core.configure_db()
    return core.get_engine()


@pytest.fixture
def postgresql_database(tmp_path, monkeypatch):
    """An empty PostgreSQL schema of this test's own, as VODLoft's configured database."""
    from backend.db import core

    schema = f"backend_test_{os.getpid()}_{next(_schema_numbers)}"
    admin = sqlalchemy.create_engine(POSTGRESQL_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    url = make_url(POSTGRESQL_TEST_URL).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = _use_database(
        monkeypatch,
        database_url=url.render_as_string(hide_password=False),
        database_path=tmp_path / "vodloft.db",
    )
    yield engine
    core.get_engine().dispose()
    with admin.connect() as connection:
        connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    admin.dispose()


def _seeded_sqlite_database(tmp_path, monkeypatch) -> Path:
    from backend.db import seed_db
    from backend.db.migrations import upgrade_database

    path = tmp_path / "vodloft.db"
    _use_database(monkeypatch, database_url=None, database_path=path)
    upgrade_database()
    seed_db()
    from backend.db import core
    core.get_engine().dispose()
    return path


def _row_counts(engine) -> dict[str, int]:
    from backend.db.core import Base, load_database_models

    load_database_models()
    with engine.connect() as connection:
        return {
            table.name: connection.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables
        }


# Settings ----------------------------------------------------------------------

def test_without_a_database_url_vodloft_uses_its_sqlite_file(tmp_path):
    from config.settings.settings import AppSettings

    settings = AppSettings(database_path=tmp_path / "vodloft.db", database_url="  ")

    assert settings.database_url is None
    assert settings.resolved_database_url == f"sqlite:///{(tmp_path / 'vodloft.db').as_posix()}"


def test_the_database_url_never_reaches_a_settings_dump():
    from config.settings.settings import AppSettings

    settings = AppSettings(database_url="postgresql+psycopg://vodloft:hunter2pw@db/vodloft")

    assert settings.resolved_database_url == "postgresql+psycopg://vodloft:hunter2pw@db/vodloft"
    assert "hunter2pw" not in str(settings.model_dump()) and "hunter2pw" not in repr(settings)


# SQL that differs per database -------------------------------------------------

def _compiled(statement, dialect) -> str:
    return str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_json_array_items_reads_an_array_on_both_databases():
    from backend.db.json_sql import json_array_items
    from task_manager.scheduler.db import TaskRun

    scanned = json_array_items(TaskRun.result, "data", "collections").alias("scanned")
    statement = select(scanned.c.value["collection_id"].as_integer()).select_from(scanned)

    assert "json_each(task_runs.result, '$.\"data\".\"collections\"')" in _compiled(statement, sqlite.dialect())
    compiled = _compiled(statement, postgresql.dialect())
    assert "json_array_elements(CASE WHEN json_typeof((task_runs.result) -> 'data' -> 'collections') = 'array'" in compiled


def test_the_case_insensitive_username_uses_each_databases_collation():
    from sqlalchemy.schema import CreateTable

    from backend.db.models import User

    assert 'COLLATE "NOCASE"' in str(CreateTable(User.__table__).compile(dialect=sqlite.dialect()))
    assert 'COLLATE "vodloft_case_insensitive"' in str(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))


# Moving from SQLite ------------------------------------------------------------

def test_copying_needs_a_database_other_than_sqlite(tmp_path, monkeypatch):
    from backend.db.sqlite_copy import SQLiteCopyError, copy_sqlite_database

    source = _seeded_sqlite_database(tmp_path, monkeypatch)
    _use_database(monkeypatch, database_url=None, database_path=tmp_path / "other.db")

    with pytest.raises(SQLiteCopyError, match="Configure the database to copy into"):
        copy_sqlite_database(source)


def test_a_new_sqlite_database_is_not_filled_from_another_file(tmp_path, monkeypatch):
    from backend.db.sqlite_copy import copy_sqlite_database_on_first_start

    _use_database(monkeypatch, database_url=None, database_path=_seeded_sqlite_database(tmp_path, monkeypatch))

    assert copy_sqlite_database_on_first_start() is False


# PostgreSQL --------------------------------------------------------------------

@needs_postgresql
def test_a_new_postgresql_database_starts_at_the_current_schema(postgresql_database):
    from backend.db.migrations import check_database, get_current_revisions, get_head_revision, upgrade_database
    from backend.db.models import LocalMediaProfileBase, Settings
    from backend.db import get_session

    upgrade_database()

    check_database()
    assert get_current_revisions() == (get_head_revision(),)
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(Settings)) == 1
        assert session.scalar(select(func.count()).select_from(LocalMediaProfileBase)) > 0


@needs_postgresql
def test_usernames_stay_unique_regardless_of_case_on_postgresql(postgresql_database):
    from sqlalchemy.exc import IntegrityError

    from backend.db import get_session
    from backend.db.migrations import upgrade_database
    from backend.db.models import User

    upgrade_database()
    with get_session() as session:
        session.add(User(username="Samuel", password_hash="x"))
        session.commit()
        assert session.scalar(select(User.id).where(User.username == "SAMUEL")) is not None
        session.add(User(username="samuel", password_hash="x"))
        with pytest.raises(IntegrityError):
            session.commit()


@needs_postgresql
def test_the_first_start_on_postgresql_copies_the_sqlite_database(tmp_path, monkeypatch, postgresql_database):
    from backend.db import get_session
    from backend.db.migrations import check_database, upgrade_database
    from backend.db.models import Collection
    from backend.db.sqlite_copy import COPIED_SUFFIX

    postgresql_url = __import__("config").get_settings().database_url
    source = _seeded_sqlite_database(tmp_path, monkeypatch)
    expected = _row_counts(sqlalchemy.create_engine(f"sqlite:///{source.as_posix()}"))
    _use_database(monkeypatch, database_url=postgresql_url, database_path=source)

    upgrade_database()

    check_database()
    from backend.db import core
    assert _row_counts(core.get_engine()) == expected
    assert not source.exists()
    assert source.with_name(source.name + COPIED_SUFFIX).is_file()
    with get_session() as session:
        highest = session.scalar(select(func.max(Collection.id)))
        added = Collection(
            uuid="copied-sequence-check", source_key="ytdlp", slug="new", title="New", type="series", episode_identifier="numbered", membership_level="FREE",
            author_name="Host", author_slug="",
            sharing_url="https://example.test/new",
        )
        session.add(added)
        session.commit()
        assert added.id == highest + 1


@needs_postgresql
def test_copying_refuses_values_postgresql_would_reject(tmp_path, monkeypatch, postgresql_database):
    from backend.db import core
    from backend.db.sqlite_copy import SQLiteCopyError, copy_sqlite_database

    postgresql_url = __import__("config").get_settings().database_url
    source = _seeded_sqlite_database(tmp_path, monkeypatch)
    # SQLite ignores a VARCHAR's length; PostgreSQL enforces it.
    with sqlalchemy.create_engine(f"sqlite:///{source.as_posix()}").begin() as connection:
        connection.execute(text("UPDATE local_media_profiles SET subtitle_language_mode = :mode"), {"mode": "x" * 40})
    _use_database(monkeypatch, database_url=postgresql_url, database_path=tmp_path / "unused.db")

    with pytest.raises(SQLiteCopyError, match="local_media_profiles.subtitle_language_mode has 2 value"):
        copy_sqlite_database(source)
    assert not sqlalchemy.inspect(core.get_engine()).get_table_names()


@needs_postgresql
def test_write_transactions_queue_behind_each_other_on_postgresql(postgresql_database):
    from backend.db import get_session
    from backend.db.core import begin_write_transaction
    from backend.db.migrations import upgrade_database

    upgrade_database()
    first = get_session()
    begin_write_transaction(first)
    entered = threading.Event()

    def second_writer():
        with get_session() as second:
            begin_write_transaction(second)
            entered.set()
            second.rollback()

    thread = threading.Thread(target=second_writer)
    thread.start()
    time.sleep(0.5)
    assert not entered.is_set()
    first.rollback()
    first.close()
    thread.join(timeout=10)
    assert entered.is_set()


@needs_postgresql
def test_a_concurrent_write_transaction_does_not_wait_on_postgresql(postgresql_database):
    from backend.db import get_session
    from backend.db.core import begin_write_transaction
    from backend.db.migrations import upgrade_database

    upgrade_database()
    first = get_session()
    begin_write_transaction(first)
    try:
        with get_session() as second:
            begin_write_transaction(second, concurrent=True)
            second.rollback()
    finally:
        first.rollback()
        first.close()
