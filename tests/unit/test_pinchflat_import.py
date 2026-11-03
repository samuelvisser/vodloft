"""The Pinchflat importer: reading its database, the plan, uploads, and applying an import twice."""
from __future__ import annotations

import io
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import importer.pinchflat as pinchflat
from importer.contract import CustomIndexPlan
from importer.paths import detect_path_map, map_path, path_map_candidates
from importer.pinchflat import NEWEST_KNOWN_VERSION, PinchflatReadError, plan_import, read_pinchflat
from importer.uploads import normalise_upload_path

CHANNEL_TEMPLATE = "/YouTube/{{ source_custom_name }}/{{ season_episode_index_from_date }} - {{ title }} [{{ id }}].{{ ext }}"
PLAYLIST_TEMPLATE = "/Lists/{{ source_custom_name }}/{{ media_playlist_index }} {{ title }}.{{ ext }}"


def _pinchflat_db(path: Path, *, version: int = NEWEST_KNOWN_VERSION, items=None) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, inserted_at TEXT);
        CREATE TABLE media_profiles (
            id INTEGER PRIMARY KEY, name TEXT, output_path_template TEXT, preferred_resolution TEXT,
            download_subs INTEGER, download_auto_subs INTEGER, embed_subs INTEGER, sub_langs TEXT,
            download_thumbnail INTEGER, embed_thumbnail INTEGER, download_metadata INTEGER, embed_metadata INTEGER,
            download_nfo INTEGER, download_source_images INTEGER, shorts_behaviour TEXT, livestream_behaviour TEXT,
            sponsorblock_behaviour TEXT, sponsorblock_categories TEXT, redownload_delay_days INTEGER,
            media_container TEXT, audio_track TEXT, marked_for_deletion_at TEXT);
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY, collection_name TEXT, collection_id TEXT, collection_type TEXT, original_url TEXT,
            media_profile_id INTEGER, custom_name TEXT, enabled INTEGER, download_media INTEGER,
            download_cutoff_date TEXT, retention_period_days INTEGER, output_path_template_override TEXT,
            title_filter_regex TEXT, min_duration_seconds INTEGER, max_duration_seconds INTEGER, cookie_behaviour TEXT,
            series_directory TEXT, nfo_filepath TEXT, poster_filepath TEXT, fanart_filepath TEXT,
            banner_filepath TEXT, marked_for_deletion_at TEXT);
        CREATE TABLE media_items (
            id INTEGER PRIMARY KEY, media_id TEXT, title TEXT, media_filepath TEXT, source_id INTEGER,
            uploaded_at TEXT, playlist_index INTEGER, upload_date_index INTEGER, prevent_download INTEGER,
            culled_at TEXT, livestream INTEGER, short_form_content INTEGER, subtitle_filepaths TEXT,
            thumbnail_filepath TEXT, metadata_filepath TEXT, nfo_filepath TEXT);
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY, restrict_filenames INTEGER, extractor_sleep_interval_seconds NUMBER,
            download_throughput_limit TEXT, youtube_api_key TEXT, apprise_server TEXT, yt_dlp_version TEXT);
    """)
    connection.execute("INSERT INTO schema_migrations VALUES (?, '')", (version,))
    connection.executemany("INSERT INTO media_profiles (id, name, output_path_template, preferred_resolution, "
                           "download_subs, embed_subs, shorts_behaviour, livestream_behaviour) VALUES (?,?,?,?,?,?,?,?)", [
        (1, "Media server", CHANNEL_TEMPLATE, "1080p", 1, 0, "exclude", "include"),
        (2, "Lists", PLAYLIST_TEMPLATE, "1440p", 0, 0, "include", "include"),
    ])
    connection.executemany("INSERT INTO sources (id, collection_name, collection_type, original_url, media_profile_id, "
                           "custom_name, enabled, download_media, retention_period_days, download_cutoff_date) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (1, "Veritasium", "channel", "https://www.youtube.com/@veritasium", 1, None, 1, 1, None, "2020-01-01"),
        (2, "Lofi beats", "playlist", "https://www.youtube.com/playlist?list=PL1", 2, "Lofi", 0, 1, 30, None),
    ])
    connection.executemany(
        "INSERT INTO media_items (id, media_id, title, media_filepath, source_id, uploaded_at, playlist_index, "
        "upload_date_index, prevent_download, culled_at) VALUES (?,?,?,?,?,?,?,?,?,?)", items or [
            (1, "vid-aaaaaaa", "First", "/downloads/YouTube/Veritasium/s2024e030299 - First [vid-aaaaaaa].mp4", 1,
             "2024-03-02T10:00:00Z", 0, 99, 0, None),
            (2, "vid-bbbbbbb", "Second", "/downloads/YouTube/Veritasium/s2024e030298 - Second [vid-bbbbbbb].mkv", 1,
             "2024-03-02T18:00:00Z", 0, 98, 0, None),
            (3, "vid-ccccccc", "Skipped", None, 1, "2024-04-01T10:00:00Z", 0, 99, 1, None),
            (4, "vid-ddddddd", "Culled", None, 1, "2023-01-01T10:00:00Z", 0, 99, 0, "2024-01-01T00:00:00Z"),
            (5, "vid-eeeeeee", "Track one", "/downloads/Lists/Lofi/03 Track one.m4a", 2, "2022-05-05T00:00:00Z", 3, 0, 0, None),
            (6, "vid-fffffff", "Not downloaded", None, 1, "2025-01-01T00:00:00Z", 0, 99, 0, None),
        ])
    connection.execute("INSERT INTO settings (id, restrict_filenames, youtube_api_key, apprise_server) "
                       "VALUES (1, 0, 'test-key', 'apprise://x')")
    connection.commit()
    connection.close()
    return path


# Reading ----------------------------------------------------------------------

def test_the_reader_reads_a_pinchflat_database(tmp_path):
    data = read_pinchflat(_pinchflat_db(tmp_path / "pinchflat.db"))

    assert data.version == NEWEST_KNOWN_VERSION
    assert [source.name for source in data.sources] == ["Veritasium", "Lofi"]
    assert [item.media_id for item in data.items if item.media_filepath] == ["vid-aaaaaaa", "vid-bbbbbbb", "vid-eeeeeee"]
    assert data.settings.youtube_api_key == "test-key" and data.settings.apprise_configured


def test_the_reader_refuses_a_newer_or_a_foreign_database(tmp_path):
    with pytest.raises(PinchflatReadError, match="newer than this VODLoft knows"):
        read_pinchflat(_pinchflat_db(tmp_path / "new.db", version=NEWEST_KNOWN_VERSION + 1))
    foreign = tmp_path / "foreign.db"
    sqlite3.connect(foreign).execute("CREATE TABLE things (id INTEGER)").connection.commit()
    with pytest.raises(PinchflatReadError, match="not a Pinchflat database"):
        read_pinchflat(foreign)
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises(PinchflatReadError):
        read_pinchflat(broken)


# The plan ---------------------------------------------------------------------

def test_the_plan_converts_profiles_and_maps_sources_and_items(tmp_path):
    plan = plan_import(read_pinchflat(_pinchflat_db(tmp_path / "pinchflat.db")), option_directory=None)

    channel, playlist = plan.profiles
    assert channel.output_template == (
        "/downloads/YouTube/{{ collection_title | as_typed }}/s{{ year }}e{{ date | strftime('%m%d') }}"
        "{{ '%02d' | format('day' | custom_index(per=date, start=99, step=-1)) }} - {{ title }} [{{ episode_site_id }}].ext"
    )
    assert channel.custom_indexes == (CustomIndexPlan("day", "Upload date index", True, start=99, step=-1),)
    assert channel.settings["preferred_format"] == "format_1080p"
    assert channel.settings["subtitle_mode"] == "sidecar"
    assert playlist.settings["preferred_format"] == "format_1440p"
    assert "preferred_resolution" not in {warning.subject for warning in playlist.warnings}

    veritasium, lofi = plan.collections
    assert (veritasium.title, lofi.title) == ("Veritasium", "Lofi")
    assert veritasium.download_profile["ep_id_type_list"] == ["ep", "livestream"]
    assert veritasium.download_profile["download_starting_from"] == "2020-01-01"
    assert (lofi.download_profile["enable_profile"], lofi.download_profile["download_days_in_past"]) == (False, 30)

    kinds = {(file.media_site_id, file.kind) for file in plan.files}
    assert kinds == {
        ("vid-aaaaaaa", "file"), ("vid-bbbbbbb", "file"), ("vid-ccccccc", "suppressed"),
        ("vid-ddddddd", "missing"), ("vid-eeeeeee", "file"),
    }
    by_id = {file.media_site_id: file for file in plan.files}
    # Pinchflat's channel numbers count down from 99; VODLoft stores the first as 1.
    assert by_id["vid-aaaaaaa"].custom_index_values == {"day": 1}
    assert by_id["vid-bbbbbbb"].custom_index_values == {"day": 2}
    assert by_id["vid-eeeeeee"].custom_index_values == {"playlist": 3}
    settings = {setting.key: setting for setting in plan.settings}
    assert settings["ytdlp.youtube_api_key"].secret
    assert settings["apprise_server"].support == "unsupported"


def test_filters_retention_and_prevent_culling_become_which_episodes(tmp_path):
    path = _pinchflat_db(tmp_path / "pinchflat.db")
    connection = sqlite3.connect(path)
    connection.execute("UPDATE sources SET title_filter_regex = 'Part \\d+', min_duration_seconds = 120, "
                       "max_duration_seconds = 3600 WHERE id = 1")
    connection.execute("ALTER TABLE media_items ADD COLUMN prevent_culling INTEGER")
    connection.execute("UPDATE media_items SET prevent_culling = 1 WHERE id = 1")
    connection.commit()
    connection.close()

    plan = plan_import(read_pinchflat(path), option_directory=None)

    veritasium, lofi = plan.collections
    assert veritasium.download_profile["rules"] == [
        {"action": "only", "field": "title", "pattern": "Part \\d+", "ignore_case": False},
        {"action": "skip", "field": "duration", "duration_operator": "shorter", "duration_seconds": 120},
        {"action": "skip", "field": "duration", "duration_operator": "longer", "duration_seconds": 3600},
    ]
    assert not {warning.subject for warning in veritasium.warnings} & {"title_filter_regex", "duration"}
    assert lofi.download_profile["retention_from"] == "downloaded"
    by_id = {file.media_site_id: file for file in plan.files}
    assert by_id["vid-aaaaaaa"].kept and not by_id["vid-bbbbbbb"].kept


def test_quality_and_subtitle_choices_come_over(tmp_path):
    path = _pinchflat_db(tmp_path / "pinchflat.db")
    connection = sqlite3.connect(path)
    connection.execute("UPDATE media_profiles SET sub_langs = 'nl,en.*,weird[x', download_auto_subs = 1, "
                       "audio_track = 'nl', media_container = 'mkv' WHERE id = 1")
    connection.commit()
    connection.close()

    plan = plan_import(read_pinchflat(path), option_directory=None)

    channel, playlist = plan.profiles
    assert channel.settings["subtitle_languages"] == ["nl", "en"]
    assert channel.settings["subtitle_language_mode"] == "listed"
    assert channel.settings["audio_language"] == "nl"
    assert (channel.settings["quality_goal"], channel.settings["container"]) == ("custom", "mkv")
    assert channel.settings["video_codecs"][0] == {"codec": "h264", "allowed": True}
    assert "sub_langs" in {warning.subject for warning in channel.warnings}
    assert not {warning.subject for warning in channel.warnings} & {"audio_track", "media_container", "download_auto_subs"}
    # Without a language list, every language the site offers; at 1440p, H.264 first but every codec allowed.
    assert playlist.settings["subtitle_language_mode"] == "site"
    assert (playlist.settings["quality_goal"], playlist.settings["container"]) == ("custom", "mp4")
    assert all(choice["allowed"] for choice in playlist.settings["video_codecs"])
    veritasium, _lofi = plan.collections
    assert veritasium.download_profile["auto_subtitles"] == "fallback"


def test_paths_map_onto_the_folder_vodloft_sees():
    samples = ["/downloads/Video/a.mp4", "/downloads/Video/b.mp4"]
    on_disk = {"/downloads/pinchflat/Video/a.mp4", "/downloads/pinchflat/Video/b.mp4"}

    candidates = path_map_candidates(samples, ["/downloads/pinchflat", "/downloads/other"])
    assert detect_path_map(samples, on_disk.__contains__, candidates) == (("/downloads", "/downloads/pinchflat"), 2)
    # VODLoft's download folder can also be one of Pinchflat's folders.
    assert detect_path_map(samples, {"/downloads/a.mp4", "/downloads/b.mp4"}.__contains__, candidates) == (
        ("/downloads/Video", "/downloads"), 2,
    )
    assert map_path("/elsewhere/a.mp4") is None
    assert map_path("/downloads/../etc/passwd") is None


def test_an_upload_takes_only_the_files_the_importer_reads():
    files = pinchflat.UPLOAD_FILES
    assert normalise_upload_path("config/db/pinchflat.db", files)[0] == "db/pinchflat.db"
    assert normalise_upload_path("pinchflat.db-wal", files)[0] == "db/pinchflat.db-wal"
    assert normalise_upload_path("config/extras/yt-dlp-configs/base-config.txt", files)[0] == "extras/yt-dlp-configs/base-config.txt"
    assert normalise_upload_path("config/metadata/sources/1/poster.jpg", files) is None
    assert normalise_upload_path("../db/pinchflat.db", files) is None
    assert normalise_upload_path("extras/cookies.txt", files)[1].secret


# Uploads ----------------------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    from backend.services import import_uploads

    monkeypatch.setattr(import_uploads, "imports_root", lambda: tmp_path / "imports")
    return import_uploads


def test_a_chunked_upload_resumes_and_skips_what_is_not_needed(store, tmp_path):
    database = _pinchflat_db(tmp_path / "pinchflat.db").read_bytes()
    begun = store.begin_upload(pinchflat.IMPORTER, [
        ("config/db/pinchflat.db", len(database)), ("config/metadata/a.jpg", 10), ("config/extras/cookies.txt", 5),
    ], include_secrets=False)
    assert begun["skipped"] == ["config/metadata/a.jpg", "config/extras/cookies.txt"]
    assert [item["path"] for item in begun["incoming"]["files"]] == ["db/pinchflat.db"]

    half = len(database) // 2
    assert store.write_chunk(pinchflat.IMPORTER, "db/pinchflat.db", 0, database[:half]) == half
    with pytest.raises(store.UploadOffsetError) as offset:
        store.write_chunk(pinchflat.IMPORTER, "db/pinchflat.db", 0, database[:half])
    assert offset.value.received == half
    with pytest.raises(store.UploadError, match="has"):
        store.finish_upload(pinchflat.IMPORTER)
    store.write_chunk(pinchflat.IMPORTER, "db/pinchflat.db", half, database[half:])

    status = store.finish_upload(pinchflat.IMPORTER)
    assert status["upload"]["files"] == [{"path": "db/pinchflat.db", "size": len(database), "secret": False}]
    assert read_pinchflat(store.work_location(pinchflat.IMPORTER, ("/downloads", "/downloads")).database).version


def test_an_archive_upload_keeps_only_the_importers_files(store, tmp_path):
    database = _pinchflat_db(tmp_path / "pinchflat.db").read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("config/db/pinchflat.db", database)
        archive.writestr("config/extras/yt-dlp-configs/media-profile-1-config.txt", "--embed-chapters\n")
        archive.writestr("config/extras/cookies.txt", "secret")
        archive.writestr("config/metadata/huge.jpg", "x" * 100)
        archive.writestr("../escape.txt", "x")
    data = buffer.getvalue()
    store.begin_upload(pinchflat.IMPORTER, [("pinchflat-config.zip", len(data))], include_secrets=False)
    store.write_chunk(pinchflat.IMPORTER, "archive.zip", 0, data)

    status = store.finish_upload(pinchflat.IMPORTER)

    assert sorted(item["path"] for item in status["upload"]["files"]) == [
        "db/pinchflat.db", "extras/yt-dlp-configs/media-profile-1-config.txt",
    ]
    assert not (tmp_path / "escape.txt").exists()
    location = store.work_location(pinchflat.IMPORTER, ("/downloads", "/downloads"))
    assert (location.extras / "yt-dlp-configs" / "media-profile-1-config.txt").is_file()


def test_an_upload_without_the_database_is_refused(store):
    with pytest.raises(store.UploadError, match="pinchflat.db is missing"):
        store.begin_upload(pinchflat.IMPORTER, [("config/extras/yt-dlp-configs/base-config.txt", 3)], include_secrets=False)


# Applying an import -----------------------------------------------------------

def _session() -> Session:
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    """A Pinchflat upload, its files on disk under VODLoft's /downloads/pinchflat, and a fake yt-dlp Source."""
    from sources import registry
    from sources.contract import CollectionDetails, Feature, Source

    from backend.services import import_uploads, imports
    from config import get_settings

    downloads = tmp_path / "downloads"
    monkeypatch.setattr(get_settings().download_settings, "download_root", downloads)
    monkeypatch.setattr(import_uploads, "imports_root", lambda: tmp_path / "imports")
    applied: list[tuple[str, object]] = []
    monkeypatch.setattr(imports, "_apply_setting", lambda key, value: applied.append((key, value)))

    for relative in ("YouTube/Veritasium/s2024e030299 - First [vid-aaaaaaa].mp4",
                     "YouTube/Veritasium/s2024e030298 - Second [vid-bbbbbbb].mkv",
                     "Lists/Lofi/03 Track one.m4a"):
        path = downloads / "pinchflat" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"media" * 20)

    database = _pinchflat_db(tmp_path / "pinchflat.db")
    import_uploads.begin_upload(pinchflat.IMPORTER, [("db/pinchflat.db", database.stat().st_size)], include_secrets=False)
    import_uploads.write_chunk(pinchflat.IMPORTER, "db/pinchflat.db", 0, database.read_bytes())
    import_uploads.finish_upload(pinchflat.IMPORTER)

    class FakeYtDlp(Source):
        id = "ytdlp"
        name = "yt-dlp"
        domains = ("youtube.com",)
        features = frozenset({Feature.COLLECTIONS, Feature.EPISODE_LISTS})

        def resolve(self, url):
            return None

        def episode_media(self, **_kwargs):
            raise NotImplementedError

        def movie_playback(self, **_kwargs):
            raise NotImplementedError

        def collection_details(self, url):
            slug = "PL1" if "list=" in url else "UCveritasium"
            return CollectionDetails(slug=slug, url=url, title="From YouTube", author_name="Derek")

    monkeypatch.setattr(registry, "_sources", {**registry._sources, "ytdlp": FakeYtDlp()})
    return _session(), applied


