from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from config import get_settings


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("alembic")))
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    return config


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def downgrade(revision: str = "-1") -> None:
    command.downgrade(alembic_config(), revision)


def current() -> None:
    command.current(alembic_config())
