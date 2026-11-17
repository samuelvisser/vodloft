"""What a Local Media Profile writes for media servers: its filename mode, NFO files and file dates."""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from conftest import available_artifact, use_database
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode
from downloader.metadata import MediaServerMetadata, render_nfo


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    yield session
    session.close()
    engine.dispose()


def _collection(session, **seasons: str):
    from backend.db.models import Collection, Season
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    collection = Collection(
        source_key="dailywire", uuid="show-uuid", slug="show", site_ref="show-site-id", title="The Show 🎙️",
        description="A show about things", sharing_url="https://example.test/show", membership_level="FREE",
        type=CollectionType.SERIES.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host", author_slug="host",
    )
    session.add(collection)
    for index, (slug, name) in enumerate(seasons.items(), start=1):
        session.add(Season(collection=collection, index=index, slug=slug, name=name, season_number=index))
    session.flush()
    return collection


def _profile(session, **values):
    from backend.db.models import CollectionLocalMediaProfile

    profile = CollectionLocalMediaProfile(**{
        "slug": "shows", "name": "Shows", "preferred_format": "format_1080p", **values,
    }, output_template="/downloads/{{ collection_title }}/{{ title }}.ext", collection_scope="both")
    session.add(profile)
    session.flush()
    return profile


def _downloaded(session, collection, profile, season_slug: str, path: Path, slug: str):
    from backend.db.models import Episode
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.media_types import MediaType

    season = next(season for season in collection.seasons if season.slug == season_slug)
    episode = Episode(
        source_key="dailywire", uuid=f"{slug}-uuid", type="episode", collection=collection, season=season,
        index=len(collection.episodes) + 1, episode_identifier=f"ep.{len(collection.episodes) + 1}", slug=slug, title=slug, duration=60.0,
        publish_status="published_final", sharing_url=f"https://example.test/{slug}",
    )
    session.add(episode)
    session.flush()
    session.add(EpisodeMediaDownload(
        type=MediaType.EPISODE.value, media_item_id=episode.id, local_media_profile_id=profile.id,
        file_path=str(path), **available_artifact(),
    ))
    session.flush()


def test_show_and_season_nfo_files_have_the_roots_media_servers_read():
    show = ET.fromstring(render_nfo(MediaServerMetadata(kind="tvshow", title="Show", description="About")))
    season = ET.fromstring(render_nfo(MediaServerMetadata(kind="season", title="Season One", season_number=1)))

    assert (show.tag, show.findtext("title"), show.findtext("plot")) == ("tvshow", "Show", "About")
    assert (season.tag, season.findtext("title"), season.findtext("seasonnumber")) == ("season", "Season One", "1")
    assert season.find("season") is None


def test_kodi_safe_nfo_replaces_emoji_and_keeps_other_text():
    metadata = MediaServerMetadata(kind="episode", title="Live 🎉👨‍👩‍👧 tonight – café 東京", description="⭐️ Stars")

    safe = ET.fromstring(render_nfo(metadata, kodi_safe=True))
    plain = ET.fromstring(render_nfo(metadata))

    assert safe.findtext("title") == "Live □ tonight – café 東京"
    assert safe.findtext("plot") == "□ Stars"
    assert plain.findtext("title") == metadata.title


def test_show_nfo_goes_in_the_collection_folder_and_season_nfo_in_each_season_folder(db_session, tmp_path):
    from backend.services.collection_assets import collection_nfo_files

    collection = _collection(db_session, one="Season One", two="Season Two", three="Season Three", four="Season Four")
    profile = _profile(db_session, show_nfo=True, kodi_safe_nfo=True)
    root = tmp_path / "The Show"
    _downloaded(db_session, collection, profile, "one", root / "Season 01" / "a.mp4", "a")
    _downloaded(db_session, collection, profile, "one", root / "Season 01" / "b.mp4", "b")
    # Season two shares its folder with season three, and season four sits in the show's own folder.
    _downloaded(db_session, collection, profile, "two", root / "Shared" / "c.mp4", "c")
    _downloaded(db_session, collection, profile, "three", root / "Shared" / "d.mp4", "d")
    _downloaded(db_session, collection, profile, "four", root / "e.mp4", "e")

    files = {file.path: file for file in collection_nfo_files(db_session, collection, profile, root)}

    assert set(files) == {root / "tvshow.nfo", root / "Season 01" / "season.nfo"}
    show = ET.fromstring(files[root / "tvshow.nfo"].content)
    assert show.findtext("title") == "The Show □"
    assert show.find("uniqueid").text == "show-site-id"
    assert ET.fromstring(files[root / "Season 01" / "season.nfo"].content).findtext("title") == "Season One"
    assert files[root / "Season 01" / "season.nfo"].kind == f"season-{collection.seasons[0].id}"


