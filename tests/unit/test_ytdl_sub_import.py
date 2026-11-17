"""The ytdl-sub importer: its subscriptions and presets, the converted templates, download archives and an import."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from importer import ytdl_sub
from importer.contract import ImportLocation
from importer.paths import detect_path_map, path_map_candidates
from importer.uploads import normalise_upload_path
from importer.ytdl_sub import YtdlSubReadError, read_ytdl_sub
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# ytdl-sub's own example, examples/tv_show_subscriptions.yaml, as its documentation gives it.
EXAMPLE = """
__preset__:
  overrides:
    tv_show_directory: "/tv_shows"
    only_recent_date_range: "2months"
    only_recent_max_files: 30

Plex TV Show by Date:
  = Documentaries:
    "NOVA PBS": "https://www.youtube.com/@novapbs"
    "Cosmos - What If": "https://www.youtube.com/playlist?list=PLZdXRHYAVxTJno6oFF9nLGuwXNGYHmE8U"
  = Kids | = TV-Y:
    "Jake Trains": "https://www.youtube.com/@JakeTrains"
  = Music:
    "Rick Beato":
      - "https://www.youtube.com/@RickBeato"
      - "https://www.youtube.com/@rickbeato240"
  = News | Only Recent:
    "BBC News": "https://www.youtube.com/@BBCNews"

Plex TV Show Collection:
  = Music:
    "~Beyond the Guitar":
      s01_name: "Videos"
      s01_url: "https://www.youtube.com/c/BeyondTheGuitar"
      s02_name: "Music Videos"
      s02_url: "https://www.youtube.com/playlist?list=PLE62gWlWZk5NWVAVuf0Lm9jdv_-_KXs0W"
