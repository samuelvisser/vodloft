"""WireLoft's own migrations, which now only bring an uploaded copy to the newest WireLoft schema."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, inspect, text

from conftest import schema_of
from importer.wireloft import migrations
from importer.wireloft.migrations import HEAD, RELEASES, UnknownWireLoftRelease, create, upgrade

WIRELOFT_1_0 = "c8d4e2f1a7b9"
WIRELOFT_1_1 = "d8b4a1f6c203"
WIRELOFT_1_2 = "6d4a8c1f2b90"
WIRELOFT_1_2_1 = "f2a6c93d8b14"
WIRELOFT_1_2_3 = "a4e7c19b2d53"


@pytest.fixture
def wireloft_database(tmp_path: Path):
    path = tmp_path / "wireloft.db"
    engines = []

    def connect():
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        engines.append(engine)
        return engine

    yield path, connect
    for engine in engines:
        engine.dispose()


@pytest.mark.parametrize("release", [release.revision for release in RELEASES])
def test_every_release_upgrades_to_the_newest_schema(wireloft_database, tmp_path, release):
    path, connect = wireloft_database
    create(path, target=release)
    applied = upgrade(path)

    assert [item.revision for item in applied] == [item.revision for item in RELEASES][
        [item.revision for item in RELEASES].index(release) + 1:
    ]
    fresh = tmp_path / "fresh.db"
    create(fresh)
    assert schema_of(connect()) == schema_of(create_engine(f"sqlite:///{fresh.as_posix()}"))
    with connect().connect() as connection:
        assert migrations.stored_revision(connection) == HEAD


def test_an_unknown_release_is_refused_with_the_revision_it_found(wireloft_database):
    path, connect = wireloft_database
    create(path, target=WIRELOFT_1_2_3)
    with connect().begin() as connection:
        connection.execute(text("UPDATE settings SET alembic_version_num = 'ffffffffffff'"))

    with pytest.raises(UnknownWireLoftRelease, match="ffffffffffff"):
        upgrade(path)

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



def test_countdown_redownload_intent_migration_uses_current_episode_table(wireloft_database):
    database_path, connect = wireloft_database
    create(database_path, target=WIRELOFT_1_2_1)
    engine = connect()

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

    upgrade(database_path, target=WIRELOFT_1_2_3)

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
        )).scalar_one() == WIRELOFT_1_2_3




def test_upgrade_from_wireloft_1_0_preserves_release_data(wireloft_database):
    database_path, connect = wireloft_database
    create(database_path, target=WIRELOFT_1_0)
    engine = connect()
    seeded = _seed_wireloft_1_0_data(database_path, engine)
    upgrade(database_path)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "media_download_attempts" not in tables
    assert "task_operations" in tables
    assert "alembic_version" not in tables

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT alembic_version_num FROM settings"
        )).scalar_one() == HEAD

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




def test_rss_output_mode_migration_rewrites_methods_and_stabilizes_feed_urls(wireloft_database):
    database_path, connect = wireloft_database
    create(database_path, target=WIRELOFT_1_1)
    engine = connect()

    cases = [
        ("stream_hls_download_m4a", "audio_hls", "format_1080p"),
        ("stream_download_mp4", "mp4", "format_1080p"),
        ("stream_hls_download_mp4", "mp4_hls", "format_1080p"),
        # All former experiment-only values intentionally collapse back to the
        # supported default instead of becoming permanent runtime aliases.
        ("experiment_hls_local_mp4_or_dw", "audio_hls", "format_1080p"),
        # Audio-only profiles do not have a meaningful video output mode.
        ("stream_hls_download_m4a", None, "format_audio_only"),
    ]

    try:
        with engine.begin() as connection:
            show_id = connection.execute(text(
                "INSERT INTO shows "
                "(uuid, slug, title, description, sharing_url, membership_level, "
                "type, episode_identifier, author_name, author_slug) VALUES "
                "('migration-show-uuid', 'migration-show', 'Migration Show', "
                "'Description', 'https://example.test/migration-show', 'FREE', "
                "'podcast', 'numbered', 'Host', 'host')"
            )).lastrowid

            for index, (old_method, _new_mode, preferred_format) in enumerate(cases):
                profile_id = connection.execute(text(
                    "INSERT INTO stream_profiles "
                    "(type, show_id, enable_profile, token, use_downloads, "
                    "use_dw_stream, preferred_format, require_exact_match, ep_id_type_list) VALUES "
                    "('rss', :show_id, 1, :token, 1, 1, :preferred_format, 0, '[]')"
                ), {
                    "show_id": show_id,
                    "token": f"profile-{index}",
                    "preferred_format": preferred_format,
                }).lastrowid
                connection.execute(text(
                    "INSERT INTO stream_profiles_rss "
                    "(id, feed_url, dw_video_method, max_items) VALUES "
                    "(:id, :feed_url, :method, 0)"
                ), {
                    "id": profile_id,
                    "feed_url": (
                        f"https://vodloft.test/feed-{index}.xml?"
                        f"custom=value&dwVideoMethod={old_method}#fragment"
                    ),
                    "method": old_method,
                })

        upgrade(database_path, target=WIRELOFT_1_2)

        with engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT base.token, base.prefer_exact_match, rss.video_output_mode, rss.feed_url "
                "FROM stream_profiles_rss AS rss "
                "JOIN stream_profiles AS base ON base.id = rss.id "
                "ORDER BY base.token"
            )).mappings().all()

        video_output_column = next(
            column
            for column in inspect(engine).get_columns("stream_profiles_rss")
            if column["name"] == "video_output_mode"
        )
        assert video_output_column["nullable"] is True

        stream_profile_columns = {
            column["name"]
            for column in inspect(engine).get_columns("stream_profiles")
        }
        assert "prefer_exact_match" in stream_profile_columns
        assert "require_exact_match" not in stream_profile_columns

        by_token = {row["token"]: row for row in rows}
        for index, (_old_method, new_mode, _preferred_format) in enumerate(cases):
            row = by_token[f"profile-{index}"]
            assert not row["prefer_exact_match"]
            assert row["video_output_mode"] == new_mode
            parts = urlsplit(row["feed_url"])
            assert parse_qs(parts.query) == {"custom": ["value"]}
            assert parts.fragment == "fragment"
    finally:
        engine.dispose()
