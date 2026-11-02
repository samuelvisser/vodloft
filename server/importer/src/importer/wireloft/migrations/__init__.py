"""WireLoft's own migrations, frozen, to bring an uploaded copy to one schema.

Each WireLoft release that changed the schema shipped one migration. The
importer reads only the newest schema, so a copy of an older WireLoft database
is first upgraded here. Supporting a new WireLoft release means adding its
migration file and a line to ``RELEASES``; nothing else.

The files are WireLoft's, with two changes: they no longer import WireLoft's
settings code (see ``_support``), and the runner below records revisions in
place of Alembic's environment. They never run on VODLoft's own database.
"""
from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from . import _support


@dataclass(frozen=True)
class Release:
    revision: str
    module: str
    label: str


RELEASES = (
    Release("0001", "0001_initial_schema", "1.0 (pre-release)"),
    Release("c8d4e2f1a7b9", "c8d4e2f1a7b9_wireloft_1_0", "1.0"),
    Release("d8b4a1f6c203", "d8b4a1f6c203_wireloft_1_1", "1.1"),
    Release("6d4a8c1f2b90", "6d4a8c1f2b90_wireloft_1_2", "1.2"),
    Release("f2a6c93d8b14", "f2a6c93d8b14_wireloft_1_2_1", "1.2.1 or 1.2.2"),
    Release("a4e7c19b2d53", "a4e7c19b2d53_wireloft_1_2_3", "1.2.3 or 1.2.4"),
    Release("c4e93f1a2b6d", "c4e93f1a2b6d_wireloft_1_2_5", "1.2.5"),
)
HEAD = RELEASES[-1].revision
_BY_REVISION = {release.revision: release for release in RELEASES}
_LEGACY_VERSION_TABLE = "alembic_version"
_lock = threading.Lock()


class UnknownWireLoftRelease(ValueError):
    def __init__(self, revision: str | None) -> None:
        self.revision = revision
        found = f"schema revision {revision}" if revision else "no schema revision"
        super().__init__(
            f"This WireLoft database has {found}, which this VODLoft does not know. "
            "Update VODLoft, or upgrade WireLoft to a release VODLoft supports."
        )


def release(revision: str | None) -> Release:
    try:
        return _BY_REVISION[revision]  # type: ignore[index]
    except KeyError:
        raise UnknownWireLoftRelease(revision) from None


def stored_revision(connection: sa.Connection) -> str | None:
    """WireLoft 1.0 kept Alembic's own table; 1.1 and later keep it in settings."""
    inspector = sa.inspect(connection)
    if inspector.has_table(_LEGACY_VERSION_TABLE):
        return connection.execute(sa.text(f"SELECT version_num FROM {_LEGACY_VERSION_TABLE}")).scalar()
    if not inspector.has_table(_support.SETTINGS_VERSION_TABLE):
        return None
    columns = {column["name"] for column in inspector.get_columns(_support.SETTINGS_VERSION_TABLE)}
    if _support.SETTINGS_VERSION_COLUMN not in columns:
        return None
    return connection.execute(sa.text(
        f"SELECT {_support.SETTINGS_VERSION_COLUMN} FROM {_support.SETTINGS_VERSION_TABLE} "
        f"WHERE {_support.SETTINGS_VERSION_COLUMN} IS NOT NULL ORDER BY id"
    )).scalar()


def _context(connection: sa.Connection) -> MigrationContext:
    metadata = sa.MetaData(naming_convention=_support.NAMING_CONVENTION)
    return MigrationContext.configure(connection, opts={"target_metadata": metadata})


def _record(connection: sa.Connection, revision: str) -> None:
    if sa.inspect(connection).has_table(_LEGACY_VERSION_TABLE):
        connection.execute(sa.text(f"UPDATE {_LEGACY_VERSION_TABLE} SET version_num = :revision"), {"revision": revision})
    else:
        connection.execute(sa.text(
            f"UPDATE {_support.SETTINGS_VERSION_TABLE} SET {_support.SETTINGS_VERSION_COLUMN} = :revision"
        ), {"revision": revision})


def upgrade(database: Path, *, target: str = HEAD, config: Path | None = None) -> list[Release]:
    """Upgrade the WireLoft database copy at ``database`` to ``target``. Returns the releases applied.

    ``config`` is the copy of WireLoft's config.yml, which the 1.0 migration rewrites as WireLoft did.
    """
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    applied: list[Release] = []
    try:
        with engine.connect() as connection:
            current = release(stored_revision(connection))
            order = [item.revision for item in RELEASES]
            if order.index(target) < order.index(current.revision):
                raise UnknownWireLoftRelease(current.revision)
            connection.rollback()
            # WireLoft's batch migrations rebuild tables other tables point at.
            connection.connection.dbapi_connection.execute("PRAGMA foreign_keys=OFF")
            with _lock:
                _support.config_path = config
                try:
                    for item in RELEASES[order.index(current.revision) + 1:order.index(target) + 1]:
                        module = importlib.import_module(f"{__name__}.{item.module}")
                        with connection.begin():
                            context = _context(connection)
                            with Operations.context(context):
                                module.upgrade()
                            _record(connection, item.revision)
                        applied.append(item)
                finally:
                    _support.config_path = None
    finally:
        engine.dispose()
    return applied


def create(database: Path, *, target: str = HEAD) -> None:
    """Create an empty WireLoft database of release ``target``, as a fresh WireLoft install would."""
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    try:
        with engine.begin() as connection:
            context = _context(connection)
            with Operations.context(context):
                importlib.import_module(f"{__name__}.{RELEASES[0].module}").upgrade()
            connection.execute(sa.text(f"CREATE TABLE {_LEGACY_VERSION_TABLE} (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            connection.execute(sa.text(f"INSERT INTO {_LEGACY_VERSION_TABLE} VALUES (:revision)"), {"revision": RELEASES[0].revision})
    finally:
        engine.dispose()
    upgrade(database, target=target)
