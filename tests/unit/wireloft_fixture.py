"""A small WireLoft 1.2.5 installation, built with WireLoft's own migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from importer.wireloft.migrations import HEAD, create

TEMPLATE = "/downloads/shows/{{ show_title }}/{{ season_name }}/{{ episode_identifier }} {{ episode_title }}.ext"
MOVIE_TEMPLATE = "/downloads/movies/{{ title }}.ext"
MEDIA = b"wireloft-media" * 50


def wireloft_installation(folder: Path, downloads: Path, *, target: str = HEAD) -> Path:
    """``folder``/wireloft.db with one show, one episode on disk, a movie and its trailer, and a feed.

    Files are written under ``downloads``, which WireLoft saw as ``/downloads``.
    """
    database = folder / "wireloft.db"
    create(database, target=target)
    episode_file = downloads / "shows" / "Morning Show" / "Season 1" / "ep.S01E01 First.mp4"
    episode_file.parent.mkdir(parents=True, exist_ok=True)
    episode_file.write_bytes(MEDIA)
    from downloader.storage.identity import inspect_artifact

    identity = inspect_artifact(episode_file)
    c = sqlite3.connect(database)
    x = c.execute
    show = x(
        "INSERT INTO shows (uuid, slug, title, description, sharing_url, membership_level, type, episode_identifier, "
        "author_name, author_slug) VALUES ('show-uuid', 'morning-show', 'Morning Show', '', "
        "'https://www.dailywire.com/show/morning-show', 'WL_ANY', 'series', 'seasonal', 'Host', 'host')"
    ).lastrowid
    season = x("INSERT INTO seasons (show_id, \"index\", slug, name, season_type, season_number) "
               "VALUES (?, 1, 'morning-show-season-1', 'Season 1', 'normal', 1)", (show,)).lastrowid
    episode = x("INSERT INTO media_items (uuid, type) VALUES ('episode-uuid', 'episode')").lastrowid
    x("INSERT INTO media_items_episode (id, show_id, season_id, \"index\", episode_identifier, slug, publish_status, "
      "sharing_url, title, duration, metadata_is_final) VALUES (?, ?, ?, 1, 'ep.S01E01', 'morning-show-first', "
      "'published_final', 'https://www.dailywire.com/episode/first', 'First', 60, 1)", (episode, show, season))
    profile = x("INSERT INTO local_media_profiles (slug, name, output_template, preferred_format, type) "
                "VALUES ('wl-shows', 'WireLoft Shows', ?, 'format_1080p', 'show')", (TEMPLATE,)).lastrowid
    x("INSERT INTO local_media_profiles_show (id, show_scope) VALUES (?, 'both')", (profile,))
    movie_profile = x("INSERT INTO local_media_profiles (slug, name, output_template, preferred_format, type) "
                      "VALUES ('wl-movies', 'WireLoft Movies', ?, 'format_1080p', 'movie')", (MOVIE_TEMPLATE,)).lastrowid
    x("INSERT INTO local_media_profiles_movie (id) VALUES (?)", (movie_profile,))
    for parent, parent_id, key, value in (
        ("media_items_episode", episode, "source.slug", "first"),
        ("media_items_episode", episode, f"custom_index.{profile}.day", "3"),
        ("media_items_episode", episode, "ep_status.last_known_pending", "wireloft:last_known_pending:2026-01-01T00:00:00+00:00"),
        ("local_media_profiles", profile, "custom_index.definition.day", "Day"),
        ("shows", show, "custom_note", "kept"),
    ):
        x("INSERT INTO metadata (parent_table, parent_id, key, value) VALUES (?, ?, ?, ?)", (parent, parent_id, key, value))
    dp = x("INSERT INTO download_profiles (show_id, local_media_profile_id, type, enable_profile, ep_id_type_list) "
           "VALUES (?, ?, 'series', 1, '[\"ep\"]')", (show, profile)).lastrowid
    x("INSERT INTO download_profiles_series (id, include_upcoming_seasons) VALUES (?, 0)", (dp,))
    x("INSERT INTO download_profile_series_seasons (download_profiles_series_id, season_id) VALUES (?, ?)", (dp, season))
    stream = x("INSERT INTO stream_profiles (type, show_id, enable_profile, token, use_downloads, use_dw_stream, "
               "preferred_format, prefer_exact_match, ep_id_type_list) VALUES ('rss', ?, 1, 'feed-token', 1, 1, "
               "'format_1080p', 0, '[]')", (show,)).lastrowid
    x("INSERT INTO stream_profiles_rss (id, feed_url, max_items) VALUES (?, 'https://wireloft.test/feed.xml', 0)", (stream,))
    download = x(
        "INSERT INTO media_downloads (type, media_item_id, local_media_profile_id, file_path, downloaded_bytes, "
        "artifact_status, artifact_stat_dev, artifact_stat_ino, artifact_size_bytes, artifact_fingerprint, downloaded_at) "
        "VALUES ('episode', ?, ?, ?, ?, 'available', ?, ?, ?, ?, '2026-01-02 00:00:00')",
        (episode, profile, "/downloads/shows/Morning Show/Season 1/ep.S01E01 First.mp4", identity.size_bytes,
         identity.stat_dev, identity.stat_ino, identity.size_bytes, identity.fingerprint),
    ).lastrowid
    x("INSERT INTO media_downloads_episode (id, download_profile_id, downloaded_publish_status) "
      "VALUES (?, ?, 'published_final')", (download, dp))
    x("INSERT INTO media_download_history (media_download_id, action, metadata) VALUES (?, 'downloaded', '{}')", (download,))
    movie = x("INSERT INTO media_items (uuid, type) VALUES ('movie-uuid', 'movie')").lastrowid
    x("INSERT INTO media_items_movie (id, slug, title, is_downloadable) VALUES (?, 'big-movie', 'Big Movie', 1)", (movie,))
    source = x("INSERT INTO movie_extra_sources (slug, title) VALUES ('big-movie-trailer', 'Trailer')").lastrowid
    extra = x("INSERT INTO media_items (uuid, type) VALUES ('extra-uuid', 'movie_extra')").lastrowid
    x("INSERT INTO media_items_movie_extra (id, movie_id, movie_extra_type, source_id) VALUES (?, ?, 'trailer', ?)",
      (extra, movie, source))
    x("UPDATE media_items_movie SET official_trailer_id = ? WHERE id = ?", (extra, movie))
    x("UPDATE settings SET background_migration_version = 'b7d2f49c0a13'")
    c.commit()
    c.close()
    (folder / "config.yml").write_text(
        "downloadSettings:\n  maxConcurrentDownloads: 3\n  downloadRoot: /downloads\n  downloadShowAssets: false\n"
        "scheduler:\n  maxWorkers: 5\n",
        encoding="utf-8",
    )
    keyring = folder / "keyring" / "data" / "python_keyring" / "keyring_pass.cfg"
    keyring.parent.mkdir(parents=True)
    import base64

    record = base64.b64encode(b'{"access_token": "a", "refresh_token": "r", "expires_at": 1}').decode()
    keyring.write_text(f"[wireloft_2Ddailywire_2Dauth]\nissuer_7Cclient = {record}\n", encoding="utf-8")
    return database