"""

BY_DATE = (
    "{{ collection_title }}/Season {{ year }}/s{{ year }}.e{{ month }}{{ day }}"
    "{{ '%02d' | format('day' | custom_index(per=date)) }} - {{ title }}.ext"
)


def _write(folder: Path, subscriptions: str, config: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "subscriptions.yaml").write_text(subscriptions)
    if config is not None:
        (folder / "config.yaml").write_text(config)
    return folder


def _plan(folder: Path, path_map=("/tv_shows", "/downloads"), downloads: Path | None = None):
    def download_file(virtual: str):
        path = downloads / virtual.removeprefix("/downloads/") if downloads else None
        return path if path is not None and path.is_file() else None

    return ytdl_sub.IMPORTER.read(ImportLocation(
        database=folder / "subscriptions.yaml", folder=folder, path_map=path_map, download_file=download_file,
    ))


def _archive(folder: Path, entries: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f".ytdl-sub-{folder.name}-download-archive.json").write_text(json.dumps(entries))


def test_the_reader_merges_presets_indent_values_and_the_file_preset(tmp_path):
    data = read_ytdl_sub(_write(tmp_path, EXAMPLE) / "subscriptions.yaml")

    subscriptions = {sub.name: sub for sub in data.subscriptions}
    assert list(subscriptions) == ["NOVA PBS", "Cosmos - What If", "Jake Trains", "Rick Beato", "BBC News", "Beyond the Guitar"]
    news = subscriptions["BBC News"]
    assert news.presets == ("Plex TV Show by Date", "Only Recent")
    assert news.overrides["subscription_indent_1"] == "News"
    assert news.overrides["tv_show_directory"] == "/tv_shows"
    assert subscriptions["Jake Trains"].overrides["subscription_indent_2"] == "TV-Y"
    assert subscriptions["Rick Beato"].urls == ("https://www.youtube.com/@RickBeato", "https://www.youtube.com/@rickbeato240")
    assert subscriptions["Beyond the Guitar"].overrides["s02_name"] == "Music Videos"


def test_a_preset_that_is_not_known_is_refused_in_a_group_key(tmp_path):
    with pytest.raises(YtdlSubReadError, match="Max 999p"):
        read_ytdl_sub(_write(tmp_path, 'Plex TV Show by Date | Max 999p:\n  "A": "https://www.youtube.com/@a"\n')
                      / "subscriptions.yaml")


def test_tv_show_presets_become_profiles_with_the_same_folder_layout(tmp_path):
    plan = _plan(_write(tmp_path, EXAMPLE))

    profiles = {profile.name: profile for profile in plan.profiles}
    assert list(profiles) == ["Plex TV Show by Date", "Plex TV Show Collection"]
    by_date = profiles["Plex TV Show by Date"]
    assert by_date.output_template == "/downloads/" + BY_DATE
    assert by_date.original_template == "{tv_show_directory}/{tv_show_name_sanitized}/{episode_file_path}.{ext}"
    assert [index.key for index in by_date.custom_indexes] == ["day"]
    assert by_date.settings["metadata_mode"] == "embed"
    assert by_date.settings["thumbnail_mode"] == "sidecar"
    assert by_date.settings["container"] == "mp4"
    # Plex's title rule keeps the digits in VODLoft, and the report says so.
    assert any("{title_sanitized_plex}" in line and "nearly the same" in line for line in by_date.report)
    collection = profiles["Plex TV Show Collection"]
    assert collection.output_template == (
        "/downloads/{{ collection_title }}/Season 01/s01.e{{ date | strftime('%y') }}{{ month }}{{ day }}"
        "{{ '%02d' | format('day' | custom_index(per=date)) }} - {{ title }}.ext"
    )
    assert plan.download_folder == "/tv_shows"


def test_subscriptions_become_collections_with_genre_rating_and_filters(tmp_path):
    plan = _plan(_write(tmp_path, EXAMPLE))

    collections = {collection.title: collection for collection in plan.collections}
    assert collections["NOVA PBS"].settings["genre"] == "Documentaries"
    assert "content_rating" not in collections["NOVA PBS"].settings
    assert (collections["Jake Trains"].settings["genre"], collections["Jake Trains"].settings["content_rating"]) == ("Kids", "TV-Y")
    assert collections["NOVA PBS"].assets == (("poster", "/downloads/NOVA PBS/poster.jpg"), ("fanart", "/downloads/NOVA PBS/fanart.jpg"))
    news = collections["BBC News"].download_profile
    assert (news["download_days_in_past"], news["delete_older_episodes"]) == (60, True)
    assert collections["BBC News"].warnings[0].message == "today-2months becomes the last 60 days"
    assert collections["NOVA PBS"].download_profile["ep_id_type_list"] == ["ep", "short", "livestream"]
    # One link per Collection until VODLoft has collections of collections.
    assert collections["Rick Beato"].url == "https://www.youtube.com/@RickBeato"
    assert "the other link comes" in collections["Rick Beato"].warnings[0].message
    assert collections["Beyond the Guitar"].url == "https://www.youtube.com/c/BeyondTheGuitar"


def test_custom_presets_convert_simple_variables_and_report_scripts(tmp_path):
    config = """
presets:
  my_shows:
    preset:
      - "Jellyfin TV Show by Date"
      - "Max 1080p"
      - "Filter Keywords"
      - "Filter Duration"
    ytdl_options:
      cookiefile: "/config/cookies.txt"
      sleep_interval: 10
      extractor_args: {youtube: {lang: ["en"]}}
    subtitles:
      subtitles_name: "{episode_file_path}.{lang}.{subtitles_ext}"
      languages: ["en", "nl"]
      allow_auto_generated_subtitles: true
    chapters:
      remove_sponsorblock_categories: ["sponsor"]
    overrides:
      tv_show_directory: "/media/tv"
      episode_file_name: "{upload_date_standardized} - {%regex_sub('[0-9]+', '', title)}"
"""
    subscriptions = """
my_shows:
  "~Kurzgesagt":
    url: "https://www.youtube.com/@kurzgesagt/videos"
    title_exclude_keywords: ["#shorts", "Trailer"]
    filter_duration_min_s: 60
    tv_show_name: "Kurzgesagt – In a Nutshell"
YouTube Releases:
  "Some Band": "https://www.youtube.com/@band"
