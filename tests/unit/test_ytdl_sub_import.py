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
        "/downloads/{{ collection_title }}/Season {{ '%02d' | format(season_number | int) }}"
        "/s{{ '%02d' | format(season_number | int) }}.e{{ date | strftime('%y') }}{{ month }}{{ day }}"
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
    # A subscription with several links is the first channel's, with each other link a link season: nothing is left out.
    beato = collections["Rick Beato"]
    assert beato.url == "https://www.youtube.com/@RickBeato"
    assert [(link.url, link.title, link.season_number) for link in beato.link_seasons] == [("https://www.youtube.com/@rickbeato240", "@rickbeato240", None)]
    assert not any(warning.subject == "links" for warning in beato.warnings)
    assert collections["NOVA PBS"].link_seasons == ()


def test_a_tv_show_collection_keeps_its_seasons_and_the_highest_keeps_a_shared_video(tmp_path):
    plan = _plan(_write(tmp_path, EXAMPLE + """
    "~Guitar Specials":
      s00_url: "https://www.youtube.com/watch?v=special"
      s01_url: "https://www.youtube.com/c/BeyondTheGuitar"
      s02_url:
        - "https://www.youtube.com/playlist?list=PLone"
        - "https://www.youtube.com/playlist?list=PLtwo"
"""))

    collections = {collection.title: collection for collection in plan.collections}
    # The channel is the collection; its own playlists are link seasons, the highest season first.
    guitar = collections["Beyond the Guitar"]
    assert guitar.url == "https://www.youtube.com/c/BeyondTheGuitar"
    assert [(link.title, link.season_number) for link in guitar.link_seasons] == [("Music Videos", 2)]
    # The channel's own season keeps its videos in none of the playlists.
    assert (guitar.loose_season.title, guitar.loose_season.season_number) == ("Videos", 1)
    specials = collections["Guitar Specials"]
    assert specials.url == "https://www.youtube.com/c/BeyondTheGuitar"
    assert [(link.url, link.title, link.season_number) for link in specials.link_seasons] == [
        ("https://www.youtube.com/playlist?list=PLone", "Season 2", 2), ("https://www.youtube.com/playlist?list=PLtwo", "Season 2", 2),
        # A single video is a season of its own too, so nothing the subscription had is left out.
        ("https://www.youtube.com/watch?v=special", "Specials", 0),
    ]
    assert not any(warning.subject == "links" for warning in specials.warnings)


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
      remove_chapters_regex: ["^Intro$", "(unclosed"]
      allow_chapters_from_comments: true
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
    # ytdl-sub's base preset saves the info file beside each video.
    assert profile.settings["save_info_json"] is True
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
    # ytdl-sub keeps the video's own chapters unless embed_chapters is turned off.
    assert (collection.download_profile["keep_chapters"], collection.download_profile["cut_chapters"]) == (True, ["^Intro$"])
    subjects = {warning.subject for warning in collection.warnings}
    assert {"throttle_protection", "ytdl_options extractor_args", "remove_chapters_regex",
            "allow_chapters_from_comments"} <= subjects
    assert [setting.key for setting in plan.settings] == ["downloads.filename_restriction_mode", "ytdlp.cookies"]
    assert any(warning.subject == "Some Band" and "Releases tab" in warning.message for warning in plan.warnings)


# ytdl-sub's own music example, examples/music_subscriptions.yaml, shortened.
MUSIC = """
__preset__:
  overrides:
    music_directory: "/music"

YouTube Full Albums:
  = Lofi:
    "Game Chops": "https://www.youtube.com/playlist?list=PLBsm_SagFMmdWnCnrNtLjA9kzfrRkto4i"

SoundCloud Discography:
  = Chill Hop:
    "UKNOWY": "https://soundcloud.com/uknowymunich"

Bandcamp:
  = Lofi:
    "Emily Hopkins": "https://emilyharpist.bandcamp.com/"
"""


