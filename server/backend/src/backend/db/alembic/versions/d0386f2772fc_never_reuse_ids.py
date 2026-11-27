"""Never give a deleted record's id to a new one.

SQLite gives a new row the highest id in its table plus one, so the id of the record deleted last came back for the
next one: a new collection could get the id of a deleted collection. A table whose id says AUTOINCREMENT never hands
out an id twice. SQLite cannot add that to a table, so each table with an id of its own is built again from the SQL it
was made with, with AUTOINCREMENT on its id, and keeps its rows, its indexes and the highest id it gave so far.

PostgreSQL never reuses an id, so this changes nothing there.

Revision ID: d0386f2772fc
Revises: a79d0f6c0f17
Create Date: 2026-11-26
"""
from __future__ import annotations

import re

from alembic import op

revision = "d0386f2772fc"
down_revision = "a79d0f6c0f17"
branch_labels = None
depends_on = None

# Every table whose own integer id SQLite hands out. Tables of a subtype share the id of their parent's row.
_TABLES = (
    "collection_lists", "collection_local_assets", "collections", "creator_accounts", "creators",
    "custom_index_states", "download_profile_filters", "download_profiles", "existing_file_scans",
    "health_dismissals", "import_links", "import_runs", "import_steps", "local_media_profiles",
    "media_download_assets", "media_download_history", "media_downloads", "media_items", "metadata",
    "movie_extra_sources", "notification_deliveries", "notification_destinations", "notification_events",
    "notification_rules", "push_subscriptions", "push_vapid_keys", "quick_download_history", "seasons", "settings",
    "stream_profiles", "task_definitions", "task_operation_dependencies", "task_operation_targets", "task_runs",
    "task_schedules", "users",
)

_CREATE = re.compile(r'^\s*CREATE\s+TABLE\s+(?:"[^"]+"|\S+)\s*\(', re.IGNORECASE)
_ID_COLUMN = re.compile(r'(\(\s*|,\s*)("?id"?\s+INTEGER)\b((?:\s+NOT\s+NULL)?)(\s+PRIMARY\s+KEY)?', re.IGNORECASE)
_TABLE_KEY = re.compile(r',\s*(?:CONSTRAINT\s+(?:"[^"]+"|\S+)\s+)?PRIMARY\s+KEY\s*\(\s*"?id"?\s*\)', re.IGNORECASE)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _with_autoincrement(table: str, sql: str, new_name: str) -> str:
    """The table's own CREATE TABLE, named ``new_name``, with AUTOINCREMENT on its id."""
    sql, created = _CREATE.subn(f"CREATE TABLE {_quote(new_name)} (", sql, count=1)
    id_column = _ID_COLUMN.search(sql)
    if not created or id_column is None:
        raise RuntimeError(f"Cannot find the id of table {table} in: {sql}")
    if not id_column.group(4):
        sql, keys = _TABLE_KEY.subn("", sql)
        if keys != 1:
            raise RuntimeError(f"Cannot find the primary key of table {table} in: {sql}")
        id_column = _ID_COLUMN.search(sql)
    start, end = id_column.span()
    return (
        sql[:start] + id_column.group(1) + id_column.group(2) + id_column.group(3)
        + " PRIMARY KEY AUTOINCREMENT" + sql[end:]
    )


_AUTOINCREMENT_ID = re.compile(r'("?id"?\s+INTEGER\s+NOT\s+NULL)\s+PRIMARY\s+KEY\s+AUTOINCREMENT', re.IGNORECASE)


def _without_autoincrement(table: str, sql: str, new_name: str) -> str:
    """The table's CREATE TABLE as the migrations before this one left it: its id a plain named primary key."""
    sql, created = _CREATE.subn(f"CREATE TABLE {_quote(new_name)} (", sql, count=1)
    sql, ids = _AUTOINCREMENT_ID.subn(r"\1", sql, count=1)
    if not created or not ids:
        raise RuntimeError(f"Cannot find the id of table {table} in: {sql}")
    end = sql.rindex(")")
    return sql[:end].rstrip() + f", \n\tCONSTRAINT pk_{table} PRIMARY KEY (id)\n" + sql[end:]


def _rebuild(table: str, rewrite, *, done) -> None:
    """Build ``table`` again from its own SQL as ``rewrite`` changes it, with its rows, indexes and triggers."""
    bind = op.get_bind()
    sql = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).scalar_one_or_none()
    if sql is None or done(sql):
        return
    # Indexes made for UNIQUE constraints have no SQL of their own and come back with the table.
    others = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL",
        (table,),
    ).scalars().all()
    columns = ", ".join(_quote(row[1]) for row in bind.exec_driver_sql(f"PRAGMA table_info({_quote(table)})"))
    new_name = f"_rebuilt_{table}"

    bind.exec_driver_sql(rewrite(table, sql, new_name))
    # Rows keep their ids; with AUTOINCREMENT, SQLite then counts on from the highest of them.
    bind.exec_driver_sql(f"INSERT INTO {_quote(new_name)} ({columns}) SELECT {columns} FROM {_quote(table)}")
    bind.exec_driver_sql(f"DROP TABLE {_quote(table)}")
    bind.exec_driver_sql(f"ALTER TABLE {_quote(new_name)} RENAME TO {_quote(table)}")
    for other in others:
        bind.exec_driver_sql(other)


def _has_autoincrement(sql: str) -> bool:
    return re.search(r"\bAUTOINCREMENT\b", sql, re.IGNORECASE) is not None


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table in _TABLES:
        _rebuild(table, _with_autoincrement, done=_has_autoincrement)


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table in _TABLES:
        _rebuild(table, _without_autoincrement, done=lambda sql: not _has_autoincrement(sql))
