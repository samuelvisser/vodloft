from __future__ import annotations

import json

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
    ("0.7.0", "c89f1a5ea2ba"),
    ("0.8.0", "bb0e7c5e17cc"),
    ("0.9.0", "2f7a91c4d8e3"),
    ("0.9.1", "5b8e2d4c9a17"),
    ("0.10.0", "4c7e19a2b6d0"),
)
VODLOFT_0_1_0_REVISION = "f4abb559e3ab"
VODLOFT_0_5_0_REVISION = "817515eb8209"
VODLOFT_0_6_0_REVISION = "d0f28c7f863e"
VODLOFT_0_7_0_REVISION = "c89f1a5ea2ba"
VODLOFT_0_8_0_REVISION = "bb0e7c5e17cc"
VODLOFT_0_9_0_REVISION = "2f7a91c4d8e3"
VODLOFT_0_9_1_REVISION = "5b8e2d4c9a17"
HEAD_REVISION = "917089ea3b82"


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
        assert {profile["type"] for profile in profiles} == {"video"}
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_collection"
        )).scalar_one() == 0
        assert connection.execute(text(
            "SELECT COUNT(*) FROM local_media_profiles_video"
        )).scalar_one() == 2
        # A new VODLoft has no Sites until onboarding asks which ones the user uses. The movies profile starts
        # without any, and takes each Site with movies the user adds.
        assert connection.execute(text("SELECT COUNT(*) FROM sites")).scalar_one() == 0
        assert connection.execute(text(
            "SELECT site_keys, include_upcoming_sites FROM local_media_profiles WHERE slug = 'vodloft-movies'"
        )).one() == ('[]', 1)

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
    command.upgrade(config, VODLOFT_0_6_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'uuid-1', 'a', 'A', 'https://example.test/a', "
            "'free', 'series', 'numbered', 'Author', 'author', 'ytdlp')"
        ))
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type) VALUES "
            "(5, 'p', 'P', '/downloads/{{ collection }}/{{ episode_title }}.ext', 'format_1080p', 'collection')"
        ))
        for profile_id, types in ((1, "[]"), (2, '["ep"]')):
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "download_with_countdown, redownload_final, download_days_in_past, download_episode_count, "
                "delete_older_episodes, include_upcoming_seasons) "
                "VALUES (:id, 1, 5, 1, :types, 0, 0, 0, 0, 0, 1)"
            ), {"id": profile_id, "types": types})

    command.upgrade(config, VODLOFT_0_7_0_REVISION)

    with engine.connect() as connection:
        enabled = dict(connection.execute(text("SELECT id, enable_profile FROM download_profiles")).all())
    # An empty list used to download nothing; now it would mean every type.
    assert enabled == {1: 0, 2: 1}


def test_imported_seasons_get_their_slug_back_and_the_duplicate_is_merged(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_6_0_REVISION)
    with engine.begin() as connection:
        for collection_id in (1, 2, 3, 4):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :slug, :slug, 'https://example.test/' || :slug, "
                "'free', 'series', 'seasonal', 'Author', 'author', 'dailywire')"
            ), {"id": collection_id, "uuid": f"uuid-{collection_id}", "slug": f"show-{collection_id}"})
        seasons = (
            # (id, collection, index, slug, imported)
            (1, 1, 1, "extras", True),
            (2, 2, 1, "extras-2", True),
            (3, 3, 1, "extras-3", True),
            (4, 3, 2, "show-3-season-1", True),
            (5, 3, 3, "extras", False),  # Added again by indexing.
            (6, 4, 1, "season-2", True),  # The Source's own slug: no season elsewhere is called "season".
        )
        for season_id, collection_id, index, slug, imported in seasons:
            connection.execute(text(
                "INSERT INTO seasons (id, collection_id, \"index\", slug, name, season_type, season_number) "
                "VALUES (:id, :collection, :index, :slug, :name, 'extra', 0)"
            ), {"id": season_id, "collection": collection_id, "index": index, "slug": slug,
                "name": "Extras" if slug.startswith("extras") else slug})
            if imported:
                connection.execute(text(
                    "INSERT INTO import_links (importer, kind, external_id, entity_id, written, unsupported) "
                    "VALUES ('wireloft', 'season', :id, :id, '{}', '[]')"
                ), {"id": season_id})
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type) VALUES "
            "(5, 'p', 'P', '/downloads/{{ collection }}/{{ episode_title }}.ext', 'format_1080p', 'collection')"
        ))
        for profile_id in (1, 2):
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "download_with_countdown, redownload_final, download_days_in_past, download_episode_count, "
                "delete_older_episodes, include_upcoming_seasons) "
                "VALUES (:id, 3, 5, 1, '[]', 0, 0, 0, 0, 0, 1)"
            ), {"id": profile_id})
        # Profile 1 had the imported season and got the duplicate as an upcoming season; profile 2 only the duplicate.
        for profile_id, season_id in ((1, 3), (1, 5), (2, 5)):
            connection.execute(text(
                "INSERT INTO download_profile_seasons (download_profile_id, season_id) VALUES (:profile, :season)"
            ), {"profile": profile_id, "season": season_id})
        for episode_id, season_id in ((10, 3), (11, 5)):
            connection.execute(text(
                "INSERT INTO media_items (id, uuid, type, source_key) VALUES (:id, :uuid, 'episode', 'dailywire')"
            ), {"id": episode_id, "uuid": f"episode-{episode_id}"})
            connection.execute(text(
                "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, slug, "
                "publish_status, sharing_url, source_slug) VALUES (:id, 3, :season, :id, :identifier, :slug, "
                "'published_final', 'https://example.test', :slug)"
            ), {"id": episode_id, "season": season_id, "identifier": f"trailer.{episode_id}", "slug": f"e{episode_id}"})

    command.upgrade(config, VODLOFT_0_7_0_REVISION)

    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT id, slug FROM seasons")).all()) == {
            1: "extras", 2: "extras", 3: "extras", 4: "show-3-season-1", 6: "season-2",
        }
        assert dict(connection.execute(text("SELECT id, season_id FROM media_items_episode")).all()) == {10: 3, 11: 3}
        assert sorted(connection.execute(text(
            "SELECT download_profile_id, season_id FROM download_profile_seasons"
        )).all()) == [(1, 3), (2, 3)]


def test_0_7_0_migration_keeps_what_existing_profiles_and_episodes_did(migration_database):
    _database_path, engine = migration_database
    import json

    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_6_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'uuid-1', 'a', 'A', 'https://example.test/a', "
            "'free', 'series', 'numbered', 'The Host', 'host', 'dailywire')"
        ))
        connection.execute(text(
            "INSERT INTO seasons (id, collection_id, \"index\", slug, name, season_type, season_number) "
            "VALUES (1, 1, 1, 'season-1', 'Season 1', 'season', 1)"
        ))
        connection.execute(text(
            "INSERT INTO media_items (id, uuid, type, source_key) VALUES (10, 'episode-10', 'episode', 'dailywire')"
        ))
        connection.execute(text(
            "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, slug, "
            "publish_status, sharing_url, source_slug) VALUES (10, 1, 1, 1, 'ep.1', 'e10', "
            "'published_final', 'https://example.test', 'e10')"
        ))
        for profile_id, preferred_format in ((5, "format_1080p"), (6, "format_4k")):
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type) VALUES "
                "(:id, :slug, :slug, '/downloads/{{ collection }}/' || :slug || '/{{ episode_title }}.ext', "
                ":format, 'collection')"
            ), {"id": profile_id, "slug": f"p{profile_id}", "format": preferred_format})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT author_name FROM media_items_episode")).scalar_one() == "The Host"
        profiles = {
            row.id: row for row in connection.execute(text(
                "SELECT id, subtitle_language_mode, quality_goal, video_codecs FROM local_media_profiles"
            ))
        }
        assert {row.subtitle_language_mode for row in profiles.values()} == {"site"}
        assert profiles[5].quality_goal == "compatibility"
        assert profiles[6].quality_goal == "custom"
        assert all(codec["allowed"] for codec in json.loads(profiles[6].video_codecs))
        assert [key for (key,) in connection.execute(text(
            "SELECT default_key FROM notification_rules ORDER BY position"
        ))] == [
            "download_failed", "sign_in_needed", "disk_almost_full", "task_failing", "update_available", "daily_summary",
            # Added for creators in 0.10.0.
            "new_lists_found",
        ]