"""
    folder = _write(tmp_path, subscriptions, config)
    (folder / "cookies.txt").write_text("# Netscape HTTP Cookie File\n")
    plan = _plan(folder, ("/media/tv", "/downloads/tv"))

    profile = plan.profiles[0]
    assert profile.name == "my_shows"
    assert profile.output_template == "/downloads/tv/{{ collection_title }}/Season {{ year }}/{{ date }} - .ext"
    assert profile.support == "unsupported"
    assert any(line.startswith("\"{%regex_sub('[0-9]+', '', title)}\" becomes nothing (not converted)")
               for line in profile.report)
    assert (profile.settings["preferred_format"], profile.settings["metadata_mode"], profile.settings["show_nfo"]) == (
        "format_1080p", "embed_and_nfo", True)
    assert (profile.settings["subtitle_mode"], profile.settings["subtitle_languages"]) == ("sidecar", ["en", "nl"])
    collection = plan.collections[0]
    assert collection.title == "Kurzgesagt – In a Nutshell"
    rules = collection.download_profile["rules"]
    assert rules == [
        {"action": "skip", "field": "title", "pattern": r"\#shorts|trailer", "ignore_case": True},
        {"action": "skip", "field": "duration", "duration_operator": "shorter", "duration_seconds": 60},
    ]
    assert collection.download_profile["ep_id_type_list"] == ["ep"]
    assert collection.download_profile["auto_subtitles"] == "fallback"
    assert collection.download_profile["sponsorblock_segments"]["sponsor"] == "cut"
    subjects = {warning.subject for warning in collection.warnings}
    assert {"throttle_protection", "ytdl_options extractor_args"} <= subjects
    assert [setting.key for setting in plan.settings] == ["downloads.filename_restriction_mode", "ytdlp.cookies"]
    assert any(warning.subject == "Some Band" and "music" in warning.message for warning in plan.warnings)


def test_download_archives_give_every_file_by_video_id_and_find_the_folder(tmp_path):
    downloads = tmp_path / "downloads"
    _archive(downloads / "tv" / "NOVA PBS", {
        "vid-aaaa": {"upload_date": "2021-03-17", "extractor": "youtube", "playlist_index": None,
                     "file_names": ["Season 2021/s2021.e031702 - Pattys Day-thumb.jpg",
                                    "Season 2021/s2021.e031702 - Pattys Day.mp4"]},
        "vid-bbbb": {"upload_date": "2022-12-25", "extractor": "youtube", "file_names": ["tvshow.nfo"]},
    })
    folder = _write(tmp_path / "config", EXAMPLE)
    first = _plan(folder, ("/downloads", "/downloads"), downloads)
    assert first.files == ()
    assert first.probes[0] == "/tv_shows/NOVA PBS/.ytdl-sub-NOVA PBS-download-archive.json"

    candidates = path_map_candidates(first.probes, ["/downloads/tv", "/downloads/other"], root=first.download_folder)
    on_disk = {"/downloads/tv/NOVA PBS/.ytdl-sub-NOVA PBS-download-archive.json"}
    path_map, found = detect_path_map(first.probes, on_disk.__contains__, candidates)
    assert (path_map, found) == (("/tv_shows", "/downloads/tv"), 1)

    plan = _plan(folder, path_map, downloads)
    assert [(file.media_site_id, file.path, file.custom_index_values, file.title, file.published)
            for file in plan.files] == [
        ("vid-aaaa", "/downloads/tv/NOVA PBS/Season 2021/s2021.e031702 - Pattys Day.mp4", {"day": 2}, "Pattys Day",
         "2021-03-17"),
    ]
    assert plan.profiles[0].output_template == "/downloads/tv/" + BY_DATE


def test_an_upload_takes_the_subscriptions_and_config_files():
    assert normalise_upload_path("config/subscriptions.yaml", ytdl_sub.UPLOAD_FILES)[0] == "subscriptions.yaml"
    assert normalise_upload_path("config/config.yaml", ytdl_sub.UPLOAD_FILES)[0] == "config.yaml"
    assert normalise_upload_path("config/logs/run.log", ytdl_sub.UPLOAD_FILES) is None


# Applying an import -----------------------------------------------------------

@pytest.fixture
def installation(tmp_path, monkeypatch):
    """A ytdl-sub upload, its files under VODLoft's /downloads/tv, and a fake yt-dlp Source."""
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base, core
    from backend.services import import_uploads, imports
    from sources import registry
    from sources.contract import CollectionDetails, Feature, Source
    from sqlalchemy.orm import sessionmaker
    from task_manager.scheduler import scheduler

    from config import get_settings

    downloads = tmp_path / "downloads"
    monkeypatch.setattr(get_settings().download_settings, "download_root", downloads)
    monkeypatch.setattr(import_uploads, "imports_root", lambda: tmp_path / "imports")
    monkeypatch.setattr(imports, "_apply_setting", lambda key, value, session=None: None)
    show = downloads / "tv" / "NOVA PBS"
    media = show / "Season 2021" / "s2021.e031701 - First.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"media" * 20)
    _archive(show, {"vid-aaaa": {"upload_date": "2021-03-17", "extractor": "youtube",
                                 "file_names": ["Season 2021/s2021.e031701 - First.mp4"]}})

    subscriptions = EXAMPLE.encode()
    import_uploads.begin_upload(ytdl_sub.IMPORTER, [("subscriptions.yaml", len(subscriptions))], include_secrets=False)
    import_uploads.write_chunk(ytdl_sub.IMPORTER, "subscriptions.yaml", 0, subscriptions)
    import_uploads.finish_upload(ytdl_sub.IMPORTER)

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
            slug = url.rstrip("/").rsplit("/", 1)[-1].lstrip("@").replace("playlist?list=", "")
            return CollectionDetails(slug=slug, url=url, title="From YouTube", author_name="Author")

    monkeypatch.setattr(registry, "_sources", {**registry._sources, "ytdlp": FakeYtDlp()})
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(scheduler, "trigger_now", lambda **_kwargs: None)
    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", sessionmaker(bind=engine))
    return session


