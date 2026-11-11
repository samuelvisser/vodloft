from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Optional, TypeVar
import importlib
import logging
import os
import pkgutil
import threading
import time

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from config import get_settings

from .datetime_types import UTCDateTime
from .text_types import create_case_insensitive_collation


logger = logging.getLogger(__name__)
T = TypeVar("T")

_SQLITE_BUSY_TIMEOUT_SECONDS = 30
_SQLITE_BUSY_TIMEOUT_MS = _SQLITE_BUSY_TIMEOUT_SECONDS * 1_000
# Idle connections kept open, and how many more may be opened under load.
# PostgreSQL allows 100 connections by default, so 60 leaves room for other clients.
_SERVER_POOL_SIZE = 10
_SERVER_POOL_MAX_OVERFLOW = 50
# The advisory lock that begin_write_transaction queues on in PostgreSQL. Any
# fixed 64-bit number works, as long as nothing else in the database uses it.
_POSTGRESQL_WRITE_LOCK_KEY = 0x564F444C6F6674  # "VODLoft"
# Database servers and proxies may drop idle connections; renew them well before that.
_SERVER_POOL_RECYCLE_SECONDS = 30 * 60

naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)
    type_annotation_map = {datetime: UTCDateTime()}


create_case_insensitive_collation(Base.metadata)


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None
_database_url: Optional[str] = None
_db_path: Optional[Path] = None


def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    """Apply per-connection SQLite settings used by API and worker threads."""
    cursor = dbapi_connection.cursor()
    try:
        # For SQLite, enable Foreign Key Support explicitly, according to official docs:
        # https://docs.sqlalchemy.org/en/21/dialects/sqlite.html#sqlite-foreign-keys
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def _enable_sqlite_wal(engine: Engine) -> None:
    """Enable WAL so long-running readers do not block unrelated writers."""
    with engine.connect() as connection:
        try:
            journal_mode = connection.exec_driver_sql(
                "PRAGMA journal_mode=WAL"
            ).scalar_one()
        except OperationalError:
            # A previous development/reload process can briefly retain a lock.
            # The busy timeout still protects this process; do not make startup
            # fail solely because WAL could not be switched during that window.
            logger.warning(
                "Could not enable SQLite WAL mode; continuing with the current journal mode",
                exc_info=True,
            )
            return

    if str(journal_mode).lower() != "wal":
        logger.warning(
            "SQLite did not enable WAL mode (journal_mode=%s)",
            journal_mode,
        )


def _sqlite_path(url: URL) -> Path | None:
    """The file behind a file-backed SQLite URL, or None for any other database."""
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)


def _create_sqlite_engine(url: URL, path: Path | None) -> Engine:
    if path is not None:
        os.makedirs(path.parent, exist_ok=True)
    # A bounded QueuePool is a poor fit for VODLoft's threaded SQLite workload.
    # The scheduler may run as many workers as the old default pool could serve,
    # leaving no connection headroom for API requests. SQLite connections are
    # cheap, and the busy timeout/WAL settings below already govern the actual
    # database contention, so open them on demand and close them with each Session.
    engine = create_engine(
        url,
        connect_args={
            "check_same_thread": False,
            # sqlite3 defaults to five seconds. Background workers and API writes
            # legitimately overlap, so give short writer bursts time to serialize.
            "timeout": _SQLITE_BUSY_TIMEOUT_SECONDS,
        },
        poolclass=NullPool,
    )
    event.listen(engine, "connect", _configure_sqlite_connection)
    _enable_sqlite_wal(engine)
    return engine


def _create_server_engine(url: URL) -> Engine:
    """An engine for a database server such as PostgreSQL.

    Every scheduler worker and every API request can hold a connection at the
    same time, and the worker counts can change while VODLoft runs. Keep a
    small pool of idle connections, but let it grow well past SQLAlchemy's
    default limit of fifteen instead of making workers wait for a connection.
    """
    return create_engine(
        url,
        pool_size=_SERVER_POOL_SIZE,
        max_overflow=_SERVER_POOL_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=_SERVER_POOL_RECYCLE_SECONDS,
    )


def configure_db() -> None:
    """Configure the global SQLAlchemy engine and session factory."""
    global _engine, _SessionLocal, _database_url, _db_path

    url = make_url(get_settings().resolved_database_url)
    url_key = url.render_as_string(hide_password=False)
    if _engine is not None and _database_url == url_key:
        return

    sqlite_path = _sqlite_path(url)
    if url.get_backend_name() == "sqlite":
        engine = _create_sqlite_engine(url, sqlite_path)
    else:
        engine = _create_server_engine(url)

    old_engine = _engine
    _engine = engine
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _database_url = url_key
    _db_path = sqlite_path
    if old_engine is not None:
        old_engine.dispose()