def test_a_discography_becomes_an_artist_creator_with_a_music_profile(tmp_path):
    plan = _plan(_write(tmp_path, MUSIC), ("/music", "/downloads/music"))

    profile = next(profile for profile in plan.profiles if profile.name == "Bandcamp")
    assert (profile.name, profile.settings.get("type", "collection"), profile.settings["collection_scope"]) == ("Bandcamp", "collection", "music")
    assert profile.settings["preferred_format"] == "format_audio_only"
    assert profile.output_template == (
        "/downloads/music/{{ artist }}/[{{ year }}] {{ album }}/{{ track_number_padded }} - {{ title }}.ext"
    )
    collections = {collection.title: collection for collection in plan.collections}
    hopkins = collections["Emily Hopkins"]
    assert (hopkins.url, hopkins.creator, hopkins.settings["type"], hopkins.settings["genre"]) == (
        "https://emilyharpist.bandcamp.com/", True, "music", "Lofi",
    )
    assert collections["UKNOWY"].profile_external_id == "preset:SoundCloud Discography"
    assert plan.download_folder == "/music"
    assert not any(warning.subject == "Game Chops" for warning in plan.warnings)


def test_full_albums_are_split_into_tracks_by_their_chapters(tmp_path):
    downloads = tmp_path / "downloads"
    # A music preset's archive sits in the music folder, beside every artist's folder.
    (downloads / "music").mkdir(parents=True)
    (downloads / "music" / ".ytdl-sub-Game Chops-download-archive.json").write_text(json.dumps({
        "album-1": {"upload_date": "2020-05-01", "extractor": "youtube", "file_names": [
            "Game Chops/[2020] Lofi Album/02 - Second.mp3", "Game Chops/[2020] Lofi Album/folder.jpg",
            "Game Chops/[2020] Lofi Album/01 - First.mp3",
        ]},
    }))
    plan = _plan(_write(tmp_path / "config", MUSIC), ("/music", "/downloads/music"), downloads)

    albums = next(collection for collection in plan.collections if collection.title == "Game Chops")
    assert (albums.creator, albums.link_seasons, albums.settings["type"], albums.settings["split_chapters"]) == (False, (), "music", True)
    profile = next(profile for profile in plan.profiles if profile.external_id == albums.profile_external_id)
    assert profile.output_template == (
        "/downloads/music/{{ artist }}/[{{ year }}] {{ album }}/{{ track_number_padded }} - {{ title }}.ext"
    )
    # Each track is a part of the album's video, in the order the tracks play in.
    assert [(file.media_site_id, file.part, file.path.rsplit("/", 1)[1]) for file in plan.files
            if file.collection_external_id == albums.external_id] == [
        ("album-1", 1, "01 - First.mp3"), ("album-1", 2, "02 - Second.mp3"),
    ]


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

@pytest.fixture(autouse=True)
def forget_sites():
    """Each test's Sources tell the Sites of their links afresh."""
    from backend.services import sites

    sites._site_of.cache_clear()
    yield
    sites._site_of.cache_clear()


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


def test_an_imported_tv_show_collection_has_its_playlists_as_seasons_in_ytdl_subs_numbers(installation):
    from backend.db.models import Collection
    from backend.services import imports

    session = installation
    run = imports.start_run(session, ytdl_sub.IMPORTER, imports.ImportOptions(collections=("subscription:Beyond the Guitar",)))
    session.commit()
    imports.apply_run(run.id)
    session.expire_all()

    guitar = session.scalar(select(Collection).where(Collection.title == "Beyond the Guitar"))
    assert guitar.sharing_url == "https://www.youtube.com/c/BeyondTheGuitar"
    assert [(link.url, link.season.season_number, link.season.name) for link in guitar.lists] == [
        ("https://www.youtube.com/playlist?list=PLE62gWlWZk5NWVAVuf0Lm9jdv_-_KXs0W", 2, "Music Videos"),
    ]
    # Its files are named by ytdl-sub's numbers, so those stay.
    assert (guitar.link_seasons, guitar.custom_season_order) == ("selected", True)
    # As in ytdl-sub, the channel's season holds what is in no playlist, and a video is in one season.
    assert (guitar.channel_season, guitar.repeat_videos) == ("unlisted", "one_season")


