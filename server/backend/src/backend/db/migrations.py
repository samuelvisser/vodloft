from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError, ResolutionError, RevisionError
from alembic.util import CommandError
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.engine import Connection

from .alembic_version import SETTINGS_VERSION_COLUMN, SETTINGS_VERSION_TABLE
from .core import Base, get_database_label, get_engine, get_sqlite_database_path, load_database_models


ALEMBIC_DIR = Path(__file__).with_name("alembic")
_UNMANAGED_TABLES = {"apscheduler_jobs"}

# WireLoft's own releases. VODLoft's history starts at its 0.1.0 migration, and
# no VODLoft release ever stopped at one of these.
WIRELOFT_REVISIONS = frozenset({
    "0001", "c8d4e2f1a7b9", "d8b4a1f6c203", "6d4a8c1f2b90", "f2a6c93d8b14", "a4e7c19b2d53", "c4e93f1a2b6d",
})
_LEGACY_VERSION_TABLE = "alembic_version"


class DatabaseMigrationError(RuntimeError):
    """Raised when VODLoft cannot safely use or migrate the database."""


def get_alembic_config() -> Config:
    # Alembic's Config default binds stdout when Alembic itself is imported.
    # Test runners and other embedders can replace and close that stream later,
    # so always bind the currently active stream when creating a config.
    config = Config(stdout=sys.stdout)
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    return config


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(get_alembic_config())


def get_head_revisions() -> tuple[str, ...]:
    return tuple(_script_directory().get_heads())


def get_head_revision() -> str:
    heads = get_head_revisions()
    if len(heads) != 1:
        raise DatabaseMigrationError(
            f"VODLoft must have exactly one Alembic head, found {len(heads)}: {heads}"
        )
    return heads[0]


class WireLoftDatabaseError(DatabaseMigrationError):
    """The database is WireLoft's. VODLoft imports it instead of taking it over."""

    def __init__(self, database: Path | str) -> None:
        super().__init__(
            f"Database '{database}' belongs to WireLoft. VODLoft no longer upgrades a WireLoft "
            "database in place. Start VODLoft with an empty config folder, then import the "
            "WireLoft config folder from Settings > Import > WireLoft. The WireLoft folder is "
            "only read, never changed."
        )


def _sqlite_database_missing() -> bool:
    """Whether VODLoft runs on SQLite and its file does not exist yet."""
    path = get_sqlite_database_path()
    return path is not None and not path.exists()


def _refuse_wireloft_config() -> None:
    """A WireLoft config folder mounted as VODLoft's: its wireloft.db sits where VODLoft's database would."""
    path = get_sqlite_database_path()
    if path is None:
        return
    wireloft = path.with_name("wireloft.db")
    if wireloft.is_file() and not (path.is_file() and path.stat().st_size > 0):
        raise WireLoftDatabaseError(wireloft)


def _settings_revisions(connection: Connection) -> tuple[str, ...]:
    """Read the current revision from VODLoft's only supported version store."""
    inspector = sa_inspect(connection)
    if inspector.has_table(_LEGACY_VERSION_TABLE):
        raise WireLoftDatabaseError(get_database_label())
    if not inspector.has_table(SETTINGS_VERSION_TABLE):
        raise DatabaseMigrationError(
            f"Database '{get_database_label()}' does not contain current VODLoft migration metadata. "
            "Run 'backend-api db upgrade' to migrate it."
        )

    settings_columns = {
        column["name"] for column in inspector.get_columns(SETTINGS_VERSION_TABLE)
    }
    if SETTINGS_VERSION_COLUMN not in settings_columns:
        raise DatabaseMigrationError(
            f"Database '{get_database_label()}' predates the current VODLoft migration metadata. "
            "Run 'backend-api db upgrade' to migrate it."
        )

    return tuple(
        revision
        for revision in connection.execute(
            text(
                f"SELECT {SETTINGS_VERSION_COLUMN} "
                f"FROM {SETTINGS_VERSION_TABLE} "
                f"WHERE {SETTINGS_VERSION_COLUMN} IS NOT NULL "
                "ORDER BY id"
            )
        ).scalars()
        if revision is not None
    )


def get_current_revisions() -> tuple[str, ...]:
    if _sqlite_database_missing():
        return ()

    engine = get_engine()
    if not sa_inspect(engine).get_table_names():
        return ()

    with engine.connect() as connection:
        return _settings_revisions(connection)


def _database_tables() -> set[str]:
    if _sqlite_database_missing():
        return set()
    return set(sa_inspect(get_engine()).get_table_names())


def validate_database_migration_state() -> None:
    """Reject application schemas without valid current VODLoft revision state."""
    _refuse_wireloft_config()
    tables = _database_tables()
    application_tables = tables - _UNMANAGED_TABLES
    if not application_tables:
        return

    current = get_current_revisions()
    if not current:
        raise DatabaseMigrationError(
            f"Database '{get_database_label()}' contains VODLoft tables but its Alembic revision is empty. "
            "Refusing to guess the schema version."
        )
    if WIRELOFT_REVISIONS.intersection(current):
        raise WireLoftDatabaseError(get_database_label())

    scripts = _script_directory()
    for revision in current:
        try:
            scripts.get_revision(revision)
        except (CommandError, ResolutionError) as exc:
            raise DatabaseMigrationError(
                f"Database '{get_database_label()}' references unknown Alembic revision '{revision}'."
            ) from exc