def test_canceled_history_actions_are_spelled_like_the_rest_of_vodloft(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        for history_id, action in ((1, "cancelled"), (2, "completed"), (3, "cancel_requested")):
            connection.execute(text(
                "INSERT INTO media_download_history (id, media_download_id, action, metadata, occurred_at) "
                "VALUES (:id, 1, :action, '{}', '2026-11-04 10:00:00')"
            ), {"id": history_id, "action": action})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        actions = dict(connection.execute(text("SELECT id, action FROM media_download_history")).all())
    assert actions == {1: "canceled", 2: "completed", 3: "cancel_requested"}


def test_which_episodes_becomes_one_ordered_list_of_filters(migration_database):
    _database_path, engine = migration_database
    import json

    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_6_0_REVISION)
    with engine.begin() as connection:
        for collection_id, identifier in ((1, "seasonal"), (2, "numbered")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :slug, :slug, 'https://example.test/' || :slug, "
                "'free', 'series', :identifier, 'Author', 'author', 'dailywire')"
            ), {"id": collection_id, "uuid": f"uuid-{collection_id}", "slug": f"show-{collection_id}", "identifier": identifier})
        for season_id, index in ((1, 1), (2, 2)):
            connection.execute(text(
                "INSERT INTO seasons (id, collection_id, \"index\", slug, name, season_type, season_number) "
                "VALUES (:id, 1, :index, :slug, :slug, 'normal', :index)"
            ), {"id": season_id, "index": index, "slug": f"season-{index}"})
        for profile_id in (5, 6):
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type) VALUES "
                "(:id, :slug, :slug, '/downloads/' || :slug || '/{{ collection }}/{{ episode_title }}.ext', 'format_1080p', "
                "'collection')"
            ), {"id": profile_id, "slug": f"p{profile_id}"})
        profiles = (
            # (id, collection, local media profile, types, days, count, retention)
            (1, 1, 5, '["ep"]', 0, 25, "published"),
            (2, 2, 5, '["ep"]', 30, 0, "downloaded"),
            (3, 2, 5, '["trailer"]', 30, 0, "downloaded"),
            (4, 2, 6, '["ep"]', 0, 10, "published"),
            (5, 2, 6, '["aux"]', 0, 0, "published"),
        )
        for profile_id, collection_id, local_id, types, days, count, _retention in profiles:
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "download_with_countdown, redownload_final, download_days_in_past, download_episode_count, "
                "delete_older_episodes, include_upcoming_seasons) "
                "VALUES (:id, :collection, :local, :enabled, :types, 0, 0, :days, :count, 1, 1)"
            ), {"id": profile_id, "collection": collection_id, "local": local_id, "types": types, "days": days,
                "count": count, "enabled": int(profile_id != 3)})
        connection.execute(text(
            "INSERT INTO download_profile_seasons (download_profile_id, season_id) VALUES (1, 2)"
        ))
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        for profile_id, _collection, _local, _types, _days, _count, retention in profiles:
            connection.execute(text(
                "UPDATE download_profiles SET retention_from = :retention WHERE id = :id"
            ), {"id": profile_id, "retention": retention})
        connection.execute(text(
            "INSERT INTO download_profile_rules (download_profile_id, position, action, field, pattern, ignore_case) "
            "VALUES (1, 0, 'skip', 'title', 'trailer', 1)"
        ))
        connection.execute(text(
            "INSERT INTO media_items (id, uuid, type, source_key) VALUES (10, 'episode-10', 'episode', 'dailywire')"
        ))
        connection.execute(text(
            "INSERT INTO seasons (id, collection_id, \"index\", slug, name, season_type, season_number) "
            "VALUES (3, 2, 1, 'season-1', 'Season 1', 'normal', 1)"
        ))
        connection.execute(text(
            "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, slug, "
            "publish_status, sharing_url, source_slug) VALUES (10, 2, 3, 1, 'trailer.1', 'e10', "
            "'published_final', 'https://example.test', 'e10')"
        ))
        connection.execute(text(
            "INSERT INTO media_downloads (id, type, media_item_id, local_media_profile_id, artifact_status, file_path) "
            "VALUES (20, 'episode', 10, 5, 'absent', '')"
        ))
        connection.execute(text(
            "INSERT INTO media_downloads_episode (id, download_profile_id) VALUES (20, 3)"
        ))

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT download_profile_id, position, action, field, pattern, episode_types, season_slugs, include_upcoming, "
            "days, count FROM download_profile_filters ORDER BY download_profile_id, position"
        )).all()
        enabled = dict(connection.execute(text("SELECT id, enable_profile FROM download_profiles")).all())
        download_profile = connection.execute(text(
            "SELECT download_profile_id FROM media_downloads_episode WHERE id = 20"
        )).scalar_one()
    by_profile: dict[int, list] = {}
    for row in rows:
        by_profile.setdefault(row.download_profile_id, []).append(
            (row.action, row.field, row.pattern, row.episode_types and json.loads(row.episode_types),
             row.season_slugs and json.loads(row.season_slugs), bool(row.include_upcoming), row.days, row.count)
        )
    # Seasons first, then episode types, then the rules, then the date line; ignore case is in the pattern.
    assert by_profile[1] == [
        ("only", "seasons", None, None, ["season-2"], True, None, None),
        ("only", "types", None, ["ep"], None, False, None, None),
        ("skip", "title", "(?i)trailer", None, None, False, None, None),
        ("only", "published", None, None, None, False, None, 25),
    ]
    # Profiles 2 and 3 differed only in their episode types: one profile downloads both, with profile 3's downloads.
    assert by_profile[2] == [
        ("only", "types", None, ["ep", "trailer"], None, False, None, None),
        ("only", "downloaded", None, None, None, False, 30, None),
    ]
    assert download_profile == 2
    # Profiles 4 and 5 differ in their date line too: the oldest stays.
    assert by_profile[4] == [
        ("only", "types", None, ["ep"], None, False, None, None),
        ("only", "published", None, None, None, False, None, 10),
    ]
    assert enabled == {1: 1, 2: 1, 4: 1}


def test_a_start_date_becomes_a_published_filter_after_an_attempt_that_stopped(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_6_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'uuid-1', 'show', 'show', 'https://example.test/show', "
            "'free', 'podcast', 'date_based', 'Author', 'author', 'dailywire')"
        ))
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, type) VALUES "
            "(5, 'audio', 'audio', '/downloads/audio/{{ collection }}/{{ episode_title }}.ext', 'format_audio_only', "
            "'collection')"
        ))
        connection.execute(text(
            "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
            "download_with_countdown, redownload_final, download_days_in_past, download_episode_count, "
            "download_starting_from, delete_older_episodes, include_upcoming_seasons) "
            "VALUES (1, 1, 5, 1, '[\"ep\"]', 0, 0, 0, 0, '2026-01-10', 1, 1)"
        ))
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    # An earlier attempt created the filters table, then stopped before converting anything.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE download_profile_filters (id INTEGER PRIMARY KEY)"))

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT action, field, starting_from FROM download_profile_filters ORDER BY position"
        )).all()
    assert [tuple(row) for row in rows] == [("only", "types", None), ("only", "published", "2026-01-10")]


