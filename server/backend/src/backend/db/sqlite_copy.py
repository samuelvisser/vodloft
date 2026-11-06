"""Move a VODLoft SQLite database into an empty database on another server.

The SQLite file is first upgraded to the current schema, the way VODLoft would
upgrade it on start. The target then gets the current schema and every row, in
one transaction, so it either receives the whole database or stays empty.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Integer, String, Table, create_engine, func, inspect as sa_inspect, select, text
from sqlalchemy.engine import Connection, Engine

from config import get_settings
from config.registry import replace_settings

from .core import Base, configure_db, get_database_label, get_engine, load_database_models
from .migrations import DatabaseMigrationError


logger = logging.getLogger(__name__)

_BATCH_SIZE = 1_000
_UNMANAGED_TABLES = {"apscheduler_jobs"}
# The copied SQLite file is renamed so it is never copied again, and kept as a backup.
COPIED_SUFFIX = ".copied-to-postgresql"


class SQLiteCopyError(DatabaseMigrationError):
    """The SQLite database cannot be copied as it is."""


def _tables() -> list[Table]:
    load_database_models()
    return [table for table in Base.metadata.sorted_tables if table.name not in _UNMANAGED_TABLES]


def _upgrade_source(path: Path) -> None:
    """Bring the SQLite file to the current schema, then point VODLoft back at the target."""
    from .migrations import require_database_current, upgrade_database  # migrations imports this module

    target = get_settings()
    replace_settings(target.model_copy(update={"database_url": None, "database_path": path}))
    try:
        configure_db()
        upgrade_database()
        require_database_current()
    finally:
        replace_settings(target)
        configure_db()


def _problems(source: Connection, tables: list[Table]) -> list[str]:
    """Data SQLite accepted but PostgreSQL refuses."""
    problems = [
        f"{row[0]} row {row[1]} refers to a missing {row[2]} row"
        for row in source.exec_driver_sql("PRAGMA foreign_key_check")
    ]
    for table in tables:
        for column in table.columns:
            if not isinstance(column.type, String):
                continue
            if column.type.length:
                too_long = source.scalar(
                    select(func.count()).select_from(table).where(func.length(column) > column.type.length)
                )
                if too_long:
                    problems.append(
                        f"{table.name}.{column.name} has {too_long} value(s) longer than {column.type.length} characters"
                    )
            with_nul = source.scalar(
                select(func.count()).select_from(table).where(func.instr(column, "\x00") > 0)
            )
            if with_nul:
                problems.append(f"{table.name}.{column.name} has {with_nul} value(s) with a NUL character")
    return problems


def _rows(source: Connection, table: Table) -> Iterator[list[dict]]:
    statement = select(table).order_by(*table.primary_key.columns)
    batch: list[dict] = []
    for row in source.execution_options(yield_per=_BATCH_SIZE).execute(statement).mappings():
        batch.append(dict(row))
        if len(batch) == _BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _reset_sequences(target: Connection, tables: list[Table]) -> None:
    """Continue each generated id after the highest copied one."""
    for table in tables:
        for column in table.primary_key.columns:
            if not isinstance(column.type, Integer) or column.autoincrement is False:
                continue
            sequence = target.scalar(
                text("SELECT pg_get_serial_sequence(:table, :column)"),
                {"table": table.name, "column": column.name},
            )
            if sequence is None:
                continue
            target.execute(
                text(f'SELECT setval(:sequence, COALESCE(MAX("{column.name}"), 1), MAX("{column.name}") IS NOT NULL) '
                     f'FROM "{table.name}"'),
                {"sequence": sequence},
            )


def copy_sqlite_database(path: Path) -> dict[str, int]:
    """Copy the SQLite database at ``path`` into the configured, empty database.

    Returns the number of rows copied per table.
    """
    target_engine = get_engine()
    if target_engine.dialect.name == "sqlite":
        raise SQLiteCopyError("Configure the database to copy into (databaseUrl or VL_DATABASE_URL) first")
    if not path.is_file() or path.stat().st_size == 0:
        raise SQLiteCopyError(f"No SQLite database at {path}")
    if set(sa_inspect(target_engine).get_table_names()) - _UNMANAGED_TABLES:
        raise SQLiteCopyError(f"Database '{get_database_label()}' is not empty; copy only into an empty database")

    _upgrade_source(path)
    tables = _tables()
    source_engine = create_engine(f"sqlite:///{path.as_posix()}")
    counts: dict[str, int] = {}
    try:
        with source_engine.connect() as source:
            problems = _problems(source, tables)
            if problems:
                raise SQLiteCopyError(
                    f"{path} has data PostgreSQL does not accept. Nothing was copied.\n  - " + "\n  - ".join(problems)
                )
            with target_engine.begin() as target:
                Base.metadata.create_all(target, tables=tables)
                for table in tables:
                    counts[table.name] = 0
                    for batch in _rows(source, table):
                        target.execute(table.insert(), batch)
                        counts[table.name] += len(batch)
                    if counts[table.name]:
                        logger.info("Copied %s rows of %s", counts[table.name], table.name)
                _reset_sequences(target, tables)
            # Fold the write-ahead log into the file, so the renamed file is complete on its own.
            source.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source_engine.dispose()
    return counts


def set_copied_sqlite_aside(path: Path) -> Path:
    """Rename the copied file and its WAL files, so it is kept but never copied again."""
    renamed = path.with_name(path.name + COPIED_SUFFIX)
    path.rename(renamed)
    for suffix in ("-wal", "-shm"):
        companion = path.with_name(path.name + suffix)
        if companion.exists():
            companion.rename(renamed.with_name(renamed.name + suffix))
    return renamed


def copy_sqlite_database_on_first_start() -> bool:
    """Fill a new, empty database server from VODLoft's SQLite file, if there is one.

    This is what makes moving to PostgreSQL a matter of configuring it and
    restarting: the first start finds the old database file and copies it.
    """
    path = get_settings().database_path
    if get_engine().dialect.name == "sqlite" or not path.is_file() or path.stat().st_size == 0:
        return False
    if set(sa_inspect(get_engine()).get_table_names()) - _UNMANAGED_TABLES:
        return False
    print(f"Copying the SQLite database {path} into {get_database_label()}...")
    counts = copy_sqlite_database(path)
    renamed = set_copied_sqlite_aside(path)
    print(f"Copied {sum(counts.values())} rows. The SQLite file is kept as {renamed}.")
    return True
