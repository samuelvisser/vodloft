from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


HEAD_REVISION = "d0f28c7f863e"
VODLOFT_0_5_0_REVISION = "817515eb8209"
VODLOFT_0_4_0_REVISION = "e6a2c9d4f817"
VODLOFT_NEEDS_SUBSCRIPTION_REVISION = "c41e7a9d3f58"
VODLOFT_REMOVED_FROM_SOURCE_REVISION = "a7e4c2d91b35"
VODLOFT_STORED_NAMES_REVISION = "f4abb559e3ab"
VODLOFT_SOURCE_IDENTITY_REVISION = "65b6125a39bb"
VODLOFT_SCHEMA_NAMES_REVISION = "a23bae59a781"
VODLOFT_UNIFIED_DOWNLOAD_PROFILES_REVISION = "72dc6dfbcb05"
VODLOFT_SOURCE_DOMAINS_REVISION = "f7b2d4e6a913"
VODLOFT_DRM_REVISION = "e3c9a7b5d214"
VODLOFT_VIDEOS_REVISION = "b5d2e8a4c716"
VODLOFT_SOURCES_REVISION = "a3e7c1d9f052"
BASELINE_REVISION = "a4e7c19b2d53"


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


def test_migration_history_has_one_head(migration_database):
    _database_path, _engine = migration_database
    from backend.db.migrations import get_alembic_config

    script = ScriptDirectory.from_config(get_alembic_config())

    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(HEAD_REVISION).down_revision == VODLOFT_0_5_0_REVISION
    assert script.get_revision(VODLOFT_0_5_0_REVISION).down_revision == VODLOFT_0_4_0_REVISION
    assert script.get_revision(VODLOFT_0_4_0_REVISION).down_revision == VODLOFT_NEEDS_SUBSCRIPTION_REVISION
    assert script.get_revision(VODLOFT_NEEDS_SUBSCRIPTION_REVISION).down_revision == VODLOFT_REMOVED_FROM_SOURCE_REVISION
    assert script.get_revision(VODLOFT_REMOVED_FROM_SOURCE_REVISION).down_revision == VODLOFT_STORED_NAMES_REVISION
    assert script.get_revision(VODLOFT_STORED_NAMES_REVISION).down_revision == VODLOFT_SOURCE_IDENTITY_REVISION
    assert script.get_revision(VODLOFT_SOURCE_IDENTITY_REVISION).down_revision == VODLOFT_SCHEMA_NAMES_REVISION
    assert script.get_revision(VODLOFT_SCHEMA_NAMES_REVISION).down_revision == VODLOFT_UNIFIED_DOWNLOAD_PROFILES_REVISION
    assert script.get_revision(VODLOFT_UNIFIED_DOWNLOAD_PROFILES_REVISION).down_revision == VODLOFT_SOURCE_DOMAINS_REVISION
    assert script.get_revision(VODLOFT_SOURCE_DOMAINS_REVISION).down_revision == VODLOFT_DRM_REVISION
    assert script.get_revision(VODLOFT_DRM_REVISION).down_revision == VODLOFT_VIDEOS_REVISION
    assert script.get_revision(VODLOFT_VIDEOS_REVISION).down_revision == VODLOFT_SOURCES_REVISION
    assert script.get_revision(VODLOFT_SOURCES_REVISION).down_revision == BASELINE_REVISION
    assert script.get_revision(BASELINE_REVISION).down_revision is None



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

        profiles = connection.execute(text(
            "SELECT type, slug, output_template, preferred_format "
            "FROM local_media_profiles ORDER BY slug"
        )).mappings().all()
        assert [profile["slug"] for profile in profiles] == [
            "vodloft-collections-audio",
            "vodloft-collections-video",
            "vodloft-movies",
            "vodloft-videos",
        ]
        assert {profile["type"] for profile in profiles} == {"movie", "collection", "video"}
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_collection"
        )).scalar_one() == 2
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
        )).scalar_one() == 4


