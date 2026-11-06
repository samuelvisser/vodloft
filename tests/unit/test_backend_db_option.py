from __future__ import annotations

from pathlib import Path

import pytest


def test_db_option_points_db_commands_at_that_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import backend.__main__ as backend_main
    from backend.db import core
    from config import registry

    # Start from settings that name another database, like a normal install.
    default_path = tmp_path / "default.db"
    monkeypatch.setattr(registry, "_SETTINGS", registry.get_settings().model_copy(update={"database_path": default_path, "database_url": None}))
    monkeypatch.setenv("VL_DATABASE_PATH", str(default_path))
    monkeypatch.delenv("VL_DATABASE_URL", raising=False)
    for name in ("_engine", "_SessionLocal", "_database_url", "_db_path"):
        monkeypatch.setattr(core, name, None)

    chosen = tmp_path / "chosen.db"
    backend_main.main(["db", "init", "--db", str(chosen)])

    assert chosen.is_file()
    assert not default_path.exists()
    assert core.get_sqlite_database_path() == chosen


def test_db_option_wins_over_a_configured_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import backend.__main__ as backend_main
    from backend.db import core
    from config import registry

    monkeypatch.setattr(registry, "_SETTINGS", registry.get_settings().model_copy(update={
        "database_path": tmp_path / "default.db", "database_url": "postgresql+psycopg://vodloft@unreachable/vodloft",
    }))
    monkeypatch.setenv("VL_DATABASE_URL", "postgresql+psycopg://vodloft@unreachable/vodloft")
    monkeypatch.setenv("VL_DATABASE_PATH", str(tmp_path / "default.db"))
    for name in ("_engine", "_SessionLocal", "_database_url", "_db_path"):
        monkeypatch.setattr(core, name, None)

    chosen = tmp_path / "chosen.db"
    backend_main.main(["db", "init", "--db", str(chosen)])

    assert chosen.is_file()
    assert core.get_engine().dialect.name == "sqlite"


def test_database_url_option_points_db_commands_at_that_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import backend.__main__ as backend_main
    from backend.db import core
    from config import registry

    monkeypatch.setattr(registry, "_SETTINGS", registry.get_settings().model_copy(update={
        "database_path": tmp_path / "default.db", "database_url": None,
    }))
    monkeypatch.delenv("VL_DATABASE_URL", raising=False)
    for name in ("_engine", "_SessionLocal", "_database_url", "_db_path"):
        monkeypatch.setattr(core, name, None)

    chosen = tmp_path / "by-url.db"
    backend_main.main(["db", "init", "--database-url", f"sqlite:///{chosen.as_posix()}"])

    assert chosen.is_file()
    assert not (tmp_path / "default.db").exists()
