from __future__ import annotations

import argparse
import os
import psutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import Optional

import uvicorn
from sqlalchemy import text

from backend.db import configure_db, get_database_label, get_engine, get_sqlite_database_path, seed_db
from backend.db.background_migrations import (
    BackgroundMigrationError,
    get_background_migration_history,
    validate_background_migration_state,
)
from backend.db.migrations import (
    DatabaseMigrationError,
    check_database,
    create_revision,
    downgrade_database,
    get_current_revisions,
    get_database_status,
    get_head_revisions,
    initialize_database,
    require_database_current,
    collection_history,
    upgrade_database,
    validate_database_migration_state,
)
from config.registry import get_settings, replace_settings
from .config import PROJECT_ROOT


def _add_database_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--db", dest="db", help="Path to a SQLite database file")
    group.add_argument(
        "--database-url",
        dest="database_url",
        help="SQLAlchemy database URL, such as postgresql+psycopg://user:password@host/vodloft",
    )


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="backend-api",
        description="VODLoft backend API and DB utilities",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    run_parser = subparsers.add_parser("run", help="Start the backend API server")
    _add_database_options(run_parser)
    run_parser.add_argument("--host", default="127.0.0.1", help="Host to bind when running server")
    run_parser.add_argument("--port", type=int, default=5001, help="Port to bind when running server")
    run_parser.add_argument("--debug", action="store_true", help="Enable debug/reload mode")

    db_parser = subparsers.add_parser("db", help="Database management commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True, help="Database operation")

    for command_name, help_text in (
        ("init", "Initialize a new or empty database at the latest schema"),
        ("upgrade", "Apply all pending database migrations"),
        ("current", "Collection the current and latest database revisions"),
        ("history", "Show the Alembic migration history"),
        ("check", "Verify the DB is current and ORM metadata matches migrations"),
        ("seed", "Seed the database with demo data"),
    ):
        command_parser = db_subparsers.add_parser(command_name, help=help_text)
        _add_database_options(command_parser)

    downgrade_parser = db_subparsers.add_parser(
        "downgrade",
        help="Downgrade the database to an Alembic revision",
    )
    downgrade_parser.add_argument(
        "revision",
        help="Target Alembic revision or relative step such as -1",
    )
    _add_database_options(downgrade_parser)

    copy_parser = db_subparsers.add_parser(
        "copy-from-sqlite",
        help="Copy a VODLoft SQLite database into the configured, empty database (such as PostgreSQL)",
    )
    copy_parser.add_argument("sqlite_path", help="The SQLite database file to copy; it is upgraded first")
    copy_parser.add_argument(
        "--database-url",
        dest="database_url",
        help="SQLAlchemy URL of the database to copy into, instead of the configured one",
    )

    revision_parser = db_subparsers.add_parser(
        "revision",
        help="Generate an Alembic revision from ORM model changes",
    )
    _add_database_options(revision_parser)
    revision_parser.add_argument("-m", "--message", required=True, help="Migration description")

    background_parser = subparsers.add_parser(
        "background-migrations",
        aliases=["migrate"],
        help="Inspect background data migrations",
    )
    background_subparsers = background_parser.add_subparsers(
        dest="background_migration_command",
        required=True,
        help="Background migration operation",
    )
    for command_name, help_text in (
        ("current", "Collection the current and latest background migration revisions"),
        ("history", "Show the ordered background migration history"),
        ("check", "Verify the background migration chain and stored revision"),
    ):
        command_parser = background_subparsers.add_parser(command_name, help=help_text)
        _add_database_options(command_parser)

    users_parser = subparsers.add_parser("users", help="User account recovery")
    _add_database_options(users_parser)
    users_subparsers = users_parser.add_subparsers(dest="users_command", required=True, help="User operation")
    users_subparsers.add_parser("list", help="List user accounts")
    reset_parser = users_subparsers.add_parser(
        "reset-password",
        help="Set a new password for a user, enable them and sign them out everywhere",
    )
    reset_parser.add_argument("username", help="The user's username")
    reset_parser.add_argument(
        "--administrator",
        action="store_true",
        help="Also make the user an administrator, to recover from a lockout",
    )

    subparsers.add_parser("stop", help="Stop all running backend-api processes")
    return parser.parse_args(argv)


def _validate_db_health() -> None:
    sqlite_path = get_sqlite_database_path()
    if sqlite_path is not None and not sqlite_path.exists():
        print(
            f"Database file not found: {sqlite_path}\n"
            "Run 'backend-api db init' to initialize the schema, or provide --db or --database-url.",
            file=sys.stderr,
        )
        sys.exit(1)

    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"Failed to connect to database: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        from sqlalchemy import inspect as sa_inspect

        inspector = sa_inspect(engine)
        if not inspector.get_table_names():
            print(
                "Database is empty (no tables). Run 'backend-api db init' to initialize the schema.",
                file=sys.stderr,
            )
            sys.exit(1)
    except Exception:
        pass


def _reload_startup_marker(supervisor_pid: str) -> Path:
    """Marker file shared by all worker subprocesses of one reload session."""
    return Path(tempfile.gettempdir()) / f"vodloft-reload-startup-{supervisor_pid}.lock"


_STOP_SIGTERM_TIMEOUT_S = 5.0


def _matches_backend_api(cmdline: Optional[list[str]]) -> bool:
    """Whether a process's cmdline looks like a backend-api invocation."""
    if not cmdline:
        return False
    return any(
        arg == "backend-api" or arg.endswith(("/backend-api", "\\backend-api"))
        for arg in cmdline
    )


def _stop_backend() -> None:
    """Stop all other running backend-api processes."""
    own_pid = os.getpid()
    targets: dict[int, psutil.Process] = {}

    for proc in psutil.process_iter(["pid", "cmdline"]):
        if proc.pid == own_pid:
            continue
        try:
            if _matches_backend_api(proc.info.get("cmdline")):
                targets[proc.pid] = proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if not targets:
        print("No running backend-api processes found")
        return

    for proc in list(targets.values()):
        try:
            for child in proc.children(recursive=True):
                targets.setdefault(child.pid, child)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    for proc in targets.values():
        try:
            print(f"Stopping backend-api process (PID: {proc.pid})")
            proc.send_signal(signal.SIGTERM)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    _gone, alive = psutil.wait_procs(
        list(targets.values()),
        timeout=_STOP_SIGTERM_TIMEOUT_S,
    )
    for proc in alive:
        try:
            print(f"Process {proc.pid} did not stop in time; killing it")
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    if alive:
        psutil.wait_procs(alive, timeout=_STOP_SIGTERM_TIMEOUT_S)

    print(f"Stopped {len(targets)} backend-api process(es)")


def _configure_database_for_args(args: argparse.Namespace) -> None:
    database_url = getattr(args, "database_url", None)
    database_path = getattr(args, "db", None)
    settings = get_settings()
    # Reload workers build their own settings from the environment; this
    # process already has settings, so point them at the database too.
    if database_url:
        os.environ["VL_DATABASE_URL"] = database_url
        settings = settings.model_copy(update={"database_url": database_url})
    elif database_path:
        # A SQLite file named on the command line wins over a configured URL.
        os.environ["VL_DATABASE_URL"] = ""
        os.environ["VL_DATABASE_PATH"] = database_path
        settings = settings.model_copy(update={"database_url": None, "database_path": Path(database_path)})
    if settings is not get_settings():
        replace_settings(settings)
    configure_db()


def _handle_db_command(args: argparse.Namespace) -> None:
    _configure_database_for_args(args)

    if args.db_command == "init":
        initialize_database()
        print(f"Initialized database at: {get_database_label()}")
        return

    if args.db_command == "upgrade":
        upgrade_database()
        _current, head = get_database_status()
        print(f"Database upgraded to: {head} ({get_database_label()})")
        return

    if args.db_command == "downgrade":
        downgrade_database(args.revision)
        current = get_current_revisions()
        current_label = ", ".join(current) if current else "base / not initialized"
        print(f"Database downgraded to: {current_label} ({get_database_label()})")
        return

    if args.db_command == "current":
        validate_database_migration_state()
        current = get_current_revisions()
        heads = get_head_revisions()
        current_label = ", ".join(current) if current else "base / not initialized"
        head_label = ", ".join(heads) if heads else "none"
        current_noun = "revision" if len(current) <= 1 else "revisions"
        head_noun = "revision" if len(heads) == 1 else "revisions"
        if len(heads) > 1:
            status = f"multiple Alembic heads ({len(heads)})"
        elif heads and current == (heads[0],):
            status = "up to date"
        else:
            status = "upgrade required"
        print(f"Current database {current_noun}: {current_label}")
        print(f"Latest VODLoft {head_noun}:  {head_label}")
        print(f"Status: {status}")
        return

    if args.db_command == "history":
        collection_history()
        return

    if args.db_command == "check":
        check_database()
        print("Database revision and ORM metadata are in sync.")
        return

    if args.db_command == "revision":
        create_revision(args.message)
        return

    if args.db_command == "copy-from-sqlite":
        from backend.db.sqlite_copy import copy_sqlite_database

        counts = copy_sqlite_database(Path(args.sqlite_path))
        print(f"Copied {sum(counts.values())} rows from {args.sqlite_path} into {get_database_label()}")
        return

    if args.db_command == "seed":
        require_database_current()
        seed_db()
        print(f"Seeded database at: {get_database_label()}")
        return

    raise RuntimeError(f"Unsupported database command: {args.db_command}")


def _handle_background_migration_command(args: argparse.Namespace) -> None:
    _configure_database_for_args(args)

    if args.background_migration_command == "history":
        history = get_background_migration_history()
        if not history:
            print("No background migrations registered.")
            return
        for migration in history:
            upstream = migration.down_revision or "<base>"
            print(f"{upstream} -> {migration.revision}  {migration.title}")
        return

    require_database_current()
    current, head = validate_background_migration_state()
    current_label = current or "base / not initialized"
    head_label = head or "base / none"

    if args.background_migration_command == "current":
        status = "up to date" if current == head else "migration required"
        print(f"Current background migration revision: {current_label}")
        print(f"Latest background migration revision:  {head_label}")
        print(f"Status: {status}")
        return

    if args.background_migration_command == "check":
        print(
            "Background migration chain and stored revision are valid "
            f"(current: {current_label}, head: {head_label})."
        )
        return

    raise RuntimeError(
        f"Unsupported background migration command: {args.background_migration_command}"
    )


def _handle_users_command(args: argparse.Namespace) -> None:
    from getpass import getpass

    from backend.db import get_session
    from backend.security.access import TEMPLATES, ADMINISTRATOR_TEMPLATE
    from backend.services import users
    from config.security.passwords import derive_admin_password_client_value

    _configure_database_for_args(args)
    require_database_current()

    with get_session() as session:
        if args.users_command == "list":
            listed = users.list_users(session)
            if not listed:
                print("No user accounts.")
            for user in listed:
                role = "administrator" if users.is_administrator(user) else (user.template_key or "custom")
                state = "enabled" if user.is_enabled else "disabled"
                print(f"{user.username}  ({role}, {state})")
            print(f"User accounts are {'on' if users.accounts_enabled(session) else 'off'}.")
            return

        if args.users_command == "reset-password":
            user = users.find_user(session, args.username)
            if user is None:
                print(f"No user named {args.username!r}.", file=sys.stderr)
                sys.exit(1)
            password = getpass("New password: ")
            if len(password) < 7:
                print("Use at least 7 characters.", file=sys.stderr)
                sys.exit(1)
            if getpass("Again: ") != password:
                print("The passwords differ.", file=sys.stderr)
                sys.exit(1)
            users.reset_password(user, derive_admin_password_client_value(password), must_change=False)
            if args.administrator:
                users.update_user(session, user, access=users.AccessList.from_template(ADMINISTRATOR_TEMPLATE))
            users.update_user(session, user, enabled=True)
            session.commit()
            role = TEMPLATES[ADMINISTRATOR_TEMPLATE].name.lower() if users.is_administrator(user) else "user"
            print(f"{user.username} ({role}) can sign in with the new password. Their other sessions are signed out.")
            return

    raise RuntimeError(f"Unsupported users command: {args.users_command}")


def main(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(argv)

    if args.command == "stop":
        _stop_backend()
        return

    try:
        if args.command == "db":
            _handle_db_command(args)
            return

        if args.command == "users":
            _handle_users_command(args)
            return

        if args.command in {"background-migrations", "migrate"}:
            _handle_background_migration_command(args)
            return

        if args.command == "run":
            _configure_database_for_args(args)

            print("Starting VODLoft backend...")
            _validate_db_health()
            require_database_current()
            validate_background_migration_state()
            debug = args.debug

            if debug:
                supervisor_pid = str(os.getpid())
                os.environ["VODLOFT_RELOAD_SUPERVISOR_PID"] = supervisor_pid
                _reload_startup_marker(supervisor_pid).unlink(missing_ok=True)

            try:
                uvicorn.run(
                    "backend.app:create_app",
                    factory=True,
                    host=args.host,
                    port=args.port,
                    reload=debug,
                    reload_dirs=str(PROJECT_ROOT / "server") if debug else None,
                    log_level="debug" if debug else "info",
                )
            finally:
                if debug:
                    _reload_startup_marker(os.getpid()).unlink(missing_ok=True)
            return
    except BackgroundMigrationError as exc:
        print(f"Background migration error: {exc}", file=sys.stderr)
        sys.exit(1)
    except DatabaseMigrationError as exc:
        print(f"Database migration error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