def test_sites_migration_places_named_sources_and_moves_the_domain_preference(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        for collection_id, slug, source_key in ((1, "a-show", "dailywire"), (2, "UC123", "ytdlp")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :slug, :slug, 'https://example.test/' || :slug, "
                "'free', 'series', 'numbered', 'Author', 'author', :source_key)"
            ), {"id": collection_id, "uuid": f"uuid-{collection_id}", "slug": slug, "source_key": source_key})
        connection.execute(text(
            "INSERT INTO source_domain_preferences (domain, source_key) VALUES ('npo.nl', 'ytdlp')"
        ))

    # Up to 0.9.1, before 0.10.0 adds the Sites VODLoft used to always list.
    command.upgrade(config, VODLOFT_0_9_1_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT slug, site_key, site_ref FROM collections ORDER BY id"
        )).all() == [("a-show", "dailywire", "a-show"), ("UC123", None, None)]
        assert connection.execute(text(
            "SELECT key, name, domains, preferred_source_key FROM sites ORDER BY key"
        )).all() == [("dailywire", "The Daily Wire", '["dailywire.com"]', None), ("npo", "NPO Start", '["npo.nl"]', "ytdlp")]


def test_existing_videos_keep_their_metadata_final(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        connection.execute(text("INSERT INTO media_items (id, uuid, type, source_key) VALUES (1, 'v1', 'video', 'ytdlp')"))
        connection.execute(text(
            "INSERT INTO media_items_video (id, slug, sharing_url) VALUES (1, 'v1', 'https://www.youtube.com/watch?v=1')"
        ))

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT metadata_is_final FROM media_items_video")).scalar_one() == 1
        columns = {row.name: row for row in connection.execute(text("PRAGMA table_info(media_items_video)"))}
        assert columns["metadata_is_final"].dflt_value == "'1'"


def test_publish_statuses_get_names_every_source_shares(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        for episode_id, status in ((10, "dw_processing"), (11, "published_with_countdown"), (12, "published_final")):
            connection.execute(text(
                "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, slug, "
                "publish_status, sharing_url, source_slug) VALUES (:id, 1, 1, :id, 'ep.' || :id, 'e' || :id, "
                ":status, 'https://example.test', 'e' || :id)"
            ), {"id": episode_id, "status": status})
        connection.execute(text(
            "INSERT INTO media_downloads_episode (id, downloaded_publish_status) VALUES (1, 'published_with_countdown')"
        ))
        connection.execute(text(
            "INSERT INTO media_download_history (id, media_download_id, action, metadata, occurred_at) VALUES "
            "(1, 1, 'started', '{\"started_publish_status\": \"published_with_countdown\", \"is_redownload\": true}', "
            "'2026-11-04 10:00:00')"
        ))
        connection.execute(text(
            "INSERT INTO task_operations (id, kind, source, resource_type, title, status, context, result) VALUES "
            "('op-1', 'episode.early_delete', 'user', 'episode', 'Early delete', 'succeeded', "
            "'{\"episode_publish_status\": \"dw_processing\"}', '{\"publish_status\": \"published_with_countdown\"}')"
        ))
        connection.execute(text(
            "INSERT INTO metadata (parent_table, parent_id, key, value) VALUES "
            "('media_items_episode', 10, 'ep_status.dw_processing.slug', 'e10')"
        ))

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT id, publish_status FROM media_items_episode")).all()) == {
            10: "source_processing", 11: "published_preliminary", 12: "published_final",
        }
        assert connection.execute(text(
            "SELECT downloaded_publish_status FROM media_downloads_episode"
        )).scalar_one() == "published_preliminary"
        assert json.loads(connection.execute(text("SELECT metadata FROM media_download_history")).scalar_one()) == {
            "started_publish_status": "published_preliminary", "is_redownload": True,
        }
        context, result = connection.execute(text("SELECT context, result FROM task_operations")).one()
        assert json.loads(context) == {"episode_publish_status": "source_processing"}
        assert json.loads(result) == {"publish_status": "published_preliminary"}
        assert connection.execute(text("SELECT key FROM metadata")).scalar_one() == "ep_status.source_processing.slug"


def test_the_daily_wire_profiles_move_to_its_own_resolutions_and_duplicates_merge(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    template = "/downloads/{{ collection }}/{{ episode_title }}.ext"
    with engine.begin() as connection:
        for collection_id, source_key in ((1, "dailywire"), (2, "ytdlp")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :uuid, 'C', 'https://example.test/' || :uuid, "
                "'free', 'series', 'numbered', 'Host', 'host', :source)"
            ), {"id": collection_id, "uuid": f"c{collection_id}", "source": source_key})
        profiles = (
            # id, type, template, format, source_keys
            (1, "movie", "/movies/{{ title }}.ext", "format_4k", None),
            (2, "collection", template, "format_4k", '["dailywire"]'),
            (3, "collection", template, "format_1080p", None),
            (4, "collection", "/all/{{ title }}.ext", "format_4k", None),
            (5, "collection", "/dw/{{ title }}.ext", "format_360p", '["dailywire"]'),
        )
        for profile_id, profile_type, path, preferred, source_keys in profiles:
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, type, output_template, preferred_format, video_codecs, source_keys) "
                "VALUES (:id, :slug, :slug, :type, :path, :format, '[]', :keys)"
            ), {"id": profile_id, "slug": f"p{profile_id}", "type": profile_type, "path": path, "format": preferred, "keys": source_keys})
            connection.execute(text(f"INSERT INTO local_media_profiles_{profile_type} (id) VALUES (:id)"), {"id": profile_id})
        for media_id in (10, 11):
            connection.execute(text(
                "INSERT INTO media_items (id, uuid, type, source_key) VALUES (:id, :uuid, 'episode', 'dailywire')"
            ), {"id": media_id, "uuid": f"m{media_id}"})
        # Both profiles hold episode 10; only the merged one holds episode 11.
        for download_id, media_id, profile_id in ((100, 10, 2), (101, 10, 3), (102, 11, 2)):
            connection.execute(text(
                "INSERT INTO media_downloads (id, type, media_item_id, local_media_profile_id, file_path) "
                "VALUES (:id, 'episode', :media, :profile, '/x')"
            ), {"id": download_id, "media": media_id, "profile": profile_id})
            connection.execute(text("INSERT INTO media_downloads_episode (id) VALUES (:id)"), {"id": download_id})
        connection.execute(text(
            "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
            "sponsorblock_segments) VALUES (7, 1, 2, 1, '[]', '{}')"
        ))
        for stream_id, collection_id in ((20, 1), (21, 2)):
            connection.execute(text(
                "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, use_dw_stream, "
                "preferred_format, prefer_exact_match) VALUES (:id, 'rss', :collection, 1, :token, 1, 0, 'format_4k', 0)"
            ), {"id": stream_id, "collection": collection_id, "token": f"t{stream_id}"})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        formats = dict(connection.execute(text("SELECT id, preferred_format FROM local_media_profiles")).all())
        # Profile 2 merged into 3, which uses its template at 1080p; profiles also for other Sources keep theirs.
        assert formats == {1: "format_1080p", 3: "format_1080p", 4: "format_4k", 5: "format_480p"}
        assert connection.execute(text("SELECT id FROM local_media_profiles_collection ORDER BY id")).scalars().all() == [3, 4, 5]
        assert dict(connection.execute(text("SELECT id, local_media_profile_id FROM media_downloads")).all()) == {101: 3, 102: 3}
        assert connection.execute(text("SELECT id FROM media_downloads_episode ORDER BY id")).scalars().all() == [101, 102]
        assert connection.execute(text("SELECT local_media_profile_id FROM download_profiles")).scalar_one() == 3
        assert dict(connection.execute(text("SELECT id, preferred_format FROM stream_profiles")).all()) == {
            20: "format_1080p", 21: "format_4k",
        }