def test_a_profile_without_show_nfo_files_wants_none(db_session, tmp_path):
    from backend.services.collection_assets import collection_nfo_files

    collection = _collection(db_session, one="Season One")
    profile = _profile(db_session)

    assert collection_nfo_files(db_session, collection, profile, tmp_path) == ()


def test_a_new_profile_follows_the_filename_mode_in_settings(db_session, monkeypatch):
    from backend.services.download_options import effective_filename_mode

    profile = _profile(db_session)
    assert profile.filename_restriction_mode == "system"
    monkeypatch.setattr(get_settings().download_settings, "filename_restriction_mode", FilenameRestrictionMode.RESTRICTED)
    assert effective_filename_mode(profile) == FilenameRestrictionMode.RESTRICTED


def test_profiles_with_the_filename_mode_in_settings_follow_settings(db_session, monkeypatch):
    from importlib import import_module

    migration = import_module("backend.db.background_migrations.versions.949968df4516_filename_mode_follows_settings")
    same = _profile(db_session, filename_restriction_mode="unrestricted")
    own = _profile(db_session, slug="car-stereo", name="Car stereo", preferred_format="format_audio_only", filename_restriction_mode="restricted")
    db_session.commit()
    monkeypatch.setattr(get_settings().download_settings, "filename_restriction_mode", FilenameRestrictionMode.UNRESTRICTED)

    asyncio.run(migration.migrate(SimpleNamespace(raise_if_canceled=lambda: None)))

    db_session.expire_all()
    assert db_session.get(type(same), same.id).filename_restriction_mode == "system"
    assert db_session.get(type(own), own.id).filename_restriction_mode == "restricted"


def test_each_profile_names_files_in_its_own_filename_mode(db_session, tmp_path):
    from backend.db.models import Episode
    from backend.utils.output_template import resolve_episode_output_path

    collection = _collection(db_session, one="Season One")
    _downloaded(db_session, collection, _profile(db_session), "one", tmp_path / "x.mp4", "what-now")
    episode = db_session.query(Episode).one()
    episode.title = "What: now?"

    def path(mode):
        return resolve_episode_output_path(
            "/downloads/{{ title }}.ext", episode=episode, filename_mode=mode, extension="mp4",
        ).name

    assert path(FilenameRestrictionMode.UNRESTRICTED) == "What: now?.mp4"
    assert path(FilenameRestrictionMode.WINDOWS) == "What： now？.mp4"
    assert path(FilenameRestrictionMode.RESTRICTED) == "What_-_now.mp4"


def test_publish_time_is_as_precise_as_vodloft_knows_it():
    from backend.services.download_metadata import publish_time

    aired = datetime(2026, 3, 4, 20, 30, tzinfo=timezone.utc)
    assert publish_time(SimpleNamespace(published_date=aired)) == aired
    assert publish_time(SimpleNamespace(release_date=date(2024, 5, 6), published_at=aired)) == datetime(
        2024, 5, 6, 12, tzinfo=timezone.utc,
    )
    assert publish_time(SimpleNamespace()) is None


def test_published_files_get_the_file_date(tmp_path):
    from downloader.coordinator import _set_file_date

    media, sidecar = tmp_path / "episode.mp4", tmp_path / "episode.nfo"
    media.write_bytes(b"media")
    sidecar.write_bytes(b"<nfo/>")
    when = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    _set_file_date(when, media, str(sidecar), tmp_path / "missing.srt")

    assert os.stat(media).st_mtime == when.timestamp()
    assert os.stat(sidecar).st_mtime == when.timestamp()