def _index(session, collection, site_ids):
    from backend.db.models import Episode, Season
    from backend.types.media_types import MediaType

    season = Season(collection=collection, index=1, slug=f"{collection.slug}-2024", name="2024")
    session.add(season)
    for index, site_id in enumerate(site_ids, start=1):
        session.add(Episode(
            source_key="ytdlp", uuid=f"{collection.slug}-{site_id}", type=MediaType.EPISODE.value,
            collection=collection, season=season, index=index, episode_identifier=f"ep.{index}",
            slug=f"{collection.slug}-{site_id}", source_slug=site_id, title=site_id, description="", duration=60,
            publish_status="published_final", sharing_url=f"https://www.youtube.com/watch?v={site_id}",
            published_date=datetime(2024, 3, 2, 12, index, tzinfo=timezone.utc),
        ))
    session.commit()


def _run(session, options):
    from backend.services import imports

    run = imports.start_run(session, pinchflat.IMPORTER, options)
    session.commit()
    imports.apply_run(session, run.id)
    return session.get(type(run), run.id)


def _adopt_waiting(session):
    from backend.db.models import ImportStep
    from backend.services import imports

    for step in list(session.scalars(select(ImportStep).where(ImportStep.status == "waiting"))):
        imports.run_step(session, step.id)