def test_youtube_feeds_stream_at_its_own_resolutions_through_vodloft(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        for collection_id, url in ((1, "https://www.youtube.com/@host"), (2, "https://vimeo.com/host")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :uuid, 'C', :url, "
                "'free', 'series', 'numbered', 'Host', 'host', 'ytdlp')"
            ), {"id": collection_id, "uuid": f"c{collection_id}", "url": url})
        for stream_id, collection_id, streams, preferred in (
                (20, 1, 1, "format_480p"), (21, 1, 1, "format_4k"), (22, 1, 0, "format_4k"), (23, 2, 1, "format_4k")):
            connection.execute(text(
                "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, use_dw_stream, "
                "preferred_format, prefer_exact_match) VALUES (:id, 'rss', :collection, 1, :token, 1, :streams, :format, 0)"
            ), {"id": stream_id, "collection": collection_id, "token": f"t{stream_id}", "streams": streams, "format": preferred})
            connection.execute(text(
                "INSERT INTO stream_profiles_rss (id, feed_url, max_items) VALUES (:id, :url, 0)"
            ), {"id": stream_id, "url": f"https://example.test/{stream_id}"})

    command.upgrade(config, VODLOFT_0_8_0_REVISION)

    with engine.connect() as connection:
        # Only feeds that stream from YouTube move; feeds of downloads keep any resolution.
        assert dict(connection.execute(text("SELECT id, preferred_format FROM stream_profiles")).all()) == {
            20: "format_720p", 21: "format_1080p", 22: "format_4k", 23: "format_4k",
        }
        assert connection.execute(text("SELECT DISTINCT proxy_source_stream FROM stream_profiles_rss")).scalars().all() == [1]


def test_feeds_of_sites_without_hls_video_move_to_mp4(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        for collection_id, source, url in (
                (1, "ytdlp", "https://www.youtube.com/@host"), (2, "ytdlp", "https://vimeo.com/host"),
                (3, "dailywire", "https://www.dailywire.com/show/host"), (4, "npo", "https://npo.nl/start/serie/host")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :uuid, 'C', :url, "
                "'free', 'series', 'numbered', 'Host', 'host', :source)"
            ), {"id": collection_id, "uuid": f"c{collection_id}", "url": url, "source": source})
        for stream_id, collection_id, mode in (
                (20, 1, "audio_hls"), (21, 2, "audio_hls"), (22, 2, "mp4_hls"), (23, 3, "mp4_hls"), (24, 4, "audio_hls"),
                (25, 4, "mp4")):
            connection.execute(text(
                "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, use_dw_stream, "
                "preferred_format, prefer_exact_match) VALUES (:id, 'rss', :collection, 1, :token, 1, 0, 'format_1080p', 0)"
            ), {"id": stream_id, "collection": collection_id, "token": f"t{stream_id}"})
            connection.execute(text(
                "INSERT INTO stream_profiles_rss (id, feed_url, max_items, video_output_mode) VALUES (:id, :url, 0, :mode)"
            ), {"id": stream_id, "url": f"https://example.test/{stream_id}", "mode": mode})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        # YouTube and The Daily Wire have HLS video; Vimeo and NPO Start do not.
        assert dict(connection.execute(text("SELECT id, video_output_mode FROM stream_profiles_rss")).all()) == {
            20: "audio_hls", 21: "audio_mp4", 22: "mp4", 23: "mp4_hls", 24: "audio_mp4", 25: "mp4",
        }


def test_daily_wire_profiles_get_the_upgrade_check_for_a_different_length(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        for collection_id, source_key in ((1, "dailywire"), (2, "ytdlp")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :uuid, 'C', 'https://example.test/' || :uuid, "
                "'free', 'series', 'numbered', 'Host', 'host', :source)"
            ), {"id": collection_id, "uuid": f"c{collection_id}", "source": source_key})
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, type, output_template, preferred_format, video_codecs) "
            "VALUES (1, 'p1', 'p1', 'collection', '/x/{{ title }}.ext', 'format_1080p', '[]')"
        ))
        connection.execute(text("INSERT INTO local_media_profiles_collection (id) VALUES (1)"))
        for profile_id, collection_id in ((7, 1), (8, 2)):
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "sponsorblock_segments, upgrade_check, upgrade_improvements) "
                "VALUES (:id, :collection, 1, 1, '[]', '{}', 0, '[\"resolution\"]')"
            ), {"id": profile_id, "collection": collection_id})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, upgrade_check, upgrade_improvements, upgrade_length_minutes FROM download_profiles ORDER BY id"
        )).all()
        assert [(row[0], row[1], json.loads(row[2]), row[3]) for row in rows] == [
            (7, 1, ["length"], 5),
            (8, 0, ["resolution"], 5),
        ]
        assert connection.execute(text("SELECT duration FROM media_downloads")).all() == []


def test_feeds_proxy_their_sites_video_by_default(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'c1', 'c1', 'C', 'https://www.youtube.com/@host', "
            "'free', 'series', 'numbered', 'Host', 'host', 'ytdlp')"
        ))
        connection.execute(text(
            "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, use_dw_stream, "
            "preferred_format, prefer_exact_match) VALUES (20, 'rss', 1, 1, 't20', 1, 1, 'format_720p', 0)"
        ))
        connection.execute(text("INSERT INTO stream_profiles_rss (id, feed_url, max_items) VALUES (20, 'https://example.test/20', 0)"))

    command.upgrade(config, VODLOFT_0_8_0_REVISION)

    with engine.begin() as connection:
        assert connection.execute(text("SELECT proxy_source_stream FROM stream_profiles_rss")).scalar_one() == 1
        connection.execute(text(
            "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, use_source_stream, "
            "preferred_format, prefer_exact_match) VALUES (21, 'rss', 1, 1, 't21', 1, 1, 'format_720p', 0)"
        ))
        connection.execute(text("INSERT INTO stream_profiles_rss (id, feed_url, max_items) VALUES (21, 'https://example.test/21', 0)"))
        assert connection.execute(text("SELECT proxy_source_stream FROM stream_profiles_rss WHERE id = 21")).scalar_one() == 1


def test_collections_keep_the_episode_order_their_identification_gave_them(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        for collection_id, identifier in ((1, "date_based"), (2, "numbered"), (3, "seasonal")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :uuid, 'C', 'https://example.test/' || :uuid, "
                "'free', 'series', :identifier, 'Host', 'host', 'dailywire')"
            ), {"id": collection_id, "uuid": f"c{collection_id}", "identifier": identifier})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, episode_order FROM collections ORDER BY id")).all() == [
            (1, "newest_first"), (2, "newest_first"), (3, "oldest_first"),
        ]


def test_imported_downloads_join_the_download_profile_of_their_collection(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'c1', 'c1', 'C', "
            "'https://example.test/c1', 'free', 'series', 'date_based', 'Host', 'host', 'youtube')"
        ))
        connection.execute(text(
            "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
            "sponsorblock_segments) VALUES (7, 1, 5, 1, '[]', '{}')"
        ))
        # 1 imported, 2 imported for a Local Media Profile without a Download Profile,
        # 3 downloaded by hand, 4 imported and already managed by another profile.
        for download_id, profile_id, action, managed in (
            (1, 5, "imported", None), (2, 6, "imported", None), (3, 5, "created", None), (4, 5, "imported", 8),
        ):
            connection.execute(text(
                "INSERT INTO media_items (id, uuid, type, source_key) VALUES (:id, :uuid, 'episode', 'youtube')"
            ), {"id": 10 + download_id, "uuid": f"e{download_id}"})
            connection.execute(text(
                "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, "
                "slug, publish_status, sharing_url, source_slug) VALUES (:id, 1, 1, :id, :identifier, :slug, "
                "'published_final', 'https://example.test', :slug)"
            ), {"id": 10 + download_id, "identifier": f"video.{download_id}", "slug": f"e{download_id}"})
            connection.execute(text(
                "INSERT INTO media_downloads (id, type, media_item_id, local_media_profile_id, file_path, artifact_status) "
                "VALUES (:id, 'episode', :media, :profile, '/downloads/' || :id, 'missing')"
            ), {"id": download_id, "media": 10 + download_id, "profile": profile_id})
            connection.execute(text(
                "INSERT INTO media_downloads_episode (id, download_profile_id) VALUES (:id, :managed)"
            ), {"id": download_id, "managed": managed})
            connection.execute(text(
                "INSERT INTO media_download_history (media_download_id, action, metadata, occurred_at) "
                "VALUES (:id, :action, '{}', '2026-11-04 10:00:00')"
            ), {"id": download_id, "action": action})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        managed = dict(connection.execute(text("SELECT id, download_profile_id FROM media_downloads_episode")).all())
    assert managed == {1: 7, 2: None, 3: None, 4: 8}