def _artist_import(monkeypatch):
    """The music example uploaded, and a yt-dlp Source that knows Emily Hopkins on Bandcamp."""
    from backend.services import import_uploads
    from sources import registry
    from sources.contract import CreatorDetails, Feature, Names, SectionKind, SectionRef, SectionType, Site

    subscriptions = MUSIC.encode()
    import_uploads.begin_upload(ytdl_sub.IMPORTER, [("subscriptions.yaml", len(subscriptions))], include_secrets=False)
    import_uploads.write_chunk(ytdl_sub.IMPORTER, "subscriptions.yaml", 0, subscriptions)
    import_uploads.finish_upload(ytdl_sub.IMPORTER)
    ytdlp = registry._sources["ytdlp"]

    class Artists(type(ytdlp)):
        domains = ("bandcamp.com",)
        features = ytdlp.features | {Feature.CREATORS}
        sites = (Site("bandcamp", "Bandcamp", ("bandcamp.com",), creators=True, creator_names=Names("artist", "artists"), link_seasons=True,
                      section_types=(SectionType("album", SectionKind.LIST, Names("album", "albums")),
                                     SectionType("single", SectionKind.ITEM, Names("single", "singles")))),)

        def creator_of(self, url):
            return "https://emilyharpist.bandcamp.com"

        def creator_details(self, ref, progress=lambda step: None):
            album = SectionRef(ref="album/harp", url="https://emilyharpist.bandcamp.com/album/harp", title="Harp",
                               type=self.sites[0].section_type("album"))
            single = SectionRef(ref="track/one", url="https://emilyharpist.bandcamp.com/track/one", title="One",
                                type=self.sites[0].section_type("single"))
            return CreatorDetails(ref="emilyharpist", url="https://emilyharpist.bandcamp.com", title="Emily Hopkins",
                                  sections=(album, single), music=True)

    monkeypatch.setattr(registry, "_sources", {**registry._sources, "ytdlp": Artists()})


def test_an_imported_discography_adds_the_artist_with_each_album_a_season(installation, monkeypatch):
    from backend.db.models import Creator, Collection, CollectionLocalMediaProfile
    from backend.services import imports

    session = installation
    _artist_import(monkeypatch)
    run = imports.start_run(session, ytdl_sub.IMPORTER, imports.ImportOptions(collections=("subscription:Emily Hopkins",)))
    session.commit()
    imports.apply_run(run.id)
    session.expire_all()

    creator = session.scalar(select(Creator))
    collection = session.scalar(select(Collection))
    assert (creator.title, collection.creator_id, collection.type, collection.genre) == ("Emily Hopkins", creator.id, "music", "Lofi")
    # The artist's page is the collection, and each album a link season of it once it is indexed.
    assert (collection.sharing_url, collection.kind, collection.link_seasons) == ("https://emilyharpist.bandcamp.com", "channel", "selected")
    assert session.scalar(select(CollectionLocalMediaProfile.collection_scope).where(CollectionLocalMediaProfile.name == "Bandcamp")) == "music"


def test_an_import_without_creators_makes_the_artist_one_plain_collection(installation, monkeypatch):
    from backend.db.models import Creator, Collection
    from backend.services.link_seasons import collection_new_lists
    from backend.services import imports

    session = installation
    _artist_import(monkeypatch)
    options = imports.ImportOptions(collections=("subscription:Emily Hopkins",), as_creators=False)
    assert imports.ImportOptions.from_dict(options.to_dict()).as_creators is False
    run = imports.start_run(session, ytdl_sub.IMPORTER, options)
    session.commit()
    imports.apply_run(run.id)
    session.expire_all()

    assert session.scalar(select(Creator)) is None
    collection = session.scalar(select(Collection))
    assert (collection.title, collection.type, collection.creator_id) == ("Emily Hopkins", "music", None)
    # Every album is a season, the ones to come too.
    assert (collection.sharing_url, collection.link_seasons) == ("https://emilyharpist.bandcamp.com", "selected")
    assert [(setting.key, setting.action) for setting in collection_new_lists(collection)] == [("album", "add")]


