from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


# Set VL_TEST_POSTGRESQL_URL (an empty PostgreSQL database the tests may fill) to
# run the tests that build an in-memory SQLite database on PostgreSQL instead. Each
# such engine gets a schema of its own, dropped when its test ends.
POSTGRESQL_TEST_URL = os.environ.get("VL_TEST_POSTGRESQL_URL") or None
_sqlite_create_engine = sqlalchemy.create_engine
_test_schema_numbers = itertools.count(1)
_test_schemas: list[tuple[str, object]] = []


def _postgresql_engine_for_memory_sqlite(url, *args, **kwargs):
    parsed = make_url(url)
    called_by_a_test = Path(sys._getframe(1).f_code.co_filename).is_relative_to(Path(__file__).parent)
    if (
        not called_by_a_test  # VODLoft's own scratch databases stay SQLite.
        or parsed.get_backend_name() != "sqlite"
        or parsed.database not in (None, "", ":memory:")
    ):
        return _sqlite_create_engine(url, *args, **kwargs)
    schema = f"test_{os.getpid()}_{next(_test_schema_numbers)}"
    with _postgresql_admin().connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = _sqlite_create_engine(POSTGRESQL_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    _test_schemas.append((schema, engine))
    return engine


_admin_engine = None


def _postgresql_admin():
    global _admin_engine
    if _admin_engine is None:
        _admin_engine = _sqlite_create_engine(POSTGRESQL_TEST_URL, isolation_level="AUTOCOMMIT")
    return _admin_engine


if POSTGRESQL_TEST_URL:
    # Test modules import create_engine after this conftest, so they get this one.
    sqlalchemy.create_engine = _postgresql_engine_for_memory_sqlite


def pytest_collection_modifyitems(config, items):
    if not POSTGRESQL_TEST_URL:
        return
    skip = pytest.mark.skip(reason="Tests SQLite itself; VL_TEST_POSTGRESQL_URL runs the tests on PostgreSQL")
    for item in items:
        if "sqlite_only" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def drop_postgresql_test_schemas():
    yield
    while _test_schemas:
        schema, engine = _test_schemas.pop()
        engine.dispose()
        with _postgresql_admin().connect() as connection:
            connection.exec_driver_sql("SET lock_timeout = '5s'")
            try:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            except sqlalchemy.exc.OperationalError:
                pass  # A connection the test left open still uses it; the database is disposable.


create_engine = sqlalchemy.create_engine
_test_schema_numbers = itertools.count(1)
_test_schemas: list[tuple[str, object]] = []


def _postgresql_engine_for_memory_sqlite(url, *args, **kwargs):
    parsed = make_url(url)
    called_by_a_test = Path(sys._getframe(1).f_code.co_filename).is_relative_to(Path(__file__).parent)
    if (
        not called_by_a_test  # VODLoft's own scratch databases stay SQLite.
        or parsed.get_backend_name() != "sqlite"
        or parsed.database not in (None, "", ":memory:")
    ):
        return _sqlite_create_engine(url, *args, **kwargs)
    schema = f"test_{os.getpid()}_{next(_test_schema_numbers)}"
    admin = _sqlite_create_engine(POSTGRESQL_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = _sqlite_create_engine(
        POSTGRESQL_TEST_URL, connect_args={"options": f"-csearch_path={schema}"},
    )
    _test_schemas.append((schema, admin))
    return engine


if POSTGRESQL_TEST_URL:
    # Test modules import create_engine after this conftest, so they get this one.
    sqlalchemy.create_engine = _postgresql_engine_for_memory_sqlite


def pytest_collection_modifyitems(config, items):
    if not POSTGRESQL_TEST_URL:
        return
    skip = pytest.mark.skip(reason="Tests SQLite itself; VL_TEST_POSTGRESQL_URL runs the tests on PostgreSQL")
    for item in items:
        if "sqlite_only" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def drop_postgresql_test_schemas():
    yield
    while _test_schemas:
        schema, admin = _test_schemas.pop()
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE pid <> pg_backend_pid() AND query_start IS NOT NULL AND datname = current_database() "
                f"AND state = 'idle in transaction'"
            )
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


create_engine = sqlalchemy.create_engine


@pytest.fixture(autouse=True)
def no_real_ytdlp(monkeypatch):
    """Sockets are disabled in tests, but a yt-dlp subprocess would still reach the internet."""
    from sources import ytdlp_runner as runner

    def refuse(*_args, **_kwargs):
        raise runner.YtDlpError("yt-dlp does not run in tests")

    monkeypatch.setattr(runner, "run_json", refuse)


@pytest.fixture(autouse=True)
def full_access_without_auth_guard(monkeypatch):
    """Most API tests mount a router on a bare FastAPI app, without the auth guard.

    The guard is what puts the signed-in person's access on the request; a
    bare app stands for an install without user accounts, where that access is
    everything. Tests of access itself use the real app, whose guard always
    sets it.
    """
    from backend.security import deps
    from backend.security.access import Access

    def request_access(request):
        return getattr(request.state, "access", None) or Access.full()

    monkeypatch.setattr(deps, "request_access", request_access)


@pytest.fixture(autouse=True)
def clean_event_bus():
    from task_manager.events.registry import (
        VodloftEventLinker,
        shutdown_event_emitter,
        wait_for_events,
    )

    VodloftEventLinker.remove_all()
    yield
    wait_for_events()
    VodloftEventLinker.remove_all()
    shutdown_event_emitter()


@pytest.fixture
def task_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Configure scheduler tests with a file-backed, disposable SQLite DB."""
    from backend.db import core
    from backend.db.core import Base
    from backend.db.models import Settings
    from task_manager.scheduler.db import (
        TaskDefinition,
        TaskOperation,
        TaskOperationDependency,
        TaskOperationRun,
        TaskOperationTarget,
        TaskRun,
        TaskSchedule,
    )

    database_path = tmp_path / "vodloft-test.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", session_factory)
    monkeypatch.setattr(core, "_db_path", database_path)

    Base.metadata.create_all(
        engine,
        tables=[
            Settings.__table__,
            TaskDefinition.__table__,
            TaskSchedule.__table__,
            TaskRun.__table__,
            TaskOperation.__table__,
            TaskOperationDependency.__table__,
            TaskOperationTarget.__table__,
            TaskOperationRun.__table__,
        ],
    )

    with session_factory() as session:
        session.add(Settings(onboarding_completed=True))
        session.commit()

    yield session_factory
    engine.dispose()

def available_artifact(path: Path | None = None) -> dict[str, object]:
    """Columns of a MediaDownload whose file is available.

    The database requires an available artifact to carry its filesystem identity:
    the identity of ``path``, or a placeholder for a test that never inspects the file.
    """
    if path is not None:
        from downloader.storage.identity import inspect_artifact

        identity = inspect_artifact(path)
        return {
            "artifact_status": "available",
            "artifact_stat_dev": identity.stat_dev,
            "artifact_stat_ino": identity.stat_ino,
            "artifact_size_bytes": identity.size_bytes,
            "artifact_fingerprint": identity.fingerprint,
        }
    return {
        "artifact_status": "available",
        "artifact_stat_dev": "1",
        "artifact_stat_ino": "1",
        "artifact_size_bytes": 0,
        "artifact_fingerprint": "0" * 64,
    }


def mark_artifact_available(download, path: Path | None = None) -> None:
    for field, value in available_artifact(path).items():
        setattr(download, field, value)


def schema_of(engine) -> dict[str, dict[str, object]]:
    """Every table's columns, keys, constraints and indexes, independent of their order in the SQL."""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    schema: dict[str, dict[str, object]] = {}
    for table in sorted(set(inspector.get_table_names()) - {"apscheduler_jobs"}):
        schema[table] = {
            "columns": [
                (column["name"], str(column["type"]), column["nullable"], column.get("default"))
                for column in inspector.get_columns(table)
            ],
            "primary_key": inspector.get_pk_constraint(table),
            "foreign_keys": sorted(
                (key["name"] or "", tuple(key["constrained_columns"]), key["referred_table"],
                 tuple(key["referred_columns"]), tuple(sorted(key.get("options", {}).items())))
                for key in inspector.get_foreign_keys(table)
            ),
            "unique": sorted(
                (constraint["name"] or "", tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table)
            ),
            "checks": sorted(
                (constraint["name"] or "", " ".join(constraint["sqltext"].split()))
                for constraint in inspector.get_check_constraints(table)
            ),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), bool(index["unique"]))
                for index in inspector.get_indexes(table)
            ),
        }
    return schema