def test_media_that_needed_a_subscription_says_which_access_it_needs(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        for media_id, source_key, needs in ((1, "npo", 1), (2, "ytdlp", 1), (3, "dailywire", 1), (4, "ytdlp", 0)):
            connection.execute(text(
                "INSERT INTO media_items (id, uuid, type, source_key, needs_subscription) "
                "VALUES (:id, :uuid, 'video', :source, :needs)"
            ), {"id": media_id, "uuid": f"m{media_id}", "source": source_key, "needs": needs})
            connection.execute(text(
                "INSERT INTO media_downloads (id, type, media_item_id, local_media_profile_id, file_path, "
                "artifact_status, automatic_retry_suppressed) VALUES (:id, 'video', :id, 1, '/d', 'absent', 1)"
            ), {"id": media_id})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        media = {row.id: row for row in connection.execute(text(
            "SELECT id, access, access_refused_at, access_check_at, access_checks FROM media_items"
        ))}
        suppressed = dict(connection.execute(text("SELECT id, automatic_retry_suppressed FROM media_downloads")).all())
    assert {media_id: row.access for media_id, row in media.items()} == {
        1: "npo_plus", 2: "members", 3: "INSIDER", 4: None,
    }
    # NPO knows from the account whether VODLoft may have it; elsewhere a download was refused.
    assert [media_id for media_id, row in media.items() if row.access_refused_at is not None] == [2, 3]
    assert [media_id for media_id, row in media.items() if row.access_check_at is not None] == [2, 3]
    assert suppressed == {1: 0, 2: 0, 3: 0, 4: 1}


def test_every_download_profile_chooses_the_new_sponsorblock_types(migration_database):
    """The new SponsorBlock types reach the Local Media Profile of a YouTube collection that has no Site yet."""
    _database_path, engine = migration_database
    import json

    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key) VALUES (1, 'c1', 'c1', 'C', 'https://www.youtube.com/@host', "
            "'free', 'series', 'date_based', 'Host', 'host', 'ytdlp')"
        ))
        for profile_id, segments in ((5, None), (6, {"sponsor": "cut", "poi_highlight": "keep"})):
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, type, output_template, preferred_format, video_codecs) "
                "VALUES (:id, :slug, :slug, 'collection', '/x/' || :slug || '/{{ title }}.ext', 'format_1080p', '[]')"
            ), {"id": profile_id, "slug": f"p{profile_id}"})
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "sponsorblock_enabled, sponsorblock_segments) VALUES (:id, 1, :local, 1, '[]', 1, :segments)"
            ), {"id": profile_id - 4, "local": profile_id, "segments": json.dumps(segments or {})})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, sponsorblock_enabled, sponsorblock_segments FROM local_media_profiles"))
        profiles = {profile_id: (bool(enabled), json.loads(value)) for profile_id, enabled, value in rows}
    assert profiles[5][0] and profiles[6][0]
    assert (profiles[5][1]["poi_highlight"], profiles[5][1]["hook"], profiles[5][1]["chapter"]) == ("chapter", "keep", "keep")
    assert (profiles[6][1]["sponsor"], profiles[6][1]["poi_highlight"], profiles[6][1]["hook"]) == ("cut", "keep", "keep")


def test_local_media_profiles_move_from_sources_to_sites(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    with engine.begin() as connection:
        profiles = (
            # id, type, source_keys
            (1, "collection", None),
            (2, "collection", '["dailywire"]'),
            (3, "video", '["ytdlp"]'),
            (4, "collection", '["npo", "ytdlp"]'),
            (5, "movie", None),
        )
        for profile_id, profile_type, source_keys in profiles:
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, type, output_template, preferred_format, video_codecs, source_keys) "
                "VALUES (:id, :slug, :slug, :type, '/x/' || :slug || '/{{ title }}.ext', 'format_1080p', '[]', :keys)"
            ), {"id": profile_id, "slug": f"p{profile_id}", "type": profile_type, "keys": source_keys})

    command.upgrade(config, VODLOFT_0_9_0_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, site_keys, include_upcoming_sites FROM local_media_profiles ORDER BY id")).all()
        sites = {profile_id: (json.loads(keys), bool(upcoming)) for profile_id, keys, upcoming in rows}
        assert sites == {
            1: (["dailywire", "npo", "youtube"], True),
            2: (["dailywire"], False),
            # yt-dlp stands for every Site that is not The Daily Wire or NPO Start, and for Sites to come.
            3: (["youtube"], True),
            4: (["npo", "youtube"], True),
            5: (["dailywire"], True),
        }
        columns = {column["name"] for column in inspect(connection).get_columns("local_media_profiles")}
        assert "source_keys" not in columns


def test_auto_subtitles_and_sponsorblock_move_to_the_local_media_profile(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)
    cut = {"sponsor": "cut"}
    with engine.begin() as connection:
        collections = (
            (1, "ytdlp", "https://www.youtube.com/@one"), (2, "ytdlp", "https://youtu.be/two"),
            (3, "ytdlp", "https://www.youtube.com/@three"), (4, "ytdlp", "https://vimeo.com/four"),
            (5, "dailywire", "https://www.dailywire.com/show/five"),
        )
        for collection_id, source_key, url in collections:
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key) VALUES (:id, :uuid, :uuid, 'C', :url, 'free', 'series', "
                "'numbered', 'Host', 'host', :source)"
            ), {"id": collection_id, "uuid": f"c{collection_id}", "url": url, "source": source_key})
        for profile_id in (1, 2):
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, type, output_template, preferred_format, video_codecs) "
                "VALUES (:id, :slug, :slug, 'collection', '/x/' || :slug || '/{{ title }}.ext', 'format_1080p', '[]')"
            ), {"id": profile_id, "slug": f"p{profile_id}"})
        # Two of the three YouTube Download Profiles of profile 1 use auto-generated subtitles always and cut sponsors.
        rows = (
            (1, 1, 1, "always", 1, cut), (2, 2, 1, "always", 1, cut), (3, 3, 1, "never", 0, {}),
            (4, 4, 1, "fallback", 0, {}), (5, 5, 1, "never", 0, {}),
        )
        for download_profile_id, collection_id, profile_id, auto, sponsorblock, segments in rows:
            connection.execute(text(
                "INSERT INTO download_profiles (id, collection_id, local_media_profile_id, enable_profile, ep_id_type_list, "
                "auto_subtitles, sponsorblock_enabled, sponsorblock_segments) "
                "VALUES (:id, :collection, :profile, 1, '[]', :auto, :sb, :segments)"
            ), {"id": download_profile_id, "collection": collection_id, "profile": profile_id, "auto": auto,
                "sb": sponsorblock, "segments": json.dumps(segments)})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        profiles = {
            row.id: (row.auto_subtitles, bool(row.sponsorblock_enabled), json.loads(row.sponsorblock_segments))
            for row in connection.execute(text(
                "SELECT id, auto_subtitles, sponsorblock_enabled, sponsorblock_segments FROM local_media_profiles"
            ))
        }
        columns = {column["name"] for column in inspect(connection).get_columns("download_profiles")}
    default_segments = {
        "sponsor": "chapter", "selfpromo": "keep", "interaction": "keep", "intro": "chapter", "outro": "chapter",
        "preview": "keep", "filler": "keep", "hook": "keep", "music_offtopic": "keep", "poi_highlight": "chapter",
        "chapter": "keep",
    }
    assert profiles == {
        # What most of its Download Profiles on Sites with the setting had: The Daily Wire has neither.
        1: ("always", True, {**default_segments, **cut}),
        # Without Download Profiles: auto-generated subtitles when there are no real ones, and SponsorBlock off.
        2: ("fallback", False, default_segments),
    }
    assert not {"auto_subtitles", "sponsorblock_enabled", "sponsorblock_segments"} & columns


