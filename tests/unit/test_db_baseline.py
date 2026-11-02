"""The baseline replaces WireLoft's migrations without changing the schema VODLoft builds on."""
from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from conftest import schema_of
from importer.wireloft import migrations as wireloft

BASELINE = "a4e7c19b2d53"


@pytest.fixture
def vodloft_database(tmp_path, monkeypatch):
    from backend.db import core

    path = tmp_path / "vodloft.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(core, "_db_path", path)
    yield path, engine
    engine.dispose()


def _old_chain(path, target=BASELINE):
    """A database built the way VODLoft built them before the baseline: WireLoft's migrations, in order."""
    wireloft.create(path, target=target)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    return engine


def test_the_baseline_builds_the_schema_the_old_migrations_built(vodloft_database, tmp_path):
    from backend.db.migrations import get_alembic_config

    _path, engine = vodloft_database
    command.upgrade(get_alembic_config(), BASELINE)
    old = _old_chain(tmp_path / "old.db")
    try:
        assert schema_of(engine) == schema_of(old)
        with engine.connect() as connection, old.connect() as old_connection:
            query = text("SELECT onboarding_completed, alembic_version_num, background_migration_version FROM settings")
            assert connection.execute(query).all() == old_connection.execute(query).all()
    finally:
        old.dispose()


def test_a_database_from_before_the_baseline_upgrades_to_the_same_schema(vodloft_database, tmp_path):
    from backend.db.migrations import check_database, get_alembic_config, upgrade_database

    _path, fresh = vodloft_database
    upgrade_database()
    check_database()

    old_path = tmp_path / "old.db"
    _old_chain(old_path).dispose()
    config = get_alembic_config()
    from backend.db import core

    old = create_engine(f"sqlite:///{old_path.as_posix()}")
    core._engine, core._db_path = old, old_path
    try:
        command.upgrade(config, "head")
        assert schema_of(old) == schema_of(fresh)
    finally:
        old.dispose()


@pytest.mark.parametrize("release", [release.revision for release in wireloft.RELEASES if release.revision != "0001"])
def test_a_wireloft_database_is_refused_with_a_pointer_to_the_importer(vodloft_database, release):
    from backend.db.migrations import WireLoftDatabaseError, upgrade_database

    path, _engine = vodloft_database
    wireloft.create(path, target=release)

    with pytest.raises(WireLoftDatabaseError, match="Settings > Import > WireLoft"):
        upgrade_database()


def test_a_wireloft_config_folder_mounted_as_vodloft_s_is_refused(vodloft_database):
    from backend.db.migrations import WireLoftDatabaseError, upgrade_database

    path, _engine = vodloft_database
    wireloft.create(path.with_name("wireloft.db"))

    with pytest.raises(WireLoftDatabaseError, match="wireloft.db"):
        upgrade_database()
    assert not path.exists()