def require_database_current() -> None:
    validate_database_migration_state()
    required = get_head_revision()
    current = get_current_revisions()
    if current != (required,):
        current_label = ", ".join(current) if current else "base / not initialized"
        raise DatabaseMigrationError(
            "Database schema is not current. "
            f"Current: {current_label}. Required: {required}. "
            "Run 'backend-api db upgrade'."
        )


def initialize_database() -> None:
    if _database_tables():
        raise DatabaseMigrationError(
            f"Database '{get_database_label()}' is not empty; db init only supports new or empty databases."
        )
    upgrade_database()


def upgrade_database() -> None:
    """Upgrade the schema and initialize application data for a fresh database."""
    _refuse_wireloft_config()
    is_initial_install = not (_database_tables() - _UNMANAGED_TABLES)
    if not is_initial_install:
        validate_database_migration_state()

    copied_from_sqlite = False
    try:
        if is_initial_install and get_engine().dialect.name != "sqlite":
            from .sqlite_copy import copy_sqlite_database_on_first_start

            copied_from_sqlite = copy_sqlite_database_on_first_start()
            if not copied_from_sqlite:
                _create_current_schema()
        else:
            command.upgrade(get_alembic_config(), "head")
    except CommandError as exc:
        raise DatabaseMigrationError(str(exc)) from exc

    require_database_current()

    if is_initial_install and not copied_from_sqlite:
        from .initial_seed import seed_initial_database

        seed_initial_database()


def _create_current_schema() -> None:
    """Create a new database other than SQLite straight at the latest schema.

    VODLoft's migrations so far were written for SQLite alone, so other
    databases start from the ORM schema and are marked current instead of
    replaying them. Migrations added after that run on every database. Defaults that a
    new installation needs come from the initial seed, never from a migration.
    """
    load_database_models()
    engine = get_engine()
    tables = [table for table in Base.metadata.sorted_tables if table.name not in _UNMANAGED_TABLES]
    Base.metadata.create_all(engine, tables=tables)
    command.stamp(get_alembic_config(), "head")


def _is_relative_downgrade(revision: str) -> bool:
    return revision.startswith("-") and revision[1:].isdigit()


def _validate_downgrade_target(revision: str) -> list:
    """Verify the target is reachable by downgrading from the DB's current path."""
    current = get_current_revisions()
    if not current:
        raise DatabaseMigrationError(
            f"Database '{get_database_label()}' has no current Alembic revision to downgrade."
        )

    if len(current) > 1 and _is_relative_downgrade(revision):
        current_label = ", ".join(current)
        raise DatabaseMigrationError(
            f"Database has multiple current Alembic revisions ({current_label}). "
            f"Relative downgrade '{revision}' is ambiguous; specify an explicit target revision."
        )

    current_label = ", ".join(current)
    try:
        # Start traversal at the revision(s) actually stored in the database, not
        # at the script directory's global head(s). Unrelated Alembic branches
        # therefore do not prevent recovery of the branch this database is on.
        return list(
            _script_directory().iterate_revisions(
                current,
                revision,
                select_for_downgrade=True,
            )
        )
    except RangeNotAncestorError as exc:
        raise DatabaseMigrationError(
            f"Cannot downgrade database from {current_label} to '{revision}': "
            "the requested revision is not an ancestor of the database's current revision(s)."
        ) from exc
    except (CommandError, RevisionError) as exc:
        raise DatabaseMigrationError(
            f"Cannot downgrade database from {current_label} to '{revision}': {exc}"
        ) from exc


def downgrade_database(revision: str) -> None:
    validate_database_migration_state()
    _validate_downgrade_target(revision)
    try:
        command.downgrade(get_alembic_config(), revision)
    except CommandError as exc:
        raise DatabaseMigrationError(str(exc)) from exc


def check_database() -> None:
    """Verify both the DB revision and ORM-to-migration schema synchronization."""
    require_database_current()
    try:
        command.check(get_alembic_config())
    except CommandError as exc:
        raise DatabaseMigrationError(str(exc)) from exc


def create_revision(message: str) -> None:
    require_database_current()
    try:
        command.revision(get_alembic_config(), message=message, autogenerate=True)
    except CommandError as exc:
        raise DatabaseMigrationError(str(exc)) from exc


def get_database_status() -> tuple[tuple[str, ...], str]:
    validate_database_migration_state()
    return get_current_revisions(), get_head_revision()


def collection_history() -> None:
    try:
        command.history(get_alembic_config(), verbose=True)
    except CommandError as exc:
        raise DatabaseMigrationError(str(exc)) from exc