def test_the_database_unlinks_downloads_from_a_deleted_download_profile(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_7_0_REVISION)

    def ondelete() -> str | None:
        with engine.connect() as connection:
            [foreign_key] = [
                key for key in inspect(connection).get_foreign_keys("media_downloads_episode")
                if key["constrained_columns"] == ["download_profile_id"]
            ]
        assert foreign_key["name"] == "fk_media_downloads_episode_download_profile_id_download_profiles"
        return foreign_key["options"].get("ondelete")

    assert ondelete() is None
    command.upgrade(config, HEAD_REVISION)
    assert ondelete() == "SET NULL"


def test_stream_profiles_keep_their_feed_settings_when_every_type_shares_them(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_8_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key, episode_order) VALUES (1, 'c1', 'c1', 'C', "
            "'https://www.dailywire.com/show/c', 'free', 'series', 'numbered', 'Host', 'host', 'dailywire', 'newest_first')"
        ))
        for profile_id, max_items, live, proxy, handoffs in ((20, 25, 1, 0, "[7, 9]"), (21, 0, 0, 1, "[]")):
            connection.execute(text(
                "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, "
                "use_source_stream, preferred_format, prefer_exact_match) "
                "VALUES (:id, 'rss', 1, 1, :token, 1, 1, 'format_720p', 0)"
            ), {"id": profile_id, "token": f"t{profile_id}"})
            connection.execute(text(
                "INSERT INTO stream_profiles_rss (id, feed_url, max_items, stream_live_episodes, proxy_source_stream, "
                "live_episode_handoff_ids) VALUES (:id, 'https://example.test/feed', :max_items, :live, :proxy, :handoffs)"
            ), {"id": profile_id, "max_items": max_items, "live": live, "proxy": proxy, "handoffs": handoffs})

    command.upgrade(config, HEAD_REVISION)

    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT id, max_items, stream_live_episodes, proxy_source_stream, live_episode_handoff_ids "
            "FROM stream_profiles ORDER BY id"
        )).all()
        rss_columns = {column["name"] for column in inspect(connection).get_columns("stream_profiles_rss")}
    assert [(row[0], row[1], bool(row[2]), bool(row[3]), json.loads(row[4])) for row in rows] == [
        (20, 25, True, False, [7, 9]),
        (21, 0, False, True, []),
    ]
    assert rss_columns == {"id", "feed_url", "video_output_mode"}

    command.downgrade(config, VODLOFT_0_8_0_REVISION)
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT max_items, proxy_source_stream FROM stream_profiles_rss WHERE id = 20"
        )).one() == (25, 0)


def test_iptv_migration_gives_each_user_and_the_install_a_stream_token(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_8_0_REVISION)
    with engine.begin() as connection:
        for name in ("ann", "bob"):
            connection.execute(text(
                "INSERT INTO users (username, password_hash, session_version, library_collection_sort) "
                "VALUES (:name, 'x', 0, 'name')"
            ), {"name": name})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        tokens = connection.execute(text("SELECT stream_token FROM users")).scalars().all()
        install = connection.execute(text("SELECT stream_token FROM settings")).scalar_one()
    assert len(set(tokens)) == 2 and all(len(token) >= 32 for token in tokens)
    assert install and install not in tokens


def test_0_10_0_episodes_without_usable_media_leave_or_stay_removed_from_their_source(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key, episode_order) VALUES (1, 'c1', 'c1', 'C', "
            "'https://example.test/c1', 'FREE', 'podcast', 'numbered', 'Host', 'host', 'dailywire', 'newest_first')"
        ))
        # 1 has no files, 2 has files and its old identifier is free, 3 has files and 4 took its old identifier.
        for episode_id, identifier, status in (
            (1, "not-usable.1", "no_usable_media"), (2, "not-usable.2", "no_usable_media"),
            (3, "not-usable.3", "no_usable_media"), (4, "ep.6", "published_final"),
        ):
            connection.execute(text(
                "INSERT INTO media_items (id, uuid, type, source_key) VALUES (:id, :uuid, 'episode', 'dailywire')"
            ), {"id": episode_id, "uuid": f"e{episode_id}"})
            connection.execute(text(
                "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, "
                "slug, publish_status, sharing_url, source_slug) VALUES (:id, 1, 1, :id, :identifier, :slug, :status, "
                "'https://example.test', :slug)"
            ), {"id": episode_id, "identifier": identifier, "slug": f"e{episode_id}", "status": status})
        for episode_id, previous in ((1, "ep.4"), (2, "ep.5"), (3, "ep.6")):
            for key, value in (("no_usable_media.previous_identifier", previous), ("no_usable_media.reason", "not_found")):
                connection.execute(text(
                    "INSERT INTO metadata (parent_table, parent_id, key, value, created_at, updated_at) "
                    "VALUES ('media_items_episode', :id, :key, :value, '2026-11-18', '2026-11-18')"
                ), {"id": episode_id, "key": key, "value": value})
        for key, value in (("ep_id.latest_not_usable_num", "3"), ("ep_id.latest_aux_num", "2")):
            connection.execute(text(
                "INSERT INTO metadata (parent_table, parent_id, key, value, created_at, updated_at) "
                "VALUES ('collections', 1, :key, :value, '2026-11-18', '2026-11-18')"
            ), {"key": key, "value": value})
        for download_id, episode_id in ((1, 2), (2, 3)):
            connection.execute(text(
                "INSERT INTO media_downloads (id, type, media_item_id, local_media_profile_id, file_path, artifact_status) "
                "VALUES (:id, 'episode', :media, 1, '/downloads/' || :id, 'missing')"
            ), {"id": download_id, "media": episode_id})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        episodes = connection.execute(text(
            "SELECT e.id, e.episode_identifier, e.publish_status, m.removed_from_source "
            "FROM media_items_episode e JOIN media_items m ON m.id = e.id ORDER BY e.id"
        )).all()
        assert [tuple(row) for row in episodes] == [
            (2, "ep.5", "published_final", 1), (3, "aux.3", "published_final", 1), (4, "ep.6", "published_final", 0),
        ]
        assert connection.execute(text("SELECT count(*) FROM media_items WHERE id = 1")).scalar_one() == 0
        assert dict(connection.execute(text("SELECT key, value FROM metadata WHERE parent_table = 'collections'")).all()) == {
            "ep_id.latest_aux_num": "3",
        }
        assert connection.execute(text(
            "SELECT count(*) FROM metadata WHERE parent_table = 'media_items_episode'"
        )).scalar_one() == 0




def test_a_webdav_folder_name_becomes_the_profiles_title(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key, episode_order) VALUES (1, 'c1', 'c1', 'The Show', "
            "'https://www.youtube.com/@host', 'free', 'series', 'date_based', 'Host', 'host', 'ytdlp', 'newest_first')"
        ))
        # A folder name of its own, one that is the collection's title, and none beside a title of its own.
        for profile_id, title, folder_name in ((1, "Listed", "Folder"), (2, "Listed", "The Show"), (3, "Listed", None)):
            connection.execute(text(
                "INSERT INTO stream_profiles (id, type, collection_id, overwrite_collection_title, enable_profile, "
                "token, use_downloads, use_source_stream, preferred_format, prefer_exact_match, ep_id_type_list, "
                "max_items, stream_live_episodes, proxy_source_stream, live_episode_handoff_ids) "
                "VALUES (:id, 'webdav', 1, :title, 1, :token, 1, 0, 'best', 0, '[]', 0, 0, 1, '[]')"
            ), {"id": profile_id, "title": title, "token": f"t{profile_id}"})
            connection.execute(text(
                "INSERT INTO stream_profiles_webdav (id, folder_name, season_folders, metadata_files) "
                "VALUES (:id, :folder_name, 'season', 'none')"
            ), {"id": profile_id, "folder_name": folder_name})

    command.upgrade(config, VODLOFT_0_9_1_REVISION)

    with engine.connect() as connection:
        titles = dict(connection.execute(text("SELECT id, overwrite_collection_title FROM stream_profiles")).all())
        columns = [row[1] for row in connection.execute(text("PRAGMA table_info(stream_profiles_webdav)"))]
    assert titles == {1: "Folder", 2: None, 3: "Listed"}
    assert "folder_name" not in columns