def test_an_imported_collection_joins_the_creator_behind_its_link(installation, monkeypatch):
    from backend.db.models import Creator, Collection
    from backend.services import imports
    from sources import registry
    from sources.contract import CreatorDetails, Feature, Names, SectionKind, SectionRef, SectionType, Site

    session = installation
    ytdlp = registry._sources["ytdlp"]

    class Creators(type(ytdlp)):
        features = ytdlp.features | {Feature.CREATORS}
        sites = (Site("youtube", "YouTube", ("youtube.com",), creators=True),)

        def creator_of(self, url):
            return "BeyondTheGuitar"

        def creator_details(self, ref, progress=lambda step: None):
            return CreatorDetails(ref=ref, url="https://www.youtube.com/c/BeyondTheGuitar", title="Beyond the Guitar", sections=(
                SectionRef(ref="videos", url="https://www.youtube.com/c/BeyondTheGuitar", type=SectionType("videos", SectionKind.FEED, Names("video", "videos"))),
            ))

    monkeypatch.setattr(registry, "_sources", {**registry._sources, "ytdlp": Creators()})
    run = imports.start_run(session, ytdl_sub.IMPORTER, imports.ImportOptions(collections=("subscription:Beyond the Guitar",)))
    session.commit()
    imports.apply_run(run.id)
    session.expire_all()

    creator = session.scalar(select(Creator))
    guitar = session.scalar(select(Collection))
    assert (guitar.creator_id, creator.title) == (creator.id, "Beyond the Guitar")
    # The playlist stays a season of the collection.
    assert [link.ref for link in guitar.lists] == ["PLE62gWlWZk5NWVAVuf0Lm9jdv_-_KXs0W"]


def test_only_an_import_that_knows_creators_offers_them(tmp_path):
    from importer.pinchflat import IMPORTER as PINCHFLAT  # noqa: F401  (registers it)
    from importer.contract import ImportPlan

    assert _plan(_write(tmp_path, EXAMPLE)).creators is True
    assert ImportPlan(importer="pinchflat").creators is False


def test_a_tv_show_collection_of_only_playlists_holds_only_them(tmp_path):
    plan = _plan(_write(tmp_path, EXAMPLE + """
    "~Mixed Playlists":
      s01_name: "Firsts"
      s01_url: "https://www.youtube.com/playlist?list=PLfirst"
      s02_url:
        - "https://www.youtube.com/playlist?list=PLsecond"
        - "https://www.youtube.com/watch?v=single"
"""))

    mixed = {collection.title: collection for collection in plan.collections}["Mixed Playlists"]
    # No channel to make the collection of: it has no link of its own, and every link is a season.
    assert (mixed.links_only, mixed.url) == (True, "https://www.youtube.com/playlist?list=PLfirst")
    assert sorted((link.url, link.title, link.season_number) for link in mixed.link_seasons) == [
        ("https://www.youtube.com/playlist?list=PLfirst", "Firsts", 1),
        ("https://www.youtube.com/playlist?list=PLsecond", "Season 2", 2),
        ("https://www.youtube.com/watch?v=single", "Season 2", 2),
    ]
    assert not any(warning.subject == "links" for warning in mixed.warnings)


def test_backwards_episode_orderings_number_the_newest_first(tmp_path):
    plan = _plan(_write(tmp_path, """
__preset__:
  overrides:
    tv_show_directory: "/tv_shows"

Plex TV Show by Date:
  = Documentaries:
    "~NOVA PBS":
      url: "https://www.youtube.com/@novapbs"
      tv_show_by_date_episode_ordering: "upload-month-day-reversed"
"""))

    profile = plan.profiles[0]
    assert profile.output_template == (
        "/downloads/{{ collection_title }}/Season {{ year }}/s{{ year }}.e{{ day_of_year_reversed }}"
        "{{ '%02d' | format('day' | custom_index(per=date, start=99, step=-1)) }} - {{ title }}.ext"
    )
    assert [index.key for index in profile.custom_indexes] == ["day"]
    assert not any(warning.subject == "tv_show_by_date_episode_ordering" for warning in plan.collections[0].warnings)


def test_the_day_of_year_counts_back_from_the_end_of_the_year():
    from datetime import date

    from backend.utils.output_template import _date_substitutions

    assert (_date_substitutions(date(2026, 1, 1))["day_of_year"], _date_substitutions(date(2026, 1, 1))["day_of_year_reversed"]) == ("001", "365")
    assert _date_substitutions(date(2026, 12, 31))["day_of_year_reversed"] == "001"
    assert _date_substitutions(date(2028, 1, 1))["day_of_year_reversed"] == "366"