def get_engine() -> Engine:
    if _engine is None:
        configure_db()
    return _engine


# Session.info keys: a session from get_session only writes inside run_write_transaction.
_GUARDED = "vodloft_guarded"
_WRITER = "vodloft_writer"
_writing = threading.local()


class UnguardedWriteError(RuntimeError):
    """A write outside run_write_transaction, which every write in VODLoft goes through."""


def get_session() -> Session:
    """A session for reading. It refuses to write: writes go through ``run_write_transaction``."""
    if _SessionLocal is None:
        configure_db()
    session = _SessionLocal()
    session.info[_GUARDED] = True
    return session


def is_read_session(session: Session) -> bool:
    """Whether ``session`` refuses writes: it came from ``get_session`` and is not a write transaction's."""
    return bool(session.info.get(_GUARDED)) and not session.info.get(_WRITER)


def is_write_session(session: Session) -> bool:
    """Whether ``session`` is the session of a ``run_write_transaction``."""
    return bool(session.info.get(_WRITER))


def _refuse_unguarded(session: Session) -> None:
    if is_read_session(session):
        raise UnguardedWriteError("VODLoft writes to the database only through run_write_transaction")


@event.listens_for(Session, "before_flush")
def _flush_only_in_write_transactions(session: Session, _flush_context, _instances) -> None:
    if session.new or session.dirty or session.deleted:
        _refuse_unguarded(session)


@event.listens_for(Session, "do_orm_execute")
def _execute_writes_only_in_write_transactions(state) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        _refuse_unguarded(state.session)


def begin_write_transaction(session: Session, *, concurrent: bool = False) -> None:
    """Begin a write-intent transaction before any reads.

    These transactions read a row and then write it based on what they read,
    such as a task run's state. They must never run side by side, or one would
    overwrite the other's change.

    SQLite WAL permits concurrent readers, but a deferred transaction that reads
    before writing can fail with SQLITE_BUSY_SNAPSHOT when another writer commits
    first. BEGIN IMMEDIATE reserves the writer slot up front, allowing SQLite's
    busy timeout to queue these short write transactions instead of failing the
    later read-to-write upgrade.

    PostgreSQL lets every other transaction write at the same time. These ones
    queue on one transaction-level advisory lock instead, and as each statement
    reads the rows committed before it (READ COMMITTED), every transaction sees
    what the one before it wrote. A ``concurrent`` transaction only writes what
    it was given, such as a new row or a value the user chose, so it may run
    beside the others and takes no lock there. On SQLite it still reserves the
    one writer slot, as every write does.
    """
    if session.in_transaction():
        raise RuntimeError("Write transaction must begin before the session is used")

    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    elif bind.dialect.name == "postgresql" and not concurrent:
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _POSTGRESQL_WRITE_LOCK_KEY})
    else:
        session.begin()


_WRITE_ATTEMPTS = 3
# A write transaction that waits this long for its turn, or holds it this long, is logged, so a slow save names
# what was in its way.
_SLOW_WRITE_SECONDS = 1.0
_WRITE_RETRY_DELAY_SECONDS = 0.1
# PostgreSQL error codes that mean "try the transaction again": a deadlock, or a
# transaction that could not be serialized against another one.
_POSTGRESQL_RETRY_CODES = {"40P01", "40001"}


def is_lock_conflict(error: BaseException) -> bool:
    """Whether a database error only means another transaction was in the way."""
    if not isinstance(error, OperationalError):
        return False
    code = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    if code in _POSTGRESQL_RETRY_CODES:
        return True
    message = str(error.orig).lower()
    return "database is locked" in message or "database is busy" in message


def _log_slow_write(work: Callable, *, waited: float, held: float) -> None:
    if waited < _SLOW_WRITE_SECONDS and held < _SLOW_WRITE_SECONDS:
        return
    code = getattr(work, "__code__", None)
    where = f"{code.co_filename.rsplit('/src/', 1)[-1]}:{code.co_firstlineno}" if code else repr(work)
    logger.warning(
        "Slow write transaction %s (%s): waited %.1fs for its turn, held it %.1fs",
        getattr(work, "__qualname__", "?"), where, waited, held,
    )