def test_webdav_shares_become_downloads_only(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_0_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key, episode_order) VALUES (1, 'c1', 'c1', 'The Show', "
            "'https://www.dailywire.com/show/c1', 'free', 'series', 'date_based', 'Host', 'host', 'dailywire', "
            "'newest_first')"
        ))
        # A share that streamed from the Site only, one that did both, and an RSS feed that streams.
        for profile_id, profile_type, use_downloads, use_source_stream in (
            (1, "webdav", 0, 1), (2, "webdav", 1, 1), (3, "rss", 0, 1),
        ):
            connection.execute(text(
                "INSERT INTO stream_profiles (id, type, collection_id, enable_profile, token, use_downloads, "
                "use_source_stream, preferred_format, prefer_exact_match, ep_id_type_list, max_items, "
                "stream_live_episodes, proxy_source_stream, live_episode_handoff_ids) "
                "VALUES (:id, :type, 1, 1, :token, :downloads, :stream, 'format_1080p', 0, '[]', 0, 0, 1, '[]')"
            ), {"id": profile_id, "type": profile_type, "token": f"t{profile_id}", "downloads": use_downloads,
                "stream": use_source_stream})

    command.upgrade(config, VODLOFT_0_9_1_REVISION)

    with engine.connect() as connection:
        sources = connection.execute(text(
            "SELECT id, use_downloads, use_source_stream FROM stream_profiles ORDER BY id"
        )).all()
    assert [tuple(row) for row in sources] == [(1, 1, 0), (2, 1, 0), (3, 0, 1)]


def test_every_collection_numbers_its_extras_in_episode_index_order(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_0_REVISION)
    with engine.begin() as connection:
        for collection_id in (1, 2):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key, episode_order) VALUES (:id, :slug, :slug, 'Show', "
                "'https://example.test/' || :slug, 'free', 'series', 'numbered', 'Host', 'host', 'dailywire', 'newest_first')"
            ), {"id": collection_id, "slug": f"c{collection_id}"})
        for season_id, collection_id, season_type in ((1, 1, "normal"), (2, 1, "extra"), (3, 2, "normal")):
            connection.execute(text(
                "INSERT INTO seasons (id, collection_id, \"index\", slug, name, season_type, season_number) "
                "VALUES (:id, :collection, :id, :slug, :slug, :type, :id)"
            ), {"id": season_id, "collection": collection_id, "slug": f"s{season_id}", "type": season_type})
        # Listed out of index order: the numbers follow the index, and each collection counts on its own.
        for episode_id, collection_id, season_id, index, identifier in (
            (10, 1, 1, 4, "aux.1"), (11, 1, 1, 1, "ep.1"), (12, 1, 2, 2, "ep.2"), (13, 1, 1, 3, "ep-extra.trailer.1.1"),
            (14, 1, 1, 5, "ep.3"), (15, 2, 3, 1, "short.1"),
        ):
            connection.execute(text(
                "INSERT INTO media_items (id, uuid, type, source_key) VALUES (:id, :uuid, 'episode', 'dailywire')"
            ), {"id": episode_id, "uuid": f"episode-{episode_id}"})
            connection.execute(text(
                "INSERT INTO media_items_episode (id, collection_id, season_id, \"index\", episode_identifier, slug, "
                "publish_status, sharing_url, source_slug) VALUES (:id, :collection, :season, :index, :identifier, "
                ":slug, 'published_final', 'https://example.test', :slug)"
            ), {"id": episode_id, "collection": collection_id, "season": season_id, "index": index,
                "identifier": identifier, "slug": f"e{episode_id}"})

    command.upgrade(config, VODLOFT_0_9_1_REVISION)

    with engine.connect() as connection:
        numbers = dict(connection.execute(text("SELECT id, extra_index FROM media_items_episode")).all())
    assert numbers == {10: 3, 11: None, 12: 1, 13: 2, 14: None, 15: 1}


def test_0_10_0_movie_profiles_become_video_profiles_that_say_what_they_are_for(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        profiles = (
            # id, slug, type, template, Sites
            (1, "vodloft-movies", "movie", "/downloads/movies/{{ movie_title }}/{{ title }}.ext", '["dailywire"]'),
            (2, "vodloft-videos", "video", "/downloads/videos/{{ title }} [{{ slug }}].ext", '["youtube"]'),
            # The same template and format as profile 2.
            (3, "clash", "movie", "/downloads/videos/{{ title }} [{{ slug }}].ext", '["dailywire"]'),
            (4, "own", "video", "/downloads/own/{{ title }}.ext", '["youtube"]'),
        )
        for profile_id, slug, profile_type, path, site_keys in profiles:
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, type, output_template, preferred_format, video_codecs, "
                "site_keys, include_upcoming_sites) VALUES (:id, :slug, :slug, :type, :path, 'format_1080p', '[]', :keys, 1)"
            ), {"id": profile_id, "slug": slug, "type": profile_type, "path": path, "keys": site_keys})
            connection.execute(text(f"INSERT INTO local_media_profiles_{profile_type} (id) VALUES (:id)"), {"id": profile_id})
        # The seeded Videos profile already holds a movie, so it stays available for movies too.
        connection.execute(text(
            "INSERT INTO media_downloads (id, type, local_media_profile_id, media_item_id, file_path) "
            "VALUES (1, 'movie', 2, 1, '/downloads/movie.mp4')"
        ))

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = {
            row.id: row for row in connection.execute(text(
                "SELECT p.id, p.type, p.output_template, p.site_keys, p.include_upcoming_sites, v.video_scope "
                "FROM local_media_profiles p JOIN local_media_profiles_video v ON v.id = p.id"
            ))
        }
        assert "local_media_profiles_movie" not in inspect(connection).get_table_names()
    assert sorted(rows) == [1, 2, 3, 4]
    assert {row.type for row in rows.values()} == {"video"}
    # Former Movie profiles keep their Sites and stop taking new ones; the Video profiles are left as they were.
    assert [(json.loads(rows[key].site_keys), bool(rows[key].include_upcoming_sites)) for key in (1, 2, 3, 4)] == [
        (["dailywire"], False), (["youtube"], True), (["dailywire"], False), (["youtube"], True),
    ]
    assert rows[1].output_template == "/downloads/movies/{{ movie_title }}/{{ title }}.ext"
    # A Jinja comment keeps the clashing template apart without naming any file differently.
    assert rows[3].output_template == "/downloads/videos/{{ title }} [{{ slug }}].ext{# kept apart from vodloft-videos #}"
    assert {key: row.video_scope for key, row in rows.items()} == {1: "movies", 2: "both", 3: "both", 4: "both"}