def test_preview_finds_the_folder_and_writes_nothing(installation):
    from backend.db.models import Collection, ImportLink
    from backend.services import imports

    session, _applied = installation
    view = imports.preview(session, pinchflat.IMPORTER, imports.ImportOptions())

    assert (view["path_map"]["source"], view["path_map"]["target"]) == ("/downloads", "/downloads/pinchflat")
    assert view["path_map"]["found"] == view["path_map"]["sampled"] == 3
    assert [(item["title"], item["becomes"], item["files_on_disk"]) for item in view["collections"]] == [
        ("Veritasium", "new", 2), ("Lofi", "new", 1),
    ]
    channel = view["profiles"][0]
    assert channel["path_proof"]["identical"] == 2, channel["path_proof"]
    secret = next(item for item in view["settings"] if item["key"] == "ytdlp.youtube_api_key")
    assert secret["value"] is None and secret["selected"]
    assert session.scalar(select(Collection)) is None and session.scalar(select(ImportLink)) is None


def test_an_import_adopts_every_file_and_a_second_run_changes_nothing(installation):
    from backend.db.models import (
        Collection, CollectionLocalMediaProfile, DownloadProfile, EpisodeMediaDownload, ImportLink, ImportStep,
    )
    from backend.services import imports
    from backend.utils.custom_index import get_episode_index_assignments

    session, applied = installation
    run = _run(session, imports.ImportOptions(enable_download_profiles=True))
    assert run.status == "waiting"
    assert [key for key, _value in applied] == ["downloads.filename_restriction_mode", "ytdlp.youtube_api_key"]

    collections = {collection.title: collection for collection in session.scalars(select(Collection))}
    assert set(collections) == {"Veritasium", "Lofi"}
    profiles = list(session.scalars(select(CollectionLocalMediaProfile)))
    assert sorted(profile.name for profile in profiles) == ["Lists", "Media server"]
    assert all(not profile.enable_profile for profile in session.scalars(select(DownloadProfile)))

    # Indexing adds the episodes; the waiting steps then number and adopt the files.
    _index(session, collections["Veritasium"], ["vid-aaaaaaa", "vid-bbbbbbb", "vid-ccccccc", "vid-ddddddd", "vid-fffffff"])
    _index(session, collections["Lofi"], ["vid-eeeeeee"])
    _adopt_waiting(session)

    run = session.get(type(run), run.id)
    assert run.status == "finished"
    assert (run.counts["adopted"], run.counts["suppressed"]) == (3, 1)
    downloads = list(session.scalars(select(EpisodeMediaDownload)))
    assert sorted(download.artifact_status for download in downloads) == ["absent", "available", "available", "available"]
    suppressed = next(download for download in downloads if download.artifact_status == "absent")
    assert suppressed.automatic_retry_suppressed
    channel = next(profile for profile in profiles if profile.name == "Media server")
    numbers = {
        episode.source_slug: get_episode_index_assignments(episode, channel.id)
        for episode in collections["Veritasium"].episodes
    }
    assert numbers["vid-aaaaaaa"] == {"day": 1} and numbers["vid-bbbbbbb"] == {"day": 2}
    # Veritasium was on in Pinchflat and the person chose to switch Download Profiles on; Lofi was off.
    enabled = {profile.collection.title: profile.enable_profile for profile in session.scalars(select(DownloadProfile))}
    assert enabled == {"Veritasium": True, "Lofi": False}

    links = session.scalar(select(ImportLink).where(ImportLink.kind == "collection").limit(1))
    assert links is not None
    rerun = _run(session, imports.ImportOptions(enable_download_profiles=True))
    _adopt_waiting(session)
    rerun = session.get(type(rerun), rerun.id)
    assert rerun.counts.get("collections_created", 0) == 0 and rerun.counts.get("profiles_created", 0) == 0
    assert rerun.counts.get("adopted", 0) == 0 and rerun.counts["already_adopted"] == 3
    assert len(list(session.scalars(select(EpisodeMediaDownload)))) == 4
    assert len(list(session.scalars(select(Collection)))) == 2
    assert session.scalar(select(ImportStep).where(ImportStep.status == "waiting")) is None


