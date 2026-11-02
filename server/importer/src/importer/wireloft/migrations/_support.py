"""What WireLoft's frozen migrations used from WireLoft's own code.

They run only on an uploaded copy, through ``importer.wireloft.migrations.upgrade``,
which records the revision itself. Alembic's version table is therefore not
switched, and the 1.0 migration rewrites the uploaded copy of config.yml, if
there is one, instead of a live config file.
"""
from __future__ import annotations

from pathlib import Path

SETTINGS_VERSION_TABLE = "settings"
SETTINGS_VERSION_COLUMN = "alembic_version_num"

# WireLoft's metadata naming convention, which names the constraints its
# migrations create without a name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

config_path: Path | None = None


def apply_settings_version_table(_context) -> None:
    """The runner records versions itself, so there is nothing to switch."""
