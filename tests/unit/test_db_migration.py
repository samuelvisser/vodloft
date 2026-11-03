from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


# One migration per VODLoft release, oldest first. Each keeps the revision a
# released version stored, so databases from any release upgrade from there.
RELEASE_REVISIONS = (
    ("0.1.0", "f4abb559e3ab"),
    ("0.2.0", "a7e4c2d91b35"),
    ("0.3.0", "c41e7a9d3f58"),
    ("0.4.0", "e6a2c9d4f817"),
    ("0.5.0", "817515eb8209"),
    ("0.6.0", "d0f28c7f863e"),
)
VODLOFT_0_1_0_REVISION = "f4abb559e3ab"
VODLOFT_0_5_0_REVISION = "817515eb8209"
HEAD_REVISION = "c5e9a2f17b30"


@pytest.fixture
def migration_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the shared DB layer at a disposable SQLite file."""
    from backend.db import core

    database_path = tmp_path / "migration-test.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", session_factory)
    monkeypatch.setattr(core, "_db_path", database_path)

    yield database_path, engine
    engine.dispose()


def test_migration_history_has_one_migration_per_release(migration_database):
    _database_path, _engine = migration_database
    from backend.db.migrations import get_alembic_config

    script = ScriptDirectory.from_config(get_alembic_config())

    assert script.get_heads() == [HEAD_REVISION]
    chain = [revision.revision for revision in script.walk_revisions()]
    assert chain[::-1][:len(RELEASE_REVISIONS)] == [revision for _release, revision in RELEASE_REVISIONS]
    assert script.get_revision(VODLOFT_0_1_0_REVISION).down_revision is None


def test_fresh_database_matches_the_models(migration_database):
    _database_path, _engine = migration_database
    from backend.db.migrations import check_database, upgrade_database

    upgrade_database()

    check_database()


def test_demo_seed_runs_on_a_fresh_database(migration_database):
    _database_path, engine = migration_database
    from backend.db import seed_db
    from backend.db.migrations import upgrade_database

    upgrade_database()
    seed_db()
    seed_db()

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM collections")).scalar_one() == 3
        assert connection.execute(text("SELECT count(*) FROM media_items_episode")).scalar_one() == 57


def test_fresh_database_upgrades_to_the_head(migration_database):
    database_path, engine = migration_database
    from backend.db.background_migrations import get_background_migration_head_revision
    from backend.db.migrations import get_database_status, upgrade_database

    assert not database_path.exists()
    upgrade_database()

    current, head = get_database_status()
    assert current == (HEAD_REVISION,)
    assert head == HEAD_REVISION

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "task_operations" in tables
    assert "movie_extra_sources" in tables
    assert "custom_index_states" in tables
    assert {"requested_generation", "completed_generation"} <= {
        column["name"] for column in inspector.get_columns("custom_index_states")
    }
    assert "media_download_attempts" not in tables
    assert "media_download_history" in tables
    assert "alembic_version" not in tables

    settings_columns = {
        column["name"] for column in inspector.get_columns("settings")
    }
    assert "background_migration_version" in settings_columns

    media_download_columns = {
        column["name"] for column in inspector.get_columns("media_downloads")
    }
    assert "first_successful_download_at" not in media_download_columns

    profile_columns = {
        column["name"] for column in inspector.get_columns("local_media_profiles")
    }
    assert "download_mode" in profile_columns
    profile_indexes = {index["name"] for index in inspector.get_indexes("local_media_profiles")}
    assert "uq_local_media_profiles_type_output_template_preferred_format" in profile_indexes
    assert "uq_local_media_profiles_type_template_format_mode" not in profile_indexes

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT alembic_version_num FROM settings"
        )).scalar_one() == HEAD_REVISION
        assert connection.execute(text(
            "SELECT onboarding_completed FROM settings"
        )).scalar_one() == 0
        # A new database has nothing for the background migrations to repair.
        assert connection.execute(text(
            "SELECT background_migration_version FROM settings"
        )).scalar_one() == get_background_migration_head_revision()

        profiles = connection.execute(text(
            "SELECT type, slug, output_template, preferred_format "
            "FROM local_media_profiles ORDER BY slug"
        )).mappings().all()
        # The Collection profiles are only for a fresh start: onboarding adds them.
        assert [profile["slug"] for profile in profiles] == ["vodloft-movies", "vodloft-videos"]
        assert {profile["type"] for profile in profiles} == {"movie", "video"}
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_collection"
        )).scalar_one() == 0
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_movie"
        )).scalar_one() == 1
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_video"
        )).scalar_one() == 1

    from backend.db.initial_seed import seed_initial_database

    seed_initial_database()
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 2


def test_existing_database_upgrade_does_not_run_initial_seed(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import upgrade_database

    from backend.db.migrations import get_alembic_config

    command.upgrade(get_alembic_config(), VODLOFT_0_1_0_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 0

    upgrade_database()

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 0
        # An existing database still runs its background migrations.
        assert connection.execute(text(
            "SELECT background_migration_version FROM settings"
        )).scalar_one() is None


def test_collections_migration_renames_shows_and_their_stored_values(migration_database):
    _database_path, engine = migration_database
    import json

    from backend.db.migrations import downgrade_database, get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_5_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO shows (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'uuid-1', 'a-show', 'A Show', 'https://example.test/a', "
            "'free', 'series', 'numbered', 'Author', 'author', 'ytdlp')"
        ))
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type) VALUES "
            "(5, 'vodloft-shows-video', 'VODLoft Shows (Video)', "
            "'/downloads/{{ show }}/{{ meta_show_year }} {{ show_title | upper }} {{ showtime }}.ext', "
            "'format_1080p', 'show')"
        ))
        connection.execute(text("INSERT INTO local_media_profiles_show (id, show_scope) VALUES (5, 'podcast')"))
        connection.execute(text(
            "INSERT INTO metadata (parent_table, parent_id, key, value) VALUES ('shows', 1, 'custom.year', '2024')"
        ))
        connection.execute(text(
            "INSERT INTO task_definitions (id, key, title, allowed_resource_types, default_max_retries) "
            "VALUES (9, 'reconcile_show_assets', 'Reconcile', :allowed, 0)"
        ), {"allowed": json.dumps(["show", "download_profile"])})
        connection.execute(text(
            "INSERT INTO task_runs (id, definition_id, resource_type, resource_id, status, attempt_count, "
            "max_retries, meta) VALUES (1, 9, 'SHOW', 1, 'QUEUED', 0, 0, :meta)"
        ), {"meta": json.dumps({"show_id": 1, "no_show_today": True, "resource_type": "show"})})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        profile = connection.execute(text(
            "SELECT type, slug, name, output_template FROM local_media_profiles WHERE id = 5"
        )).mappings().one()
        assert dict(profile) == {
            "type": "collection",
            "slug": "vodloft-collections-video",
            "name": "VODLoft Collections (Video)",
            "output_template": (
                "/downloads/{{ collection }}/{{ meta_collection_year }} "
                "{{ collection_title | upper }} {{ showtime }}.ext"
            ),
        }
        assert connection.execute(text(
            "SELECT collection_scope FROM local_media_profiles_collection WHERE id = 5"
        )).scalar_one() == "podcast"
        assert connection.execute(text("SELECT title FROM collections")).scalar_one() == "A Show"
        assert connection.execute(text("SELECT parent_table FROM metadata")).scalar_one() == "collections"
        assert connection.execute(text(
            "SELECT key FROM task_definitions WHERE id = 9"
        )).scalar_one() == "reconcile_collection_assets"
        assert json.loads(connection.execute(text(
            "SELECT allowed_resource_types FROM task_definitions WHERE id = 9"
        )).scalar_one()) == ["collection", "download_profile"]
        run = connection.execute(text("SELECT resource_type, meta FROM task_runs")).one()
        assert run.resource_type == "COLLECTION"
        assert json.loads(run.meta) == {"collection_id": 1, "no_show_today": True, "resource_type": "collection"}

    downgrade_database(VODLOFT_0_5_0_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT title FROM shows")).scalar_one() == "A Show"
        assert connection.execute(text(
            "SELECT output_template FROM local_media_profiles WHERE id = 5"
        )).scalar_one() == "/downloads/{{ show }}/{{ meta_show_year }} {{ show_title | upper }} {{ showtime }}.ext"
        assert connection.execute(text("SELECT resource_type FROM task_runs")).scalar_one() == "SHOW"


def test_download_profiles_without_episode_types_stop_downloading(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, "b5e1c0a7d392")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'uuid-1', 'a', 'A', 'https://example.test/a', "
            "'free', 'series', 'numbered', 'Author', 'author', 'ytdlp')"
        ))
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type, video_codecs) VALUES "
            "(5, 'p', 'P', '/downloads/{{ collection }}/{{ episode_title }}.ext', 'format_1080p', 'collection', '[]')"
        ))
        for profile_id, types in ((1, "[]"), (2, '["ep"]')):
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "download_with_countdown, redownload_final, download_days_in_past, download_episode_count, "
                "delete_older_episodes, include_upcoming_seasons, sponsorblock_segments) "
                "VALUES (:id, 1, 5, 1, :types, 0, 0, 0, 0, 0, 1, '{}')"
            ), {"id": profile_id, "types": types})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        enabled = dict(connection.execute(text("SELECT id, enable_profile FROM download_profiles")).all())
    # An empty list used to download nothing; now it would mean every type.
    assert enabled == {1: 0, 2: 1}


def test_ytdlp_options_move_from_local_media_profiles_to_the_source(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, "e2f7a41c9d05")
    with engine.begin() as connection:
        for profile_id, options in ((5, "-N 4"), (6, ""), (7, "-N 4"), (8, "--xattrs")):
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type, video_codecs, "
                "ytdlp_options) VALUES (:id, :slug, :slug, '/downloads/{{ collection }}/' || :slug || '/{{ episode_title }}.ext', "
                "'format_1080p', 'collection', '[]', :options)"
            ), {"id": profile_id, "slug": f"p{profile_id}", "options": options})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT ytdlp_options FROM settings")).scalar_one() == "-N 4\n--xattrs"
    assert "ytdlp_options" not in {column["name"] for column in inspect(engine).get_columns("local_media_profiles")}