def test_a_change_made_in_vodloft_is_kept_and_a_newly_mapped_setting_comes_over(installation, monkeypatch):
    from backend.db.models import CollectionLocalMediaProfile
    from backend.services import imports
    import importer.pinchflat.mapping as mapping

    session, _applied = installation
    # An earlier VODLoft had no 1440p and reported it as not supported yet.
    monkeypatch.setitem(mapping._RESOLUTIONS, "1440p", ("format_1080p", "unsupported", "No 1440p yet"))
    _run(session, imports.ImportOptions())
    lists = session.scalar(select(CollectionLocalMediaProfile).where(CollectionLocalMediaProfile.name == "Lists"))
    channel = session.scalar(select(CollectionLocalMediaProfile).where(CollectionLocalMediaProfile.name == "Media server"))
    assert lists.preferred_format == "format_1080p"
    channel.subtitle_mode = "embed"
    session.commit()

    # This VODLoft maps 1440p.
    monkeypatch.setitem(mapping._RESOLUTIONS, "1440p", ("format_1440p", "exact", None))
    view = imports.preview(session, pinchflat.IMPORTER, imports.ImportOptions())
    changes = {profile["name"]: profile["changes"] for profile in view["profiles"]}
    assert changes["Lists"]["updated"] == ["preferred_format"]
    assert changes["Lists"]["newly_mapped"] == ["preferred_resolution"]
    assert changes["Media server"]["kept"] == ["subtitle_mode"]

    run = _run(session, imports.ImportOptions())
    session.refresh(lists)
    session.refresh(channel)
    assert lists.preferred_format == "format_1440p"
    assert channel.subtitle_mode == "embed"
    kinds = {(entry["kind"], entry["subject"]) for entry in run.report}
    assert ("newly_mapped", "Lists") in kinds and ("kept", "Media server") in kinds
    assert len(list(session.scalars(select(CollectionLocalMediaProfile)))) == 2