def run_write_transaction(
    work: Callable[[Session], T], *, concurrent: bool = False, attempts: int = _WRITE_ATTEMPTS,
) -> T:
    """Run ``work`` in a write transaction of its own and commit it.

    The transaction starts with ``begin_write_transaction``, so it reads what
    the previous writer committed. When another transaction is in the way
    (a locked SQLite database, a PostgreSQL deadlock), the whole of ``work``
    runs again in a new transaction, a few times, before the error is raised.
    ``work`` may end the transaction early with ``session.rollback()``; any
    exception it raises rolls the transaction back and is raised as it is.

    ``work`` must be short: SQLite has one writer at a time, so every other
    write waits while it runs, and a retry runs it again. Look Sites up, read
    files and do other slow work before, and side effects such as webhooks
    after. ``concurrent`` lets the transaction run beside other writers where
    the database allows it; see ``begin_write_transaction``.
    """
    if getattr(_writing, "active", False):
        # A second write transaction on the same thread would wait for the first one forever.
        raise RuntimeError("run_write_transaction cannot run inside another write transaction")
    for attempt in range(attempts):
        session = get_session()
        session.info[_WRITER] = True
        _writing.active = True
        try:
            asked = time.monotonic()
            begin_write_transaction(session, concurrent=concurrent)
            began = time.monotonic()
            result = work(session)
            session.commit()
            _log_slow_write(work, waited=began - asked, held=time.monotonic() - began)
            return result
        except OperationalError as error:
            session.rollback()
            if attempt + 1 >= attempts or not is_lock_conflict(error):
                raise
        except BaseException:
            session.rollback()
            raise
        finally:
            _writing.active = False
            session.close()
        time.sleep(_WRITE_RETRY_DELAY_SECONDS * (2 ** attempt))
    raise AssertionError("unreachable")


def write_when_changed(work: Callable[[Session], T], *, concurrent: bool = False) -> T:
    """Run ``work`` on a read session, and again in a write transaction only when it changes something.

    For checks that run often and seldom find anything to store: most passes then
    only read, and do not wait for the writer's turn. ``work`` runs twice when it
    writes, so like any write transaction it must be short and free of side effects.
    """
    session = get_session()
    try:
        result = work(session)
        changed = bool(session.new or session.dirty or session.deleted)
    except UnguardedWriteError:
        changed = True
    finally:
        session.rollback()
        session.close()
    return run_write_transaction(work, concurrent=concurrent) if changed else result


def get_database_url() -> URL:
    if _engine is None:
        configure_db()
    return _engine.url


def get_database_label() -> str:
    """The configured database for messages and logs, with any password hidden."""
    if _db_path is not None:
        return str(_db_path)
    return get_database_url().render_as_string(hide_password=True)


def get_sqlite_database_path() -> Path | None:
    """The SQLite file in use, or None when VODLoft runs on another database."""
    if _engine is None:
        configure_db()
    return _db_path


def load_database_models() -> None:
    """Import every model that contributes tables to the shared metadata."""
    package_name = "backend.db.models"
    package = importlib.import_module(package_name)

    if hasattr(package, "__path__"):
        for _, name, _ in pkgutil.walk_packages(package.__path__, package_name + "."):
            importlib.import_module(name)

    # The scheduler owns models outside backend.db.models, but they inherit
    # backend.db.Base and therefore belong to the same Alembic schema.
    importlib.import_module("task_manager.scheduler.db")

    from sqlalchemy.orm import configure_mappers

    configure_mappers()


def seed_db() -> None:
    """Seed an already-migrated database with the development/demo data."""
    load_database_models()

    from sqlalchemy import select

    from backend.db.fake_data import episodes_for, collections as seed_collections
    from backend.db.models import Episode, Season, Collection
    from backend.services.sites import place_collection

    def work(session):
        for collection_index, collection_data in enumerate(seed_collections, start=1):
            if session.scalar(select(Collection.id).where(Collection.uuid == collection_data["uuid"])) is not None:
                continue
            collection = Collection(**collection_data)
            place_collection(session, collection)
            season = Season(collection=collection, index=1, slug=f"{collection.slug}-episodes", name="Episodes", season_number=1)
            session.add_all([collection, season])
            session.flush()
            session.add_all(
                Episode(collection_id=collection.id, season_id=season.id, **episode_data)
                for episode_data in episodes_for(collection_data, collection_index)
            )

    run_write_transaction(work)