def test_a_date_range_with_an_end_date_downloads_between_two_dates(tmp_path):
    config = """
presets:
  closed_period:
    preset:
      - "Jellyfin TV Show by Date"
    date_range:
      after: "20200101"
      before: "20221231"
    overrides:
      tv_show_directory: "/tv_shows"
"""
    plan = _plan(_write(tmp_path, """
closed_period:
  "NOVA PBS": "https://www.youtube.com/@novapbs"
""", config))

    from backend.services.import_filters import filters_from_plan

    collection = plan.collections[0]
    (published,) = [item for item in filters_from_plan(collection.download_profile, seasons=False) if item.field == "published"]
    assert (published.starting_from.isoformat(), published.until.isoformat()) == ("2020-01-01", "2022-12-31")
    assert not any(warning.subject == "date_range" for warning in collection.warnings)


def test_an_own_episode_title_and_plot_become_the_profiles_metadata_templates(tmp_path):
    config = """
presets:
  titled:
    preset:
      - "Jellyfin TV Show by Date"
    overrides:
      tv_show_directory: "/tv_shows"
      episode_title: "{upload_date_standardized} - {title}"
      episode_plot: "{description}"
"""
    plan = _plan(_write(tmp_path, """
titled:
  "NOVA PBS": "https://www.youtube.com/@novapbs"
""", config))

    settings = plan.profiles[0].settings
    assert settings["episode_title_template"] == "{{ date }} - {{ title }}"
    assert settings["episode_description_template"] == "{{ description }}"


MUSIC_VIDEOS = """
__preset__:
  overrides:
    music_video_directory: "/music_videos"

Jellyfin Music Videos:
  = Pop:
    "Rick Astley": "https://www.youtube.com/@RickAstleyYT"
"""


def test_an_artists_music_videos_become_a_collection_of_their_creator(tmp_path):
    plan = _plan(_write(tmp_path, MUSIC_VIDEOS), ("/music_videos", "/downloads/music_videos"))

    assert not any(warning.subject == "Rick Astley" for warning in plan.warnings)
    videos = next(collection for collection in plan.collections if collection.title == "Rick Astley")
    # A plain Music collection that joins the creator behind its link, so a playlist works too.
    assert (videos.url, videos.creator, videos.artist, videos.settings["type"], videos.settings["genre"]) == (
        "https://www.youtube.com/@RickAstleyYT", False, "Rick Astley", "music", "Pop",
    )
    profile = next(profile for profile in plan.profiles if profile.external_id == videos.profile_external_id)
    assert profile.output_template == "/downloads/music_videos/{{ artist }}/{{ title }}.ext"
    assert (profile.settings["episode_nfo"], profile.settings["show_nfo"], profile.settings["metadata_mode"]) == (
        "music_video", False, "embed_and_nfo",
    )
    assert plan.download_folder == "/music_videos"


ARTIST = """
__preset__:
  overrides:
    music_directory: "/media/music"
    music_video_directory: "/media/music_videos"

Bandcamp:
  = Lofi:
    "Emily Hopkins": "https://emilyharpist.bandcamp.com/"

YouTube Full Albums:
  = Lofi:
    "Game Chops": "https://www.youtube.com/@GameChops"

Jellyfin Music Videos:
  = Lofi:
    "Emily Hopkins": "https://www.youtube.com/playlist?list=PLharp"
    "Game Chops": "https://www.youtube.com/@GameChops"
  = Pop:
    "+ Rick Astley":
      Music Videos:
        - "https://www.youtube.com/playlist?list=PLrick"
      Concerts:
        - "https://www.youtube.com/watch?v=live1"
        - "https://www.youtube.com/watch?v=live2"
"""


