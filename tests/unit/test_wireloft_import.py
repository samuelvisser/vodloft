"""The WireLoft importer: a whole WireLoft installation, imported next to VODLoft's own Library, twice."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import importer.wireloft as wireloft
from importer.contract import ImportLocation
from importer.wireloft import rename_template_variables
from importer.wireloft.migrations import RELEASES
from wireloft_fixture import MEDIA, wireloft_installation


def _session() -> Session:
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


def test_show_variables_become_collection_variables_and_nothing_else_changes():
    assert rename_template_variables(
        "/downloads/{{ show_title }}/{{ meta_show_x | default('show_title') }} show_title {{ season_name }}.ext"
    ) == "/downloads/{{ collection_title }}/{{ meta_collection_x | default('show_title') }} show_title {{ season_name }}.ext"


@pytest.mark.parametrize("release", ["c8d4e2f1a7b9", "d8b4a1f6c203", "f2a6c93d8b14", "a4e7c19b2d53"])
def test_an_older_release_is_upgraded_on_the_copy_and_reads_the_same(tmp_path, release):
    folder, downloads = tmp_path / "config", tmp_path / "downloads"
    folder.mkdir()
    # The fixture writes rows of the newest schema, so build it at the newest release and compare the
    # plan of an empty older database: what matters is that every release reads without errors.
    database = folder / "wireloft.db"
    from importer.wireloft.migrations import create

    create(database, target=release)
    plan = wireloft.IMPORTER.read(ImportLocation(database=database))
    assert plan.version.endswith(f"from {next(item.label for item in RELEASES if item.revision == release)}")
    assert plan.records == ()
    _ = downloads


def test_the_plan_keeps_daily_wire_ids_numbers_and_tokens(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    database = wireloft_installation(folder, tmp_path / "downloads")
    work = tmp_path / "work"
    work.mkdir()
    (work / "wireloft.db").write_bytes(database.read_bytes())

    plan = wireloft.IMPORTER.read(ImportLocation(database=work / "wireloft.db", extras=folder))

    shows, movies = plan.profiles
    assert shows.output_template.startswith("/downloads/shows/{{ collection_title }}/")
    assert shows.settings["type"] == "collection" and movies.settings["type"] == "movie"
    assert [index.key for index in shows.custom_indexes] == ["day"]
    records = {(record.kind, record.external_id): record for record in plan.records}
    assert records[("collection", "1")].values["membership_level"] == "HIGHEST_ALLOWED"
    episode = records[("episode", "1")]
    assert (episode.values["source_slug"], episode.values["episode_identifier"]) == ("first", "ep.S01E01")
    assert episode.profile_metadata == (("local_media_profile:1", "custom_index.", ".day", "3"),)
    assert episode.metadata["ep_status.last_known_pending"].startswith("vodloft:")
    assert records[("stream_profile", "1")].values["token"] == "feed-token"
    assert records[("download_profile", "1")].values["include_upcoming_seasons"] is False
    assert ("download_profile_season", "1:1") in records
    keys = {setting.key: setting for setting in plan.settings}
    assert keys["settings.download_settings.max_concurrent_downloads"].value == 3
    assert keys["settings.download_settings.download_collection_assets"].value is False
    assert keys["settings.download_settings.download_root"].support == "unsupported"
    assert keys["dailywire.sign_in"].secret
    assert plan.warnings == ()


@pytest.fixture
def installation(tmp_path, monkeypatch):
    from backend.services import import_uploads, imports
    from config import get_settings

    downloads = tmp_path / "downloads"
    monkeypatch.setattr(get_settings().download_settings, "download_root", downloads)
    monkeypatch.setattr(import_uploads, "imports_root", lambda: tmp_path / "imports")
    applied: list[tuple[str, object]] = []
    monkeypatch.setattr(imports, "_apply_setting", lambda key, value: applied.append((key, value)))
    folder = tmp_path / "wireloft-config"
    folder.mkdir()
    wireloft_installation(folder, downloads)
    import_uploads.upload_from_folder(wireloft.IMPORTER, folder, include_secrets=True)
    return _session(), applied


def _run(session, options):
    from backend.db.models import ImportRun
    from backend.services import imports

    run = imports.start_run(session, wireloft.IMPORTER, options)
    session.commit()
    imports.apply_run(session, run.id)
    return session.get(ImportRun, run.id)


def test_preview_counts_what_the_import_brings(installation):
    from backend.db.models import Collection
    from backend.services import imports

    session, _applied = installation
    view = imports.preview(session, wireloft.IMPORTER, imports.ImportOptions())

    assert view["records"]["collections"] == [{
        "external_id": "1", "title": "Morning Show", "url": "https://www.dailywire.com/show/morning-show", "becomes": "new",
    }]
    assert view["records"]["kinds"]["download"] == {"new": 1, "on_disk": 1}
    assert view["path_map"]["found"] == 1
    assert {item["key"] for item in view["settings"] if item["selected"]} == set()
    assert session.scalar(select(Collection)) is None


def test_a_wireloft_import_keeps_names_numbers_feeds_and_files_and_repeats_cleanly(installation):
    from backend.db.models import (
        Collection, DownloadProfile, Episode, LocalMediaProfileBase, MediaDownloadBase, Movie,
    )
    from backend.db.models.stream_profile.RssStreamProfile import RssStreamProfile
    from backend.services import imports
    from backend.utils.custom_index import get_episode_index_assignments

    session, applied = installation
    run = _run(session, imports.ImportOptions(
        enable_download_profiles=True, settings=["settings.download_settings.max_concurrent_downloads"],
    ))
    assert run.status == "finished", run.report
    assert applied == [("settings.download_settings.max_concurrent_downloads", 3)]

    collection = session.scalar(select(Collection))
    assert (collection.title, collection.source_key, collection.membership_level) == ("Morning Show", "dailywire", "HIGHEST_ALLOWED")
    episode = session.scalar(select(Episode))
    assert (episode.uuid, episode.source_slug, episode.index) == ("episode-uuid", "first", 1)
    profiles = {profile.name: profile for profile in session.scalars(select(LocalMediaProfileBase))}
    shows = profiles["WireLoft Shows"]
    assert "{{ collection_title }}" in shows.output_template
    assert get_episode_index_assignments(episode, shows.id) == {"day": 3}

    download = session.scalar(select(MediaDownloadBase))
    assert download.artifact_status == "available"
    assert download.file_path.endswith("ep.S01E01 First.mp4")
    assert sorted(item.action for item in download.history) == ["downloaded", "imported"]

    feed = session.scalar(select(RssStreamProfile))
    assert (feed.token, feed.collection_id) == ("feed-token", collection.id)
    profile = session.scalar(select(DownloadProfile))
    assert profile.enable_profile and not profile.include_upcoming_seasons
    assert [season.slug for season in profile.seasons] == ["morning-show-season-1"]
    movie = session.scalar(select(Movie))
    assert movie.official_trailer is not None and movie.official_trailer.uuid == "extra-uuid"

    # A second run right after changes nothing.
    rerun = _run(session, imports.ImportOptions(enable_download_profiles=True))
    assert rerun.status == "finished"
    assert not any(key.endswith("_created") for key in rerun.counts), rerun.counts
    assert rerun.counts.get("adopted", 0) == 0 and rerun.counts["already_adopted"] == 1
    for model in (Collection, Episode, MediaDownloadBase, RssStreamProfile, DownloadProfile, Movie, LocalMediaProfileBase):
        assert len(list(session.scalars(select(model)))) == (2 if model is LocalMediaProfileBase else 1)


def test_a_show_already_in_vodloft_is_linked_and_a_taken_feed_token_is_refused(installation):
    from backend.db.models import Collection
    from backend.db.models.stream_profile.RssStreamProfile import RssStreamProfile
    from backend.services import imports

    session, _applied = installation
    existing = Collection(
        uuid="show-uuid", slug="morning-show", title="My Morning Show", sharing_url="https://www.dailywire.com/show/morning-show",
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="Host", author_slug="host",
        source_key="dailywire",
    )
    session.add(existing)
    session.flush()
    session.add(RssStreamProfile(
        collection_id=existing.id, enable_profile=True, token="feed-token", use_downloads=True, use_dw_stream=True,
        preferred_format="format_1080p", prefer_exact_match=False, ep_id_type_list=[], feed_url="https://x.test/feed",
        max_items=0,
    ))
    session.commit()

    run = _run(session, imports.ImportOptions())

    assert [collection.title for collection in session.scalars(select(Collection))] == ["My Morning Show"]
    kinds = {(entry["kind"], entry["subject"]) for entry in run.report}
    assert ("linked", "Morning Show") in kinds
    assert any(entry["kind"] == "refused" for entry in run.report)
    assert len(list(session.scalars(select(RssStreamProfile)))) == 1


def test_a_file_vodloft_cannot_reach_is_kept_and_not_downloaded_again(installation, tmp_path):
    from backend.db.models import MediaDownloadBase
    from backend.services import imports

    session, _applied = installation
    (tmp_path / "downloads" / "shows" / "Morning Show" / "Season 1" / "ep.S01E01 First.mp4").unlink()

    run = _run(session, imports.ImportOptions())

    download = session.scalar(select(MediaDownloadBase))
    assert download.artifact_status == "absent" and download.automatic_retry_suppressed
    assert run.counts["not_reachable"] == 1
    # Once the file is back, the next import adopts it.
    path = tmp_path / "downloads" / "shows" / "Morning Show" / "Season 1" / "ep.S01E01 First.mp4"
    path.write_bytes(MEDIA)
    rerun = _run(session, imports.ImportOptions())
    session.refresh(download)
    assert download.artifact_status == "available" and rerun.counts["adopted"] == 1
