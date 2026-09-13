from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from config import get_settings
from sqlalchemy import inspect, text

from backend.db import engine


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("alembic")))
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    return config


def _record_current_revision() -> None:
    """Mirror Alembic's current revision into the singleton application settings row."""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if "application_settings" not in tables or "alembic_version" not in tables:
            return
        revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
        connection.execute(
            text("UPDATE application_settings SET alembic_version_num = :revision WHERE id = 1"),
            {"revision": revision},
        )


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)
    _record_current_revision()


def downgrade(revision: str = "-1") -> None:
    command.downgrade(alembic_config(), revision)
    _record_current_revision()


def current() -> None:
    command.current(alembic_config())