def test_an_artists_albums_and_music_videos_are_two_collections_of_one_artist(tmp_path):
    plan = _plan(_write(tmp_path, ARTIST), ("/media", "/downloads"))

    by_id = {collection.external_id: collection for collection in plan.collections}
    # The second subscription of a name is known by its presets too, so neither takes the other's files.
    assert set(by_id) == {
        "subscription:Emily Hopkins", "subscription:Game Chops", "subscription:Emily Hopkins:Jellyfin Music Videos",
        "subscription:Game Chops:Jellyfin Music Videos", "subscription:Rick Astley",
    }
    albums, videos = by_id["subscription:Emily Hopkins"], by_id["subscription:Emily Hopkins:Jellyfin Music Videos"]
    assert (albums.title, albums.artist, albums.creator) == ("Emily Hopkins albums", "Emily Hopkins", True)
    assert (videos.title, videos.artist, videos.creator) == ("Emily Hopkins music videos", "Emily Hopkins", False)
    # Albums come first, so the music videos join the artist they make.
    order = [collection.external_id for collection in plan.collections]
    assert order.index(albums.external_id) < order.index(videos.external_id)
    # The same link for both is one collection with both profiles, named after the artist.
    assert {by_id["subscription:Game Chops"].title, by_id["subscription:Game Chops:Jellyfin Music Videos"].title} == {"Game Chops"}


def test_a_music_video_map_has_each_category_as_a_link_season(tmp_path):
    plan = _plan(_write(tmp_path, ARTIST), ("/media", "/downloads"))

    assert not any(warning.subject == "Rick Astley" for warning in plan.warnings)
    rick = next(collection for collection in plan.collections if collection.external_id == "subscription:Rick Astley")
    assert (rick.links_only, rick.artist, rick.settings["type"]) == (True, "Rick Astley", "music")
    assert [(season.url, season.title, season.season_number) for season in rick.link_seasons] == [
        ("https://www.youtube.com/playlist?list=PLrick", "Music Videos", 1),
        ("https://www.youtube.com/watch?v=live1", "Concerts", 2),
        ("https://www.youtube.com/watch?v=live2", "Concerts", 2),
    ]


def test_ytdl_subs_artist_name_names_the_artist(tmp_path):
    plan = _plan(_write(tmp_path, """
Bandcamp:
  "Emily":
    preset: Bandcamp
    overrides:
      music_directory: "/music"
      url: "https://emilyharpist.bandcamp.com/"
      track_artist: "Emily Hopkins"
"""), ("/music", "/downloads/music"))

    assert [collection.artist for collection in plan.collections] == ["Emily Hopkins"]


@pytest.mark.parametrize(("preset", "url", "expected"), [
    ("Max Audio Quality", "https://www.youtube.com/@GameChops", "opus"),
    ("Max Audio Quality", "https://emilyharpist.bandcamp.com/", "mp3"),
    ("MP3 320k", "https://www.youtube.com/@GameChops", "mp3"),
])
def test_best_audio_keeps_the_sites_own_format(tmp_path, preset, url, expected):
    preset_name = "Bandcamp" if "bandcamp" in url else "YouTube Full Albums"
    plan = _plan(_write(tmp_path, f"""
__preset__:
  overrides:
    music_directory: "/music"
{preset_name} | {preset}:
  "Artist": "{url}"
"""), ("/music", "/downloads/music"))

    profile = plan.profiles[0]
    assert profile.settings["audio_format"] == expected
    assert not any(warning.subject == "audio_extract" and "saves audio as" in warning.message for warning in profile.warnings)


def test_flac_stays_flac_for_music_tracks(tmp_path):
    plan = _plan(_write(tmp_path, """
YouTube Full Albums:
  "Artist":
    overrides:
      music_directory: "/music"
      url: "https://www.youtube.com/@GameChops"
    audio_extract:
      codec: flac
"""), ("/music", "/downloads/music"))

    assert plan.profiles[0].settings["audio_format"] == "flac"