def test_existing_database_upgrade_does_not_run_initial_seed(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import upgrade_database

    from backend.db.migrations import get_alembic_config

    command.upgrade(get_alembic_config(), VODLOFT_SOURCES_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 0

    upgrade_database()

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 0


def test_sources_migration_marks_existing_rows_as_daily_wire(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, BASELINE_REVISION)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO media_items (uuid, type) VALUES ('existing', 'movie')"))

    command.upgrade(config, VODLOFT_0_4_0_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT source_key FROM media_items")).scalar_one() == "dailywire"
    inspector = inspect(engine)
    for table in ("shows", "media_items"):
        assert "source_key" in {column["name"] for column in inspector.get_columns(table)}

    command.downgrade(config, BASELINE_REVISION)
    inspector = inspect(engine)
    for table in ("shows", "media_items"):
        assert "source_key" not in {column["name"] for column in inspector.get_columns(table)}


def test_source_identity_migration_moves_source_slugs_into_their_column(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_SCHEMA_NAMES_REVISION)
    with engine.begin() as connection:
        show_id = connection.execute(text(
            "INSERT INTO shows (uuid, source_key, slug, title, sharing_url, membership_level, type, "
            "episode_identifier, author_name, author_slug) VALUES "
            "('show', 'ytdlp', 'show', 'Show', 'https://example.test/show', 'FREE', 'podcast', 'numbered', 'A', 'a')"
        )).lastrowid
        season_id = connection.execute(text(
            "INSERT INTO seasons (show_id, \"index\", slug, name) VALUES (:show_id, 1, 's1', 's1')"
        ), {"show_id": show_id}).lastrowid

        def episode(index: int, slug: str) -> int:
            episode_id = connection.execute(text(
                "INSERT INTO media_items (uuid, source_key, type) VALUES (:slug, 'ytdlp', 'episode')"
            ), {"slug": slug}).lastrowid
            connection.execute(text(
                "INSERT INTO media_items_episode (id, show_id, season_id, \"index\", episode_identifier, slug, "
                "publish_status, sharing_url, title, duration) VALUES "
                "(:id, :show_id, :season_id, :index, :identifier, :slug, 'published_final', :url, :slug, 0)"
            ), {
                "id": episode_id, "show_id": show_id, "season_id": season_id, "index": index,
                "identifier": f"ep.{index}", "slug": slug, "url": f"https://example.test/{slug}",
            })
            return episode_id

        plain = episode(1, "abc")
        prefixed = episode(2, "show-def")
        connection.execute(text(
            "INSERT INTO metadata (parent_table, parent_id, key, value) "
            "VALUES ('media_items_episode', :id, 'source.slug', 'def')"
        ), {"id": prefixed})

    command.upgrade(config, VODLOFT_0_4_0_REVISION)
    with engine.connect() as connection:
        slugs = dict(connection.execute(text("SELECT id, source_slug FROM media_items_episode")).all())
        assert slugs == {plain: "abc", prefixed: "def"}
        assert connection.execute(text("SELECT count(*) FROM metadata")).scalar_one() == 0

    command.downgrade(config, VODLOFT_SCHEMA_NAMES_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT parent_id, value FROM metadata WHERE key = 'source.slug'"
        )).all() == [(prefixed, "def")]
    inspector = inspect(engine)
    assert "source_slug" not in {column["name"] for column in inspector.get_columns("media_items_episode")}


def test_stored_names_migration_renames_wireloft_values(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_SOURCE_IDENTITY_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO shows (uuid, source_key, slug, title, sharing_url, membership_level, type, "
            "episode_identifier, author_name, author_slug) VALUES "
            "('show', 'dailywire', 'show', 'Show', 'https://example.test/show', 'WL_ANY', 'podcast', 'numbered', 'A', 'a')"
        ))
        connection.execute(text(
            "INSERT INTO metadata (parent_table, parent_id, key, value) VALUES "
            "('media_items_episode', 1, 'ep_status.last_known_pending', 'wireloft:last_known_pending:2026-01-01T00:00:00+00:00'), "
            "('media_items_episode', 1, 'ep_status.recorded_published_final', "
            "'wireloft:recorded_published_final:2026-01-02T00:00:00+00:00'), "
            "('media_items_episode', 1, 'ep_status.trusted_live_ended', 'monitor:live_ended:2026-01-03T00:00:00+00:00')"
        ))

    def stored() -> tuple[str, list[str]]:
        with engine.connect() as connection:
            return (
                connection.execute(text("SELECT membership_level FROM shows")).scalar_one(),
                list(connection.execute(text("SELECT value FROM metadata ORDER BY id")).scalars()),
            )

    command.upgrade(config, VODLOFT_0_4_0_REVISION)
    assert stored() == ("HIGHEST_ALLOWED", [
        "vodloft:last_known_pending:2026-01-01T00:00:00+00:00",
        "vodloft:recorded_published_final:2026-01-02T00:00:00+00:00",
        "monitor:live_ended:2026-01-03T00:00:00+00:00",
    ])

    command.downgrade(config, VODLOFT_SOURCE_IDENTITY_REVISION)
    assert stored() == ("WL_ANY", [
        "wireloft:last_known_pending:2026-01-01T00:00:00+00:00",
        "wireloft:recorded_published_final:2026-01-02T00:00:00+00:00",
        "monitor:live_ended:2026-01-03T00:00:00+00:00",
    ])


def test_unified_download_profiles_migration_keeps_every_profile_setting(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_SOURCE_DOMAINS_REVISION)
    with engine.begin() as connection:
        local_media_profile_id = connection.execute(text(
            "INSERT INTO local_media_profiles (slug, name, output_template, preferred_format) "
            "VALUES ('shows', 'Shows', '/downloads/{{ show_title }}.ext', 'format_1080p')"
        )).lastrowid

        def show(slug: str, show_type: str, episode_identifier: str) -> int:
            return connection.execute(text(
                "INSERT INTO shows (uuid, slug, title, sharing_url, membership_level, type, "
                "episode_identifier, author_name, author_slug) VALUES "
                "(:slug, :slug, :slug, :url, 'FREE', :type, :identifier, 'A', 'a')"
            ), {
                "slug": slug, "url": f"https://example.test/{slug}",
                "type": show_type, "identifier": episode_identifier,
            }).lastrowid

        def season(show_id: int, index: int) -> int:
            return connection.execute(text(
                "INSERT INTO seasons (show_id, \"index\", slug, name) VALUES (:show_id, :index, :slug, :slug)"
            ), {"show_id": show_id, "index": index, "slug": f"s{index}"}).lastrowid

        def profile(show_id: int, profile_type: str) -> int:
            return connection.execute(text(
                "INSERT INTO download_profiles (show_id, local_media_profile_id, type, enable_profile, ep_id_type_list) "
                "VALUES (:show_id, :lmp, :type, 1, '[\"ep\"]')"
            ), {"show_id": show_id, "lmp": local_media_profile_id, "type": profile_type}).lastrowid

        podcast_show = show("podcast", "podcast", "date_based")
        podcast_profile = profile(podcast_show, "podcast")
        connection.execute(text(
            "INSERT INTO download_profiles_podcast (id, download_with_countdown, redownload_final, "
            "download_days_in_past, download_episode_count, download_starting_from, delete_older_episodes) "
            "VALUES (:id, 1, 1, 30, 0, NULL, 0)"
        ), {"id": podcast_profile})

        seasonal_podcast_show = show("seasonal-podcast", "podcast", "seasonal")
        seasonal_podcast_seasons = {season(seasonal_podcast_show, 1), season(seasonal_podcast_show, 2)}
        seasonal_podcast_profile = profile(seasonal_podcast_show, "podcast")
        connection.execute(text(
            "INSERT INTO download_profiles_podcast (id, download_with_countdown, redownload_final, "
            "download_days_in_past, download_episode_count, download_starting_from, delete_older_episodes) "
            "VALUES (:id, 0, 0, 0, 5, NULL, 1)"
        ), {"id": seasonal_podcast_profile})

        series_show = show("series", "series", "seasonal")
        chosen_season = season(series_show, 1)
        season(series_show, 2)
        series_profile = profile(series_show, "series")
        connection.execute(text(
            "INSERT INTO download_profiles_series (id, include_upcoming_seasons) VALUES (:id, 0)"
        ), {"id": series_profile})
        connection.execute(text(
            "INSERT INTO download_profile_series_seasons (download_profiles_series_id, season_id) "
            "VALUES (:profile, :season)"
        ), {"profile": series_profile, "season": chosen_season})

        connection.execute(text(
            "INSERT INTO task_definitions (key, title) VALUES ('download_profile_worker', 'Download profiles')"
        ))
        connection.execute(text(
            "INSERT INTO task_schedules (definition_id, resource_id, resource_type, \"trigger\", trigger_args, active) "
            "VALUES (1, :id, 'DOWNLOAD_PROFILE_SERIES', 'interval', '{}', 1)"
        ), {"id": series_profile})

    command.upgrade(config, VODLOFT_0_4_0_REVISION)
    with engine.connect() as connection:
        rows = {
            row.id: row
            for row in connection.execute(text("SELECT * FROM download_profiles"))
        }
        assert (
            rows[podcast_profile].download_with_countdown,
            rows[podcast_profile].redownload_final,
            rows[podcast_profile].download_days_in_past,
            rows[podcast_profile].delete_older_episodes,
        ) == (1, 1, 30, 0)
        assert rows[seasonal_podcast_profile].download_episode_count == 5
        assert rows[series_profile].include_upcoming_seasons == 0
        assert rows[series_profile].download_days_in_past == 0

        def profile_seasons(profile_id: int) -> set[int]:
            return set(connection.execute(text(
                "SELECT season_id FROM download_profile_seasons WHERE download_profile_id = :id"
            ), {"id": profile_id}).scalars())

        assert profile_seasons(series_profile) == {chosen_season}
        assert profile_seasons(seasonal_podcast_profile) == seasonal_podcast_seasons
        assert profile_seasons(podcast_profile) == set()
        assert connection.execute(text(
            "SELECT resource_type FROM task_schedules"
        )).scalar_one() == "DOWNLOAD_PROFILE"

    tables = set(inspect(engine).get_table_names())
    assert {"download_profiles_podcast", "download_profiles_series", "download_profile_series_seasons"}.isdisjoint(tables)
    assert "type" not in {column["name"] for column in inspect(engine).get_columns("download_profiles")}

    command.downgrade(config, VODLOFT_SOURCE_DOMAINS_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT type FROM download_profiles WHERE id = :id"
        ), {"id": series_profile}).scalar_one() == "series"
        assert connection.execute(text(
            "SELECT download_days_in_past FROM download_profiles_podcast WHERE id = :id"
        ), {"id": podcast_profile}).scalar_one() == 30
        assert connection.execute(text(
            "SELECT season_id FROM download_profile_series_seasons WHERE download_profiles_series_id = :id"
        ), {"id": series_profile}).scalar_one() == chosen_season


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