def read_only_folder(monkeypatch, folder):
    """Refuse every write under ``folder`` the way a read-only mount would, even for root.

    Returns the list of refused attempts, so a test can also see what was tried.
    """
    import builtins
    import errno
    import io
    import os
    import shutil
    from pathlib import Path

    root = Path(folder).resolve()
    refused: list[str] = []

    def inside(path) -> bool:
        try:
            return Path(os.fsdecode(path)).resolve().is_relative_to(root)
        except (TypeError, ValueError):
            return False

    def refuse(name, *paths):
        if any(inside(path) for path in paths):
            refused.append(f"{name} {paths[0]}")
            raise OSError(errno.EROFS, "Read-only file system", os.fsdecode(paths[0]))

    def guard(module, name, count=1):
        original = getattr(module, name)

        def guarded(*args, **kwargs):
            refuse(name, *args[:count])
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, guarded)

    for name, count in (("rename", 2), ("replace", 2), ("remove", 1), ("unlink", 1), ("rmdir", 1),
                        ("mkdir", 1), ("makedirs", 1), ("utime", 1), ("chmod", 1), ("truncate", 1),
                        ("link", 2), ("symlink", 2)):
        guard(os, name, count)
    guard(shutil, "rmtree")
    guard(shutil, "move", 2)

    original_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)) and any(flag in mode for flag in "wax+"):
            refuse("open", file)
        return original_open(file, mode, *args, **kwargs)

    # pathlib opens through io.open, which is the same function under another name.
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)

    original_os_open = os.open
    writing = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & writing:
            refuse("open", path)
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_os_open)
    return refused


def folder_snapshot(folder):
    """Every file and folder under ``folder`` with its size, time and content hash."""
    import hashlib
    from pathlib import Path

    snapshot = {}
    for path in sorted(Path(folder).rglob("*")):
        stat = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        snapshot[str(path.relative_to(folder))] = (stat.st_size if path.is_file() else None, stat.st_mtime_ns, digest)
    return snapshot