def test_an_import_finds_the_folder_adopts_the_archive_and_keeps_the_genre(installation):
    from backend.api.models.imports import ImportPreviewAPIRead
    from backend.db.models import (
        Collection,
        Episode,
        EpisodeMediaDownload,
        ImportStep,
        Season,
    )
    from backend.services import imports
    from backend.services.download_metadata import build_show_metadata
    from backend.types.media_types import MediaType

    session = installation
    view = ImportPreviewAPIRead.model_validate(imports.preview(session, ytdl_sub.IMPORTER, imports.ImportOptions())).model_dump()
    assert (view["path_map"]["source"], view["path_map"]["target"]) == ("/tv_shows", "/downloads/tv")
    assert view["path_map"]["found"] >= 1

    run = imports.start_run(session, ytdl_sub.IMPORTER, imports.ImportOptions(collections=("subscription:NOVA PBS",)))
    session.commit()
    imports.apply_run(run.id)
    session.expire_all()
    nova = session.scalar(select(Collection).where(Collection.title == "NOVA PBS"))
    assert (nova.genre, nova.content_rating) == ("Documentaries", None)
    assert build_show_metadata(nova).genres == ("Documentaries",)

    season = Season(collection=nova, index=1, slug="nova-2021", name="2021")
    session.add(season)
    session.add(Episode(
        source_key="ytdlp", uuid="nova-vid-aaaa", type=MediaType.EPISODE.value, collection=nova, season=season,
        index=1, episode_identifier="ep.1", slug="nova-vid-aaaa", source_slug="vid-aaaa", title="First",
        description="", duration=60, publish_status="published_final",
        sharing_url="https://www.youtube.com/watch?v=vid-aaaa",
        published_date=datetime(2021, 3, 17, 12, tzinfo=UTC),
    ))
    session.commit()
    step_ids = list(session.scalars(select(ImportStep.id).where(ImportStep.status == "waiting")))
    session.commit()
    for step_id in step_ids:
        imports.run_step(step_id)
    session.expire_all()
    download = session.scalar(select(EpisodeMediaDownload))
    assert download is not None and download.file_path.endswith("tv/NOVA PBS/Season 2021/s2021.e031701 - First.mp4")