def test_0_10_0_a_profile_for_podcasts_and_series_is_stored_under_its_own_name(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        for profile_id, scope in ((1, "both"), (2, "podcast"), (3, "series")):
            connection.execute(text(
                "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, video_codecs, type) "
                "VALUES (:id, :id, :id, '/downloads/' || :id || '.ext', 'format_1080p', '[]', 'collection')"
            ), {"id": profile_id})
            connection.execute(text(
                "INSERT INTO local_media_profiles_collection (id, collection_scope) VALUES (:id, :scope)"
            ), {"id": profile_id, "scope": scope})

    def scopes():
        with engine.connect() as connection:
            return connection.execute(text("SELECT collection_scope FROM local_media_profiles_collection ORDER BY id")).scalars().all()

    def scope_default():
        column = next(c for c in inspect(engine).get_columns("local_media_profiles_collection") if c["name"] == "collection_scope")
        return column["default"]

    command.upgrade(config, HEAD_REVISION)
    assert scopes() == ["podcast-and-series", "podcast", "series"]
    assert "podcast-and-series" in scope_default()

    command.downgrade(config, VODLOFT_0_9_1_REVISION)
    assert scopes() == ["both", "podcast", "series"]
    assert "both" in scope_default()


def test_0_10_0_the_sites_get_their_order_and_the_always_listed_sites_become_rows(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.begin() as connection:
        for key, name, domain in (("youtube", "YouTube", "youtube.com"), ("twitch", "Twitch", "twitch.tv")):
            connection.execute(text("INSERT INTO sites (key, name, domains) VALUES (:key, :name, :domains)"), {
                "key": key, "name": name, "domains": json.dumps([domain]),
            })

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT key, domains FROM sites ORDER BY position")).all()
    # Numbered by name, with The Daily Wire and NPO Start added beside the YouTube row the installation had.
    assert [key for key, _ in rows] == ["npo", "dailywire", "twitch", "youtube"]
    assert json.loads(dict(rows)["npo"]) == ["npo.nl"]


def test_0_10_0_installations_with_notification_rules_get_the_new_lists_rule(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.connect() as connection:
        before = connection.execute(text("SELECT default_key FROM notification_rules ORDER BY position")).scalars().all()

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rules = connection.execute(text(
            "SELECT default_key, event, position, push FROM notification_rules ORDER BY position"
        )).all()
    assert before and "new_lists_found" not in before
    assert [rule.default_key for rule in rules] == [*before, "new_lists_found"]
    assert tuple(rules[-1]) == ("new_lists_found", "new_lists_found", rules[-2].position + 1, 1)


def test_0_10_0_seasons_of_sites_with_their_own_seasons_came_from_the_site(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.begin() as connection:
        # A Daily Wire show and a YouTube channel.
        for collection_id, source_key in ((1, "dailywire"), (2, "ytdlp")):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key, episode_order) VALUES (:id, 'uuid-' || :id, 'c' || :id, 'C', "
                "'https://example.test/' || :id, 'free', 'series', 'seasonal', 'Host', 'host', :source, 'oldest_first')"
            ), {"id": collection_id, "source": source_key})
        for season_id, collection_id, slug in ((1, 1, "season-1"), (2, 1, "2024"), (3, 2, "2023"), (4, 2, "vlogs")):
            connection.execute(text(
                "INSERT INTO seasons (id, collection_id, \"index\", slug, name, season_type, season_number) "
                "VALUES (:id, :collection, :id, :slug, :slug, 'normal', :id)"
            ), {"id": season_id, "collection": collection_id, "slug": slug})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, origin FROM seasons ORDER BY id")).all() == [
            (1, "site"), (2, "vodloft"), (3, "vodloft"), (4, "vodloft"),
        ]
        collection = connection.execute(text(
            "SELECT kind, link_seasons, channel_season, repeat_videos, new_lists, creator_id FROM collections WHERE id = 2"
        )).one()
    # Every collection starts as a channel collection without lists; a background migration tells its kind.
    assert tuple(collection) == ("channel", "off", "unlisted", "one_season", "{}", None)


def test_0_10_0_downgrades_to_0_9_1_and_upgrades_again(migration_database):
    _database_path, _engine = migration_database
    from backend.db.migrations import check_database, get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, HEAD_REVISION)
    command.downgrade(config, VODLOFT_0_9_1_REVISION)
    command.upgrade(config, HEAD_REVISION)

    check_database()


def test_dw_episode_number_becomes_source_number_in_episodes_and_saved_templates(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, VODLOFT_0_9_1_REVISION)
    template = "/downloads/{{ dw_episode_number }} {{ title | default('dw_episode_number') }} dw_episode_number.ext"
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO local_media_profiles (id, slug, name, output_template, preferred_format, video_codecs, type) "
            "VALUES (5, 'p', 'P', :template, 'format_1080p', '[]', 'collection')"
        ), {"template": template})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT output_template FROM local_media_profiles")).scalar_one() == (
            "/downloads/{{ source_number }} {{ title | default('dw_episode_number') }} dw_episode_number.ext"
        )
    assert "source_number" in {column["name"] for column in inspect(engine).get_columns("media_items_episode")}

    command.downgrade(config, VODLOFT_0_9_1_REVISION)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT output_template FROM local_media_profiles")).scalar_one() == template
    assert "dw_episode_number" in {column["name"] for column in inspect(engine).get_columns("media_items_episode")}


def test_yt_dlp_options_vodloft_now_refuses_become_comments(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config
    from sources.ytdlp_options import check_ytdlp_options

    config = get_alembic_config()
    command.upgrade(config, "4c7e19a2b6d0")
    collection_options = "--concurrent-fragments 4\n--limit-rate 2M\n# --test\n--remove-chapters Intro --no-mtime"
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
            "author_name, author_slug, source_key, episode_order, ytdlp_options) VALUES (1, 'c1', 'c1', 'Channel', "
            "'https://example.test/c1', 'free', 'series', 'seasonal', 'Author', 'author', 'ytdlp', 'newest_first', "
            ":options)"
        ), {"options": collection_options})
        connection.execute(text("UPDATE settings SET ytdlp_options = :options"), {"options": "--no-warn\n-N 4"})

    command.upgrade(config, "ee7b43f4d6a1")

    with engine.connect() as connection:
        collection = connection.execute(text("SELECT ytdlp_options FROM collections")).scalar_one()
        source = connection.execute(text("SELECT ytdlp_options FROM settings")).scalar()
    note = "# Turned off by VODLoft, which no longer takes this option here: "
    assert collection.splitlines() == [
        "--concurrent-fragments 4", f"{note}--limit-rate 2M", "# --test", f"{note}--remove-chapters Intro --no-mtime",
    ]
    # An abbreviated option is matched the way yt-dlp matches it.
    assert source.splitlines() == [f"{note}--no-warn", "-N 4"]
    # What is left passes VODLoft's check, so downloads keep working.
    assert all(line.status == "valid" for line in check_ytdlp_options(collection))
    assert all(line.status == "valid" for line in check_ytdlp_options(source))

    command.downgrade(config, "4c7e19a2b6d0")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT ytdlp_options FROM collections")).scalar_one() == collection_options


def test_downloads_to_move_become_an_issue_of_the_collections_health(migration_database):
    _database_path, engine = migration_database
    from backend.db.migrations import get_alembic_config

    config = get_alembic_config()
    command.upgrade(config, "6ab9362820f3")
    with engine.begin() as connection:
        for collection_id, waiting in ((1, 0), (2, 3)):
            connection.execute(text(
                "INSERT INTO collections (id, uuid, slug, title, sharing_url, membership_level, type, episode_identifier, "
                "author_name, author_slug, source_key, episode_order, moves_waiting) VALUES (:id, 'uuid-' || :id, "
                "'c' || :id, 'C', 'https://example.test/' || :id, 'free', 'series', 'seasonal', 'Host', 'host', "
                "'ytdlp', 'oldest_first', :waiting)"
            ), {"id": collection_id, "waiting": waiting})

    command.upgrade(config, HEAD_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, healthy, health_issues FROM collections ORDER BY id")).all()
    assert [(row[0], bool(row[1]), json.loads(row[2])) for row in rows] == [(1, True, {}), (2, False, {"moves": 3})]
    assert "moves_waiting" not in {column["name"] for column in inspect(engine).get_columns("collections")}

    command.downgrade(config, "6ab9362820f3")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, moves_waiting FROM collections ORDER BY id")).all() == [(1, 0), (2, 3)]