def test_an_imported_artist_keeps_ytdl_subs_name_with_their_albums_and_music_videos(installation, monkeypatch):
    from backend.services.link_seasons import collection_new_lists
    from backend.db.models import Creator, Collection
    from backend.services import import_uploads, imports
    from sources import registry
    from sources.contract import CreatorDetails, Feature, Names, SectionKind, SectionRef, SectionType, Site

    session = installation
    subscriptions = """
__preset__:
  overrides:
    music_directory: "/tv/music"
    music_video_directory: "/tv/music_videos"

Bandcamp:
  "Emily Hopkins": "https://emilyharpist.bandcamp.com/"

Jellyfin Music Videos:
  "Emily Hopkins": "https://www.youtube.com/playlist?list=PLharp"
""".encode()
    import_uploads.begin_upload(ytdl_sub.IMPORTER, [("subscriptions.yaml", len(subscriptions))], include_secrets=False)
    import_uploads.write_chunk(ytdl_sub.IMPORTER, "subscriptions.yaml", 0, subscriptions)
    import_uploads.finish_upload(ytdl_sub.IMPORTER)
    ytdlp = registry._sources["ytdlp"]

    class Artists(type(ytdlp)):
        domains = ("bandcamp.com", "youtube.com")
        features = ytdlp.features | {Feature.CREATORS}
        # A Site that tells an artist's albums from their playlists.
        sites = (Site("bandcamp", "Bandcamp", ("bandcamp.com",), creators=True, creator_names=Names("artist", "artists"), link_seasons=True,
                      section_types=(SectionType("album", SectionKind.LIST, Names("album", "albums"), albums=True),
                                     SectionType("playlist", SectionKind.LIST, Names("playlist", "playlists")))),)

        def creator_of(self, url):
            return "https://emilyharpist.bandcamp.com"

        def creator_details(self, ref, progress=lambda step: None):
            album = SectionRef(ref="album/harp", url="https://emilyharpist.bandcamp.com/album/harp", title="Harp",
                               type=self.sites[0].section_type("album"))
            playlist = SectionRef(ref="sets/favourites", url="https://emilyharpist.bandcamp.com/sets/favourites",
                                  title="Favourites", type=self.sites[0].section_type("playlist"))
            # The site names the artist by their handle; ytdl-sub by the subscription.
            return CreatorDetails(ref="emilyharpist", url="https://emilyharpist.bandcamp.com", title="emilyharpist",
                                  sections=(album, playlist), music=True)

    monkeypatch.setattr(registry, "_sources", {**registry._sources, "ytdlp": Artists()})
    run = imports.start_run(session, ytdl_sub.IMPORTER, imports.ImportOptions(collections=(
        "subscription:Emily Hopkins", "subscription:Emily Hopkins:Jellyfin Music Videos",
    )))
    session.commit()
    imports.apply_run(run.id)
    session.expire_all()

    creator = session.scalar(select(Creator))
    collections = {collection.title: collection for collection in session.scalars(select(Collection))}
    assert set(collections) == {"Emily Hopkins albums", "Emily Hopkins music videos"}
    albums, videos = collections["Emily Hopkins albums"], collections["Emily Hopkins music videos"]
    # The music videos are a playlist, which is in no creator.
    assert (creator.title, albums.creator_id, videos.creator_id) == ("Emily Hopkins", creator.id, None)
    assert (videos.type, videos.sharing_url, videos.author_name) == ("music", "https://www.youtube.com/playlist?list=PLharp", "Emily Hopkins")
    # New albums are added as they come out, as the other program did; new playlists are skipped.
    assert [(setting.key, setting.action) for setting in collection_new_lists(albums)] == [("album", "add"), ("playlist", "ignore")]


def test_albums_and_music_videos_of_differently_named_subscriptions_pair_by_their_artist(tmp_path):
    # ytdl-sub keeps only the last of two subscriptions of one name, so configurations name the artist in an override.
    plan = _plan(_write(tmp_path, """
__preset__:
  overrides:
    music_directory: "/media/music"
    music_video_directory: "/media/music_videos"

Bandcamp:
  "Emily Hopkins - Albums":
    overrides:
      url: "https://emilyharpist.bandcamp.com/"
      track_artist: "Emily Hopkins"

Jellyfin Music Videos:
  "Emily Hopkins - Videos":
    overrides:
      url: "https://www.youtube.com/playlist?list=PLharp"
      music_video_artist: "Emily Hopkins"
"""), ("/media", "/downloads"))

    assert [(collection.title, collection.artist) for collection in plan.collections] == [
        ("Emily Hopkins albums", "Emily Hopkins"), ("Emily Hopkins music videos", "Emily Hopkins"),
    ]