def test_an_import_from_a_read_only_media_folder_changes_no_file(installation, tmp_path, monkeypatch):
    from backend.db.models import Collection, EpisodeMediaDownload
    from backend.services import imports
    from conftest import folder_snapshot, read_only_folder

    session, _applied = installation
    downloads = tmp_path / "downloads"
    before = folder_snapshot(downloads)
    refused = read_only_folder(monkeypatch, downloads)

    for _ in range(2):
        _run(session, imports.ImportOptions(enable_download_profiles=True))
        for collection in session.scalars(select(Collection)):
            if not collection.episodes:
                _index(session, collection, ["vid-aaaaaaa", "vid-bbbbbbb"] if collection.title == "Veritasium" else ["vid-eeeeeee"])
        _adopt_waiting(session)

    downloads_made = list(session.scalars(select(EpisodeMediaDownload)))
    assert sum(download.artifact_status == "available" for download in downloads_made) == 3
    assert folder_snapshot(downloads) == before
    assert refused == []


def test_sponsorblock_and_unmapped_options_come_over(tmp_path):
    from backend.services.imports import _with_checked_options

    path = _pinchflat_db(tmp_path / "pinchflat.db")
    connection = sqlite3.connect(path)
    connection.execute("UPDATE media_profiles SET sponsorblock_behaviour = 'remove', "
                       "sponsorblock_categories = '[\"sponsor\", \"intro\"]' WHERE id = 1")
    connection.commit()
    connection.close()
    options = tmp_path / "yt-dlp-configs"
    options.mkdir()
    (options / "media-profile-1-config.txt").write_text("--xattrs\n--exec 'echo done'\n--embed-chapters\n")

    plan = plan_import(read_pinchflat(path), option_directory=options)

    channel, playlist = plan.profiles
    veritasium, _lofi = plan.collections
    assert veritasium.download_profile["sponsorblock_enabled"] is True
    assert veritasium.download_profile["sponsorblock_segments"]["sponsor"] == "cut"
    assert veritasium.download_profile["sponsorblock_segments"]["intro"] == "cut"
    assert veritasium.download_profile["sponsorblock_segments"]["outro"] == "keep"
    assert "sponsorblock_behaviour" not in {warning.subject for warning in channel.warnings}
    assert channel.settings["ytdlp_options"].splitlines() == [
        "--xattrs  # media-profile-1-config.txt",
        '--exec "echo done"  # media-profile-1-config.txt',
        "--embed-chapters  # media-profile-1-config.txt",
    ]
    assert "ytdlp_options" not in playlist.settings

    # VODLoft keeps the lines its own check passes, and reports the others with the reason.
    checked = _with_checked_options(plan).profiles[0]
    assert checked.settings["ytdlp_options"].splitlines() == [
        "--xattrs  # media-profile-1-config.txt", "--embed-chapters  # media-profile-1-config.txt",
    ]
    refused = [warning.message for warning in checked.warnings if warning.subject == "yt-dlp options"]
    assert any(message.startswith('--exec "echo done"') and "Runs other programs" in message for message in refused)
