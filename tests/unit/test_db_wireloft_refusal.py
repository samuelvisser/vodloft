"""VODLoft refuses a WireLoft database and points to the importer instead of upgrading it."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from importer.wireloft import migrations as wireloft


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
