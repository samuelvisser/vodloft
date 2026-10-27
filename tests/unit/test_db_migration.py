from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


HEAD_REVISION = "a7e4c2d91b35"
VODLOFT_STORED_NAMES_REVISION = "f4abb559e3ab"
VODLOFT_SOURCE_IDENTITY_REVISION = "65b6125a39bb"
VODLOFT_SCHEMA_NAMES_REVISION = "a23bae59a781"
VODLOFT_UNIFIED_DOWNLOAD_PROFILES_REVISION = "72dc6dfbcb05"
VODLOFT_SOURCE_DOMAINS_REVISION = "f7b2d4e6a913"
VODLOFT_DRM_REVISION = "e3c9a7b5d214"
VODLOFT_VIDEOS_REVISION = "b5d2e8a4c716"
VODLOFT_SOURCES_REVISION = "a3e7c1d9f052"
WIRELOFT_1_2_3_REVISION = "a4e7c19b2d53"
WIRELOFT_1_2_1_REVISION = "f2a6c93d8b14"
WIRELOFT_1_2_REVISION = "6d4a8c1f2b90"
WIRELOFT_1_0_REVISION = "c8d4e2f1a7b9"
BASE_REVISION = "0001"


@pytest.fixture
def migration_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the shared DB layer at a disposable SQLite file."""
    from backend.db import core

    database_path = tmp_path / "wireloft-migration-test.db"
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


def _upgrade_to_wireloft_1_0(engine) -> None:
    from backend.db.migrations import get_alembic_config

    command.upgrade(
        get_alembic_config(allow_version_storage_migration=True),
        WIRELOFT_1_0_REVISION,
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == WIRELOFT_1_0_REVISION


def _seed_wireloft_1_0_data(database_path: Path, engine) -> dict[str, int | str]:
    artifact_path = database_path.parent / "published-episode.mp4"
    artifact_path.write_bytes(b"wireloft-1.0-artifact")

    with engine.begin() as connection:
        profile_id = connection.execute(text(
            "SELECT id FROM local_media_profiles "
            "WHERE slug = 'vodloft-shows-video'"
        )).scalar_one_or_none()
        if profile_id is None:
            profile_id = connection.execute(text(
                "INSERT INTO local_media_profiles "
                "(type, slug, name, output_template, preferred_format, "
                "append_media_type_to_filename) VALUES "
                "('show', 'vodloft-shows-video', 'VODLoft Shows (Video)', "
                "'/downloads/shows/{{ show_title }}/{{ season_name }}/{{ episode_title }}.ext', "
                "'format_1080p', 0)"
            )).lastrowid
            connection.execute(text(
                "INSERT INTO local_media_profiles_show (id) VALUES (:profile_id)"
            ), {"profile_id": profile_id})

        show_id = connection.execute(text(
            "INSERT INTO shows "
            "(uuid, slug, title, description, sharing_url, membership_level, type, "
            "episode_identifier, author_name, author_slug) VALUES "
            "('release-show-uuid', 'release-show', 'Release Show', 'Description', "
            "'https://www.dailywire.com/show/release-show', 'FREE', 'series', 'seasonal', "
            "'Host', 'host')"
        )).lastrowid
        extra_season_id = connection.execute(text(
            "INSERT INTO seasons (show_id, `index`, slug, name) "
            "VALUES (:show_id, 1, 'extras', 'Extras')"
        ), {"show_id": show_id}).lastrowid
        season_id = connection.execute(text(
            "INSERT INTO seasons (show_id, `index`, slug, name) "
            "VALUES (:show_id, 2, 'season-1', 'Season 1')"
        ), {"show_id": show_id}).lastrowid
        for key, value in (
            ("ep_id.latest_ep_num", "1"),
            ("ep_id.latest_ep_extra_num", "1"),
            ("ep_id.latest_season_2_ep", "1"),
        ):
            connection.execute(
                text(
                    "INSERT INTO metadata (parent_table, parent_id, key, value) "
                    "VALUES ('shows', :show_id, :key, :value)"
                ),
                {"show_id": show_id, "key": key, "value": value},
            )

        episode_id = connection.execute(text(
            "INSERT INTO media_items "
            "(uuid, type, title, description, duration, background_image_path, "
            "thumbnail_landscape_path, thumbnail_portrait_path, thumbnail_square_path) "
            "VALUES ('release-episode-uuid', 'episode', 'Release Episode', "
            "'Episode description', 1800, NULL, 'episode-land.jpg', NULL, NULL)"
        )).lastrowid
        connection.execute(text(
            "INSERT INTO episodes "
            "(id, show_id, season_id, `index`, episode_identifier, slug, publish_status, "
            "video_url, audio_url, sharing_url, published_date, metadata_is_final) "
            "VALUES (:id, :show_id, :season_id, 1, 'ep.S02E01', 'release-episode', "
            "'published', 'https://video.test/master.m3u8', NULL, "
            "'https://example.test/release-episode', '2026-09-01 12:00:00', 1)"
        ), {
            "id": episode_id,
            "show_id": show_id,
            "season_id": season_id,
        })
        connection.execute(text(
            "INSERT INTO metadata (parent_table, parent_id, key, value) "
            "VALUES ('episodes', :episode_id, 'dw_processing.reason', 'release-test')"
        ), {"episode_id": episode_id})

        trailer_episode_id = connection.execute(text(
            "INSERT INTO media_items "
            "(uuid, type, title, description, duration, background_image_path, "
            "thumbnail_landscape_path, thumbnail_portrait_path, thumbnail_square_path) "
            "VALUES ('release-trailer-episode-uuid', 'episode', "
            "'Release Show | Official Trailer', 'Trailer description', 90, NULL, "
            "'trailer-episode-land.jpg', NULL, NULL)"
        )).lastrowid
        connection.execute(text(
            "INSERT INTO episodes "
            "(id, show_id, season_id, `index`, episode_identifier, slug, publish_status, "
            "video_url, audio_url, sharing_url, published_date, metadata_is_final) "
            "VALUES (:id, :show_id, :season_id, 2, 'aux.1', 'release-show-trailer', "
            "'published', 'https://video.test/trailer.m3u8', NULL, "
            "'https://example.test/release-show-trailer', "
            "'2026-08-31 12:00:00', 1)"
        ), {
            "id": trailer_episode_id,
            "show_id": show_id,
            "season_id": extra_season_id,
        })

        download_id = connection.execute(text(
            "INSERT INTO media_downloads "
            "(type, media_item_id, local_media_profile_id, download_status, file_path, "
            "progress, error_message, downloaded_bytes, format_downloaded, started_at, "
            "finished_at, attempt_generation) VALUES "
            "('episode', :episode_id, :profile_id, 'downloaded', :file_path, 100, NULL, "
            ":downloaded_bytes, '1920x1080', '2026-09-01 12:00:00', "
            "'2026-09-01 12:30:00', 1)"
        ), {
            "episode_id": episode_id,
            "profile_id": profile_id,
            "file_path": str(artifact_path),
            "downloaded_bytes": artifact_path.stat().st_size,
        }).lastrowid
        connection.execute(text(
            "INSERT INTO media_downloads_episode "
            "(id, download_profile_id, downloaded_publish_status, is_redownload_attempt) "
            "VALUES (:id, NULL, 'published', 0)"
        ), {"id": download_id})
        connection.execute(text(
            "INSERT INTO media_download_attempts "
            "(media_download_id, is_redownload, status, downloaded_bytes, "
            "format_downloaded, started_at, finished_at) VALUES "
            "(:download_id, 0, 'downloaded', :downloaded_bytes, '1920x1080', "
            "'2026-09-01 12:00:00', '2026-09-01 12:30:00')"
        ), {
            "download_id": download_id,
            "downloaded_bytes": artifact_path.stat().st_size,
        })

        task_definition_id = connection.execute(text(
            "INSERT INTO task_definitions "
            "(key, title, description, allowed_resource_types, default_max_retries) "
            "VALUES ('monitor_episode_worker', 'Legacy monitor', NULL, '[\"episode\"]', 3)"
        )).lastrowid

        movie_id = connection.execute(text(
            "INSERT INTO media_items "
            "(uuid, type, title, description, duration, background_image_path, "
            "thumbnail_landscape_path, thumbnail_portrait_path, thumbnail_square_path) "
            "VALUES ('release-movie-uuid', 'movie', 'Release Movie', 'Movie description', "
            "5400, NULL, 'movie-land.jpg', 'movie-port.jpg', 'movie-square.jpg')"
        )).lastrowid
        connection.execute(text(
            "INSERT INTO movies "
            "(id, slug, dw_id, sharing_url, is_downloadable, available_for, "
            "release_date_lookup_status) VALUES "
            "(:id, 'release-movie', 'rotating-movie-id', "
            "'https://example.test/release-movie', 1, '[\"ALL_ACCESS\"]', 'pending')"
        ), {"id": movie_id})

        movie_extra_id = connection.execute(text(
            "INSERT INTO media_items "
            "(uuid, type, title, description, duration, background_image_path, "
            "thumbnail_landscape_path, thumbnail_portrait_path, thumbnail_square_path) "
            "VALUES ('release-extra-uuid', 'movie_extra', 'Official Trailer', "
            "'Trailer description', 120, NULL, 'trailer-land.jpg', NULL, NULL)"
        )).lastrowid
        connection.execute(text(
            "INSERT INTO movie_extras "
            "(id, movie_id, movie_extra_type, dw_id, slug, sharing_url, published_date) "
            "VALUES (:id, :movie_id, 'trailer', 'rotating-extra-id', "
            "'release-movie-trailer', 'https://example.test/trailer', "
            "'2026-08-01 12:00:00')"
        ), {"id": movie_extra_id, "movie_id": movie_id})
        connection.execute(text(
            "UPDATE movies SET official_trailer_id = :extra_id WHERE id = :movie_id"
        ), {"extra_id": movie_extra_id, "movie_id": movie_id})

    return {
        "profile_id": int(profile_id),
        "show_id": int(show_id),
        "extra_season_id": int(extra_season_id),
        "season_id": int(season_id),
        "episode_id": int(episode_id),
        "trailer_episode_id": int(trailer_episode_id),
        "download_id": int(download_id),
        "task_definition_id": int(task_definition_id),
        "movie_id": int(movie_id),
        "movie_extra_id": int(movie_extra_id),
        "artifact_path": str(artifact_path),
    }


def test_migration_history_has_one_head(migration_database):
    _database_path, _engine = migration_database
    from backend.db.migrations import get_alembic_config

    script = ScriptDirectory.from_config(
        get_alembic_config(allow_version_storage_migration=True)
    )

    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(HEAD_REVISION).down_revision == VODLOFT_STORED_NAMES_REVISION
    assert script.get_revision(VODLOFT_STORED_NAMES_REVISION).down_revision == VODLOFT_SOURCE_IDENTITY_REVISION
    assert script.get_revision(VODLOFT_SOURCE_IDENTITY_REVISION).down_revision == VODLOFT_SCHEMA_NAMES_REVISION
    assert script.get_revision(VODLOFT_SCHEMA_NAMES_REVISION).down_revision == VODLOFT_UNIFIED_DOWNLOAD_PROFILES_REVISION
    assert script.get_revision(VODLOFT_UNIFIED_DOWNLOAD_PROFILES_REVISION).down_revision == VODLOFT_SOURCE_DOMAINS_REVISION
    assert script.get_revision(VODLOFT_SOURCE_DOMAINS_REVISION).down_revision == VODLOFT_DRM_REVISION
    assert script.get_revision(VODLOFT_DRM_REVISION).down_revision == VODLOFT_VIDEOS_REVISION
    assert script.get_revision(VODLOFT_VIDEOS_REVISION).down_revision == VODLOFT_SOURCES_REVISION
    assert script.get_revision(VODLOFT_SOURCES_REVISION).down_revision == WIRELOFT_1_2_3_REVISION
    assert script.get_revision(WIRELOFT_1_2_3_REVISION).down_revision == WIRELOFT_1_2_1_REVISION
    assert script.get_revision(WIRELOFT_1_2_1_REVISION).down_revision == WIRELOFT_1_2_REVISION
    assert (
        script.get_revision(WIRELOFT_1_2_REVISION).down_revision
        == "d8b4a1f6c203"
    )
    assert script.get_revision("d8b4a1f6c203").down_revision == WIRELOFT_1_0_REVISION
    assert script.get_revision(WIRELOFT_1_0_REVISION).down_revision == BASE_REVISION
    assert script.get_revision(BASE_REVISION) is not None



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
        assert connection.execute(text("SELECT count(*) FROM shows")).scalar_one() == 3
        assert connection.execute(text("SELECT count(*) FROM media_items_episode")).scalar_one() == 57


def test_countdown_redownload_intent_migration_uses_current_episode_table(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config, upgrade_database

    command.upgrade(
        get_alembic_config(allow_version_storage_migration=True),
        WIRELOFT_1_2_1_REVISION,
    )

    with engine.begin() as connection:
        show_id = connection.execute(text(
            "INSERT INTO shows "
            "(uuid, slug, title, description, sharing_url, membership_level, type, "
            "episode_identifier, author_name, author_slug) VALUES "
            "('countdown-migration-show', 'countdown-migration-show', 'Countdown Migration', "
            "NULL, 'https://example.test/countdown-migration-show', 'FREE', 'podcast', "
            "'numbered', 'Host', 'host')"
        )).lastrowid
        season_id = connection.execute(text(
            "INSERT INTO seasons (show_id, `index`, slug, name) "
            "VALUES (:show_id, 1, 'season-1', 'Season 1')"
        ), {"show_id": show_id}).lastrowid
        media_item_id = connection.execute(text(
            "INSERT INTO media_items (uuid, type) "
            "VALUES ('countdown-migration-episode', 'episode')"
        )).lastrowid
        connection.execute(text(
            "INSERT INTO media_items_episode "
            "(id, show_id, season_id, `index`, episode_identifier, slug, publish_status, "
            "sharing_url, title, duration, metadata_is_final) VALUES "
            "(:id, :show_id, :season_id, 1, 'ep.1', 'countdown-migration-episode', "
            "'published_with_countdown', 'https://example.test/countdown-migration-episode', "
            "'Countdown Episode', 1800, 1)"
        ), {
            "id": media_item_id,
            "show_id": show_id,
            "season_id": season_id,
        })

        local_profile_id = connection.execute(text(
            "INSERT INTO local_media_profiles "
            "(slug, name, output_template, preferred_format, type) VALUES "
            "('countdown-migration-audio', 'Countdown Migration Audio', "
            "'/downloads/{{ episode_title }}.ext', 'format_audio_only', 'show')"
        )).lastrowid
        connection.execute(text(
            "INSERT INTO local_media_profiles_show (id) VALUES (:id)"
        ), {"id": local_profile_id})

        download_profile_id = connection.execute(text(
            "INSERT INTO download_profiles "
            "(show_id, local_media_profile_id, type, enable_profile, ep_id_type_list) "
            "VALUES (:show_id, :local_profile_id, 'podcast', 1, '[\"ep\"]')"
        ), {
            "show_id": show_id,
            "local_profile_id": local_profile_id,
        }).lastrowid
        connection.execute(text(
            "INSERT INTO download_profiles_podcast "
            "(id, download_with_countdown, redownload_final, download_days_in_past, "
            "delete_older_episodes, download_episode_count) "
            "VALUES (:id, 1, 1, 0, 0, 0)"
        ), {"id": download_profile_id})

        media_download_id = connection.execute(text(
            "INSERT INTO media_downloads "
            "(type, media_item_id, local_media_profile_id, file_path, artifact_status) "
            "VALUES ('episode', :media_item_id, :local_profile_id, "
            "'/downloads/countdown.m4a', 'absent')"
        ), {
            "media_item_id": media_item_id,
            "local_profile_id": local_profile_id,
        }).lastrowid
        connection.execute(text(
            "INSERT INTO media_downloads_episode "
            "(id, download_profile_id, downloaded_publish_status) "
            "VALUES (:id, :download_profile_id, 'published_with_countdown')"
        ), {
            "id": media_download_id,
            "download_profile_id": download_profile_id,
        })

    upgrade_database()

    inspector = inspect(engine)
    assert {"redownload_when_final", "redownload_when_delay_passed"} <= {
        column["name"]
        for column in inspector.get_columns("media_downloads_episode")
    }
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT redownload_when_final FROM media_downloads_episode WHERE id = :id"
        ), {"id": media_download_id}).scalar_one() == 1
        assert connection.execute(text(
            "SELECT alembic_version_num FROM settings"
        )).scalar_one() == HEAD_REVISION



def test_fresh_database_upgrades_to_wireloft_1_1(migration_database):
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
            "vodloft-movies",
            "vodloft-shows-audio",
            "vodloft-shows-video",
            "vodloft-videos",
        ]
        assert {profile["type"] for profile in profiles} == {"movie", "show", "video"}
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_show"
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

    _upgrade_to_wireloft_1_0(engine)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 0

    upgrade_database()

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles"
        )).scalar_one() == 0


def test_upgrade_from_wireloft_1_0_preserves_release_data(migration_database):
    database_path, engine = migration_database
    from backend.db.migrations import upgrade_database

    _upgrade_to_wireloft_1_0(engine)
    seeded = _seed_wireloft_1_0_data(database_path, engine)
    upgrade_database()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "media_download_attempts" not in tables
    assert "task_operations" in tables
    assert "alembic_version" not in tables

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT alembic_version_num FROM settings"
        )).scalar_one() == HEAD_REVISION

        episode = connection.execute(text(
            "SELECT slug, title, metadata_is_final, dw_episode_number, episode_identifier "
            "FROM media_items_episode WHERE id = :id"
        ), {"id": seeded["episode_id"]}).mappings().one()
        assert episode["slug"] == "release-episode"
        assert episode["title"] == "Release Episode"
        assert bool(episode["metadata_is_final"])
        assert episode["dw_episode_number"] is None
        assert episode["episode_identifier"] == "ep.S01E01"

        trailer_episode = connection.execute(text(
            "SELECT title, episode_identifier FROM media_items_episode WHERE id = :id"
        ), {"id": seeded["trailer_episode_id"]}).mappings().one()
        assert trailer_episode["title"] == "Release Show | Official Trailer"
        assert trailer_episode["episode_identifier"] == "trailer.1"

        extra_season = connection.execute(text(
            "SELECT season_type, season_number FROM seasons WHERE id = :id"
        ), {"id": seeded["extra_season_id"]}).mappings().one()
        assert extra_season["season_type"] == "extra"
        assert extra_season["season_number"] == 0

        season = connection.execute(text(
            "SELECT season_type, season_number FROM seasons WHERE id = :id"
        ), {"id": seeded["season_id"]}).mappings().one()
        assert season["season_type"] == "normal"
        assert season["season_number"] == 1

        retired_counters = connection.execute(
            text(
                "SELECT key FROM metadata "
                "WHERE parent_table = 'shows' AND parent_id = :show_id "
                "AND (key = 'ep_id.latest_ep_num' "
                "OR key = 'ep_id.latest_ep_extra_num' "
                "OR key LIKE 'ep_id.latest_season_%_ep')"
            ),
            {"show_id": seeded["show_id"]},
        ).scalars().all()
        assert retired_counters == []

        assert connection.execute(text(
            "SELECT background_migration_version FROM settings"
        )).scalar_one() is None

        metadata = connection.execute(text(
            "SELECT parent_table, key, value FROM metadata "
            "WHERE parent_table = 'media_items_episode' AND parent_id = :id"
        ), {"id": seeded["episode_id"]}).mappings().one()
        assert metadata["parent_table"] == "media_items_episode"
        assert metadata["key"] == "no_usable_media.reason"
        assert metadata["value"] == "release-test"

        download = connection.execute(text(
            "SELECT artifact_status, artifact_error, artifact_size_bytes, "
            "artifact_fingerprint, downloaded_bytes, format_downloaded, file_path "
            "FROM media_downloads WHERE id = :id"
        ), {"id": seeded["download_id"]}).mappings().one()
        assert download["artifact_status"] == "available"
        assert download["artifact_error"] is None
        assert download["artifact_size_bytes"] == Path(str(seeded["artifact_path"])).stat().st_size
        assert len(download["artifact_fingerprint"]) == 64
        assert download["downloaded_bytes"] == Path(str(seeded["artifact_path"])).stat().st_size
        assert download["format_downloaded"] == "1920x1080"
        assert download["file_path"] == seeded["artifact_path"]

        assert connection.execute(text(
            "SELECT key FROM task_definitions WHERE id = :id"
        ), {"id": seeded["task_definition_id"]}).scalar_one() == "monitor_pending_episode"

        movie = connection.execute(text(
            "SELECT slug, title, is_downloadable, official_trailer_id "
            "FROM media_items_movie WHERE id = :id"
        ), {"id": seeded["movie_id"]}).mappings().one()
        assert movie["slug"] == "release-movie"
        assert movie["title"] == "Release Movie"
        assert bool(movie["is_downloadable"])
        assert movie["official_trailer_id"] == seeded["movie_extra_id"]

        extra = connection.execute(text(
            "SELECT placement.movie_extra_type, source.slug, source.title "
            "FROM media_items_movie_extra AS placement "
            "JOIN movie_extra_sources AS source ON source.id = placement.source_id "
            "WHERE placement.id = :id"
        ), {"id": seeded["movie_extra_id"]}).mappings().one()
        assert extra["movie_extra_type"] == "trailer"
        assert extra["slug"] == "release-movie-trailer"
        assert extra["title"] == "Official Trailer"

        profile = connection.execute(text(
            "SELECT download_mode FROM local_media_profiles WHERE id = :id"
        ), {"id": seeded["profile_id"]}).scalar_one()
        assert profile == "system"
        assert connection.execute(text(
            "SELECT show_scope FROM local_media_profiles_show WHERE id = :id"
        ), {"id": seeded["profile_id"]}).scalar_one() == "both"


def test_wireloft_1_1_downgrades_to_1_0_schema(migration_database):
    database_path, engine = migration_database
    from backend.db.migrations import downgrade_database, upgrade_database

    _upgrade_to_wireloft_1_0(engine)
    seeded = _seed_wireloft_1_0_data(database_path, engine)
    upgrade_database()
    downgrade_database(WIRELOFT_1_0_REVISION)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "task_operations" not in tables
    assert "media_download_attempts" in tables
    assert "episodes" in tables
    assert "movies" in tables
    assert "movie_extras" in tables
    assert "media_items_episode" not in tables

    assert "download_mode" not in {
        column["name"] for column in inspector.get_columns("local_media_profiles")
    }
    assert "timezone" in {
        column["name"] for column in inspector.get_columns("task_schedules")
    }
    assert "is_no_show_today" in {
        column["name"] for column in inspector.get_columns("episodes")
    }
    assert "artifact_status" not in {
        column["name"] for column in inspector.get_columns("media_downloads")
    }
    assert "download_status" in {
        column["name"] for column in inspector.get_columns("media_downloads")
    }
    assert "background_migration_version" not in {
        column["name"] for column in inspector.get_columns("settings")
    }
    assert "dw_episode_number" not in {
        column["name"] for column in inspector.get_columns("episodes")
    }
    assert "season_type" not in {
        column["name"] for column in inspector.get_columns("seasons")
    }
    assert "season_number" not in {
        column["name"] for column in inspector.get_columns("seasons")
    }

    with engine.connect() as connection:
        # The old attempt table is structurally restored, but its 1.0 history was
        # intentionally discarded during the upgrade.
        assert connection.execute(text(
            "SELECT COUNT(*) FROM media_download_attempts"
        )).scalar_one() == 0
        downgraded_episode = connection.execute(
            text("SELECT slug, episode_identifier FROM episodes WHERE id = :id"),
            {"id": seeded["episode_id"]},
        ).mappings().one()
        assert downgraded_episode["slug"] == "release-episode"
        assert downgraded_episode["episode_identifier"] == "ep.S02E01"
        assert connection.execute(text(
            "SELECT slug FROM movies WHERE id = :id"
        ), {"id": seeded["movie_id"]}).scalar_one() == "release-movie"
        assert connection.execute(text(
            "SELECT slug FROM movie_extras WHERE id = :id"
        ), {"id": seeded["movie_extra_id"]}).scalar_one() == "release-movie-trailer"
        assert connection.execute(text(
            "SELECT key FROM task_definitions WHERE id = :id"
        ), {"id": seeded["task_definition_id"]}).scalar_one() == "monitor_episode_worker"
        assert connection.execute(text(
            "SELECT alembic_version_num FROM settings"
        )).scalar_one() == WIRELOFT_1_0_REVISION


def test_sources_migration_marks_existing_rows_as_daily_wire(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config(allow_version_storage_migration=True)
    command.upgrade(config, WIRELOFT_1_2_3_REVISION)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO media_items (uuid, type) VALUES ('existing', 'movie')"))

    command.upgrade(config, HEAD_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT source_key FROM media_items")).scalar_one() == "dailywire"
    inspector = inspect(engine)
    for table in ("shows", "media_items"):
        assert "source_key" in {column["name"] for column in inspector.get_columns(table)}

    command.downgrade(config, WIRELOFT_1_2_3_REVISION)
    inspector = inspect(engine)
    for table in ("shows", "media_items"):
        assert "source_key" not in {column["name"] for column in inspector.get_columns(table)}


def test_source_identity_migration_moves_source_slugs_into_their_column(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config(allow_version_storage_migration=True)
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

    command.upgrade(config, HEAD_REVISION)
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

    config = get_alembic_config(allow_version_storage_migration=True)
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

    command.upgrade(config, HEAD_REVISION)
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

    config = get_alembic_config(allow_version_storage_migration=True)
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

    command.upgrade(config, HEAD_REVISION)
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
