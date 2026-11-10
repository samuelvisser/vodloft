"""Channels and playlists from a Source that lists their episodes, as collections with a season per year."""
from __future__ import annotations

from profile_filters import filter_rows, only_types

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import (
    Feature, LinkKind, Playback, PlaybackKind, CollectionDetails, Site, SiteSetting, SiteSettings, Source, VideoDetails, registry,
)
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource
from sources.ytdlp.source import collection_url
from conftest import use_database
from backend.services.sites import _site_of


def _video(slug: str, year: int, month: int = 1, day: int = 1) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://www.youtube.com/watch?v={slug}", title=f"Video {slug}",
        duration=60.0, image_url=f"https://i.ytimg.com/vi/{slug}/hq.jpg", author_name="A Channel",
        published_at=datetime(year, month, day, tzinfo=timezone.utc),
    )


class ListedSource(Source):
    id = "listed"
    name = "Listed"
    domains = ("listed.example",)
    features = frozenset({Feature.COLLECTIONS, Feature.EPISODE_LISTS})

    def __init__(self):
        self.videos: list[VideoDetails] = []
        self.known_seen: list[frozenset[str]] = []

    def resolve(self, url):
        return None

    def episode_media(self, **_kwargs):
        raise NotImplementedError

    def movie_playback(self, **_kwargs):
        raise NotImplementedError

    def collection_details(self, url):
        return CollectionDetails(slug="PL1", url=url, title="A playlist", author_name="A Channel")

    def list_episodes(self, url, *, known):
        self.known_seen.append(known)
        return iter([video for video in self.videos if video.slug not in known])

    def video_playback(self, *, slug, url):
        return Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp",))


@pytest.fixture
def listed(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(ListedSource())


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _collection(session, slug="PL1", source_key="listed"):
    from backend.db.models import Collection

    collection = Collection(
        uuid=f"uuid-{slug}", slug=slug, source_key=source_key, title="A playlist",
        sharing_url=f"https://www.youtube.com/playlist?list={slug}", membership_level="FREE",
        type="podcast", episode_identifier="seasonal", author_name="A Channel", author_slug="a-channel",
    )
    session.add(collection)
    session.commit()
    return collection


def test_listed_episodes_get_a_season_per_upload_year(listed, session, monkeypatch):
    from backend.db.models import Episode
    from task_manager.events import transactional
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    emitted: list[str] = []
    monkeypatch.setattr(transactional, "emit_event", lambda name, _data: emitted.append(name))
    collection = _collection(session)
    listed.videos = [_video("c", 2024, 3), _video("a", 2023, 5), _video("b", 2023, 9)]
    assert index_listed_collection(session, collection_id=collection.id, source=listed) == 3

    episodes = session.query(Episode).order_by(Episode.index).all()
    assert [(e.slug, e.episode_identifier, e.season.name, e.index) for e in episodes] == [
        ("a", "ep.S2023E01", "2023", 1),
        ("b", "ep.S2023E02", "2023", 2),
        ("c", "ep.S2024E01", "2024", 3),
    ]
    assert {e.publish_status for e in episodes} == {"published_final"}
    assert all(e.metadata_is_final and e.source_key == "listed" for e in episodes)
    assert episodes[0].sharing_url == "https://www.youtube.com/watch?v=a"
    assert [(s.season_number, s.index) for s in sorted(collection.seasons, key=lambda s: s.index)] == [(2023, 1), (2024, 2)]
    assert emitted.count("episode.added") == 3
    assert emitted.count("episode.published_final") == 3
    assert emitted.count("season.added") == 2


def test_listed_episodes_can_be_identified_by_date_or_number(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    by_date, numbered = _collection(session, "UC1"), _collection(session, "PL1")
    by_date.episode_identifier, numbered.episode_identifier = "date_based", "numbered"
    session.commit()
    listed.videos = [_video("c", 2024, 3), _video("a", 2023, 5), _video("b", 2023, 5)]
    index_listed_collection(session, collection_id=by_date.id, source=listed)
    session.commit()
    index_listed_collection(session, collection_id=numbered.id, source=listed)
    session.commit()

    def identifiers(collection):
        episodes = session.query(Episode).filter_by(collection_id=collection.id).order_by(Episode.index)
        return [(e.source_slug, e.episode_identifier, e.season.name) for e in episodes]

    # Videos uploaded at the same moment: the second one is auxiliary.
    assert identifiers(by_date) == [
        ("a", "ep.2023-05-01T00:00:00.000000", "2023"),
        ("b", "aux.1", "2023"),
        ("c", "ep.2024-03-01T00:00:00.000000", "2024"),
    ]
    assert identifiers(numbered) == [("a", "ep.1", "2023"), ("b", "ep.2", "2023"), ("c", "ep.3", "2024")]

    listed.videos.append(_video("d", 2024, 6))
    index_listed_collection(session, collection_id=numbered.id, source=listed)
    assert identifiers(numbered)[-1] == ("d", "ep.4", "2024")


def test_later_episodes_keep_existing_numbers_and_older_years_sort_first(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session)
    listed.videos = [_video("b", 2024, 6)]
    index_listed_collection(session, collection_id=collection.id, source=listed)
    session.commit()

    # A newer video, plus an older one added to the playlist later.
    listed.videos += [_video("c", 2024, 9), _video("a", 2022, 1)]
    assert index_listed_collection(session, collection_id=collection.id, source=listed) == 2
    assert listed.known_seen[-1] == frozenset({"b"})
    identifiers = {e.slug: e.episode_identifier for e in session.query(Episode)}
    assert identifiers == {"b": "ep.S2024E01", "a": "ep.S2022E01", "c": "ep.S2024E02"}
    session.refresh(collection)
    assert [s.name for s in sorted(collection.seasons, key=lambda s: s.index)] == ["2022", "2024"]

    assert index_listed_collection(session, collection_id=collection.id, source=listed) == 0


def test_the_same_video_in_two_collections_is_two_episodes(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    channel, playlist = _collection(session, "UC1"), _collection(session, "PL1")
    listed.videos = [_video("x", 2024)]
    index_listed_collection(session, collection_id=channel.id, source=listed)
    session.commit()
    index_listed_collection(session, collection_id=playlist.id, source=listed)
    session.commit()

    assert sorted(e.slug for e in session.query(Episode)) == ["PL1-x", "x"]
    # Each collection still knows the video by the Source's own id.
    assert index_listed_collection(session, collection_id=playlist.id, source=listed) == 0
    assert listed.known_seen[-1] == frozenset({"x"})


def test_a_scan_of_a_listed_collection_skips_the_daily_wire(listed, session, monkeypatch):
    import asyncio

    from backend.db.models import Episode
    from task_manager.tasks.workers.fetch_new_episodes import service

    collection = _collection(session)
    listed.videos = [_video("a", 2024)]

    async def no_daily_wire(*_args, **_kwargs):
        pytest.fail("A listed collection must not be fetched from The Daily Wire")

    def no_token(_self):
        pytest.fail("A scan of listed collections must not sign in to The Daily Wire")

    monkeypatch.setattr(service, "_fetch_collection", no_daily_wire)
    monkeypatch.setattr(service.DeviceAuthClient, "get_token", no_token)
    result = asyncio.run(service.run_fetch_new_episodes(session, collection_id=collection.id))
    assert result.collections[0].episodes_found == 1
    assert session.query(Episode).count() == 1


class _Progress:
    def __init__(self):
        self.messages: list[str] = []
        self.found: list[int] = []

    def set(self, _percentage, message, meta=None):
        self.messages.append(message)
        if meta is not None:
            self.found.append(meta["found"])


def test_a_dry_run_lists_a_listed_collection_without_saving(listed, session):
    import asyncio

    from backend.db.models import Episode
    from task_manager.tasks.workers.fetch_new_episodes import service

    collection = _collection(session)
    listed.videos = [_video("a", 2024), _video("b", 2024, 2)]
    progress = _Progress()
    result = asyncio.run(service.run_fetch_new_episodes(session, collection_id=collection.id, dry_run=True, progress=progress))

    assert result.dry_run and result.episodes_found == 0
    assert session.query(Episode).count() == 0
    assert progress.messages[-1] == "Dry run complete for 'PL1': 2 new episodes (nothing saved)"


def test_listing_reports_each_new_episode(listed, session):
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session)
    listed.videos = [_video("a", 2024), _video("b", 2024, 2)]
    progress = _Progress()
    index_listed_collection(session, collection_id=collection.id, source=listed, progress=progress)

    assert progress.messages == [
        "Listing the episodes of 'A playlist' at Listed",
        "Found 1 new episode of 'A playlist' at Listed",
        "Found 2 new episodes of 'A playlist' at Listed",
        "Saving 2 new episodes of 'A playlist'",
    ]
    assert progress.found == [1, 2]


def test_a_canceled_scan_stops_between_lookups_and_saves_nothing(lookups, session):
    from backend.db.models import Episode
    from sources import pacing
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    answers, calls = lookups
    collection = _collection(session, source_key="ytdlp")
    answers[("--flat-playlist", "--extractor-args", "youtubetab:approximate_date", collection.sharing_url)] = {"_type": "playlist", "entries": [
        {"id": slug, "ie_key": "Youtube", "url": f"https://www.youtube.com/watch?v={slug}"} for slug in ("v1", "v2")
    ]}
    for slug in ("v1", "v2"):
        answers[("--no-playlist", f"https://www.youtube.com/watch?v={slug}")] = {
            "id": slug, "extractor_key": "Youtube", "title": slug, "upload_date": "20240102",
            "webpage_url": f"https://www.youtube.com/watch?v={slug}",
        }

    def looked_up() -> int:
        return sum(1 for args in calls if args[0] == "--no-playlist")

    with pacing.request_context(should_cancel=lambda: looked_up() > 0), pytest.raises(pacing.RequestCanceled):
        index_listed_collection(session, collection_id=collection.id, source=YtDlpSource())

    assert looked_up() == 1
    assert session.query(Episode).count() == 0


def test_listed_episodes_download_through_the_page(listed, session, monkeypatch):
    from backend.db.models import CollectionLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services import download_plans
    from downloader.lifecycle import DownloadTracker
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session)
    listed.videos = [_video("a", 2024, 2, 3)]
    index_listed_collection(session, collection_id=collection.id, source=listed)
    profile = CollectionLocalMediaProfile(
        slug="collections", name="Collections", preferred_format="format_1080p",
        output_template="/downloads/shows/{{ collection_title }}/{{ season_name }}/{{ episode_title }}.ext",
    )
    session.add(profile)
    session.flush()
    episode = collection.episodes[0]
    download = EpisodeMediaDownload(
        media=episode, local_media_profile=profile, type="episode", file_path="/downloads/x.ext",
    )
    session.add(download)
    session.commit()
    monkeypatch.setattr(download_plans, "resolve_download_source", lambda *_a, **_k: pytest.fail("not probed"))

    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert plan.source.url == "https://www.youtube.com/watch?v=a"
    assert plan.source.ytdlp_command[0] == "yt-dlp"
    assert str(plan.requested_destination).endswith("/shows/A playlist/2024/Video a.mp4")


def test_a_listed_episode_whose_playback_is_protected_is_not_downloaded(listed, session, monkeypatch):
    from backend.db.models import CollectionLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services import download_plans
    from downloader import EncryptedMediaError
    from downloader.lifecycle import DownloadTracker
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session)
    listed.videos = [_video("a", 2024, 2, 3)]
    index_listed_collection(session, collection_id=collection.id, source=listed)
    profile = CollectionLocalMediaProfile(slug="collections", name="Collections", preferred_format="format_1080p", output_template="/downloads/{{ episode_title }}.ext")
    session.add(profile)
    session.flush()
    download = EpisodeMediaDownload(media=collection.episodes[0], local_media_profile=profile, type="episode", file_path="/downloads/x.ext")
    session.add(download)
    session.commit()
    monkeypatch.setattr(listed, "video_playback", lambda **_: Playback(url="https://cdn.example/drm.m3u8", drm_protected=True))

    with pytest.raises(EncryptedMediaError, match="Listed protects 'Video a' with DRM"):
        download_plans.prepare_download_plan(session, download.id, DownloadTracker())


def test_a_listed_collection_bundle_is_seasonal_and_streams_only_downloads(listed, session):
    from fastapi import HTTPException

    from backend.services.errors import ServiceError

    from backend.api.endpoints.collections.as_bundle.service import create_collection_bundle
    from backend.api.models.collection_as_bundle import CollectionAPICreateBundle

    collection = {
        "slug": "PL1", "sourceKey": "listed", "title": "A playlist", "sharingUrl": "https://listed.example/PL1",
        "membershipLevel": "HIGHEST_ALLOWED", "type": "series", "episodeIdentifier": "numbered",
        "authorName": "A Channel", "authorSlug": "a-channel",
    }
    seasons = [{"slug": "s1", "name": "Season 1"}]
    stream = {
        "title": "A playlist", "enableProfile": True, "useDownloads": True, "useSourceStream": True,
        "preferredFormat": "format_1080p", "epIdTypeList": ["ep"], "preferExactMatch": False,
    }
    with pytest.raises(HTTPException, match="downloaded files only"):
        create_collection_bundle(session, None, CollectionAPICreateBundle.model_validate({"collection": collection, "seasons": seasons, "streamProfile": stream}))
    session.rollback()

    created = create_collection_bundle(session, None, CollectionAPICreateBundle.model_validate({"collection": collection, "seasons": seasons}))
    # The episode identification is the one picked in the wizard.
    assert (created.source_key, created.episode_identifier, created.membership_level) == ("listed", "numbered", "FREE")
    assert created.model_dump(by_alias=True).get("seasons") in (None, [])

    with pytest.raises(ServiceError, match="Unknown|No Source"):
        create_collection_bundle(session, None, CollectionAPICreateBundle.model_validate({"collection": {**collection, "slug": "x", "sourceKey": "nope"}, "seasons": []}))


@pytest.fixture
def lookups(monkeypatch):
    answers: dict[tuple[str, ...], dict] = {}
    calls: list[tuple[str, ...]] = []

    def run_json(*args, **_kwargs):
        calls.append(args)
        if args not in answers:
            raise runner.YtDlpError("Video unavailable")
        return answers[args]

    monkeypatch.setattr(runner, "run_json", run_json)
    monkeypatch.setattr("sources.ytdlp.source._LISTING_PAUSE_SECONDS", 0)
    return answers, calls


def test_ytdlp_lists_new_playlist_videos_and_skips_unavailable_ones(lookups):
    answers, calls = lookups
    playlist = "https://www.youtube.com/playlist?list=PL1"
    answers[("--flat-playlist", "--extractor-args", "youtubetab:approximate_date", playlist)] = {"_type": "playlist", "entries": [
        {"id": "known1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=known1"},
        {"id": "new1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=new1"},
        {"id": "priv", "ie_key": "Youtube", "title": "[Private video]", "url": "https://www.youtube.com/watch?v=priv"},
        {"id": "gone", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=gone"},
    ]}
    answers[("--no-playlist", "https://www.youtube.com/watch?v=new1")] = {
        "id": "new1", "extractor_key": "Youtube", "title": "New", "upload_date": "20240102",
        "webpage_url": "https://www.youtube.com/watch?v=new1",
    }
    found = list(YtDlpSource().list_episodes(playlist, known=frozenset({"known1"})))
    assert [(v.slug, v.published_at.year) for v in found] == [("new1", 2024)]
    looked_up = [args[-1] for args in calls if args[0] == "--no-playlist"]
    assert looked_up == ["https://www.youtube.com/watch?v=new1", "https://www.youtube.com/watch?v=gone"]


def test_a_youtube_channel_is_its_videos_tab(lookups):
    answers, _ = lookups
    assert collection_url("https://www.youtube.com/@a-channel") == "https://www.youtube.com/@a-channel/videos"
    assert collection_url("https://www.youtube.com/@a-channel/shorts") == "https://www.youtube.com/@a-channel/shorts"
    assert collection_url("https://www.youtube.com/playlist?list=PL1") == "https://www.youtube.com/playlist?list=PL1"

    tab = "https://www.youtube.com/@a-channel/videos"
    answers[("--no-playlist", "--flat-playlist", "--playlist-items", "1", tab)] = {
        "_type": "playlist", "id": "UC1", "channel_id": "UC1", "channel": "A Channel",
        "title": "A Channel - Videos", "channel_url": "https://www.youtube.com/channel/UC1",
        "extractor_key": "YoutubeTab",
    }
    source = YtDlpSource()
    details = source.collection_details("https://www.youtube.com/@a-channel")
    assert (details.slug, details.title, details.author_name) == ("UC1", "A Channel", "A Channel")
    link = source.resolve("https://www.youtube.com/@a-channel")
    assert (link.kind, link.slug, link.url) == (LinkKind.COLLECTION, "UC1", tab)


def test_the_collection_lookup_endpoint(listed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.sources import router as source_router_module

    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    with TestClient(app) as client:
        body = client.get("/api/sources/listed/collection", params={"url": "https://listed.example/PL1"}).json()
        assert body["slug"] == "PL1"
        assert (body["authorName"], body["authorSlug"], body["sourceKey"]) == ("A Channel", "a-channel", "listed")
        assert body["probableCollectionType"] == "series"
        assert client.get("/api/sources/dailywire/show", params={"url": "https://x"}).status_code == 404


def test_the_collection_lookup_suggests_a_podcast_from_its_name(listed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.sources import router as source_router_module

    monkeypatch.setattr(ListedSource, "collection_details", lambda self, url: CollectionDetails(slug="UC1", url=url, title="PBD Podcasts"))
    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    with TestClient(app) as client:
        body = client.get("/api/sources/listed/collection", params={"url": "https://listed.example/UC1"}).json()
    assert body["probableCollectionType"] == "podcast"


def test_a_collection_bundle_can_use_an_existing_profile(listed, session):
    from backend.api.endpoints.collections.as_bundle.service import create_collection_bundle
    from backend.api.models.collection_as_bundle import CollectionAPICreateBundle
    from backend.db.models import Collection, CollectionLocalMediaProfile

    template = "/downloads/shows/{{ collection_title }}/{{ season_name }}/{{ episode_title }}.ext"
    session.add(CollectionLocalMediaProfile(slug="collections", name="Collections", preferred_format="format_1080p", output_template=template))
    session.commit()
    collection = {
        "slug": "PL1", "sourceKey": "listed", "title": "A playlist", "sharingUrl": "https://listed.example/PL1",
        "membershipLevel": "FREE", "type": "series", "episodeIdentifier": "seasonal",
        "authorName": "A Channel", "authorSlug": "a-channel",
    }
    profile = {
        "op": "update_by_slug", "slug": "collections", "name": "Collections", "preferredFormat": "format_1080p",
        "outputTemplate": template, "indexingValues": [],
    }
    created = create_collection_bundle(session, None, CollectionAPICreateBundle.model_validate({"collection": collection, "seasons": [], "localMediaProfile": profile}))
    assert session.get(Collection, created.id) is not None
    assert session.query(CollectionLocalMediaProfile).count() == 1


def test_a_bundle_that_matches_existing_files_holds_its_download_profile(listed, session, tmp_path, monkeypatch):
    from sqlalchemy import select

    from backend.api.endpoints.collections.as_bundle.service import create_collection_bundle
    from backend.api.models.collection_as_bundle import CollectionAPICreateBundle
    from backend.db.models import DownloadProfile, ExistingFileScan
    from config import get_settings

    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    (tmp_path / "YouTube").mkdir()
    payload = {
        "collection": {
            "slug": "PL1", "sourceKey": "listed", "title": "A playlist", "sharingUrl": "https://listed.example/PL1",
            "membershipLevel": "HIGHEST_ALLOWED", "type": "series", "episodeIdentifier": "numbered",
            "authorName": "A Channel", "authorSlug": "a-channel",
        },
        "seasons": [],
        "localMediaProfile": {
            "op": "create_new", "name": "YouTube", "preferredFormat": "format_1080p",
            "outputTemplate": "/downloads/YouTube/{{ collection_title }}/{{ title }}.ext",
        },
        "downloadProfile": {
            "enableProfile": True, "downloadWithCountdown": False, "redownloadFinal": False,
            "deleteOlderEpisodes": False, "autoSubtitles": "fallback", "sponsorblockEnabled": False,
            "sponsorblockSegments": {"sponsor": "keep", "intro": "keep", "outro": "keep", "selfpromo": "keep", "preview": "keep", "filler": "keep", "interaction": "keep", "hook": "keep", "music_offtopic": "keep", "poi_highlight": "keep", "chapter": "keep"}, "upgradeCheck": False, "upgradeAfterDays": 7, "upgradeRepeat": "once",
            "upgradeImprovements": [], "upgradeLengthMinutes": 5,
            "filters": [{"action": "only", "field": "types", "episodeTypes": ["ep"]}],
        },
        "existingFiles": {"folder": "/downloads/YouTube"},
    }

    create_collection_bundle(session, None, CollectionAPICreateBundle.model_validate(payload))

    profile = session.scalar(select(DownloadProfile))
    scan = session.scalar(select(ExistingFileScan))
    assert profile.enable_profile is False
    assert (scan.status, scan.folder, scan.held_download_profile_ids) == ("waiting", "/downloads/YouTube", [profile.id])


def test_a_local_media_profiles_auto_generated_subtitles_apply_where_the_site_has_them(listed, session, monkeypatch):
    from backend.db.models import CollectionLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services import download_plans
    from downloader.lifecycle import DownloadTracker
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session)
    listed.videos = [_video("a", 2024, 2, 3)]
    index_listed_collection(session, collection_id=collection.id, source=listed)
    profile = CollectionLocalMediaProfile(
        slug="collections", name="Collections", preferred_format="format_1080p", subtitle_mode="sidecar",
        subtitle_languages=["nl", "en"], output_template="/downloads/shows/{{ collection_title }}/{{ episode_title }}.ext",
    )
    session.add(profile)
    session.flush()
    # A manual download: the collection has no Download Profile.
    download = EpisodeMediaDownload(
        media=collection.episodes[0], local_media_profile=profile, type="episode", file_path="/downloads/x.ext",
    )
    session.add(download)
    session.commit()

    def choose_always():
        profile.auto_subtitles = "always"
        session.commit()

    # A site whose contract hides auto-generated subtitles doesn't get them, whatever the profile says.
    _site_of.cache_clear()
    monkeypatch.setattr(ListedSource, "sites", (Site(
        "youtube", "YouTube", ("youtube.com",), settings=SiteSettings(hides=frozenset({SiteSetting.AUTO_SUBTITLES})),
    ),))
    choose_always()
    assert download_plans.prepare_download_plan(session, download.id, DownloadTracker()).source.ytdlp_subtitles.auto_generated == "never"

    _site_of.cache_clear()
    monkeypatch.setattr(ListedSource, "sites", ())
    choose_always()
    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert (plan.source.ytdlp_subtitles.languages, plan.source.ytdlp_subtitles.auto_generated) == (("nl", "en"), "always")


def test_a_youtube_download_profile_marks_sponsors_and_adds_your_own_options(listed, session, monkeypatch):
    from backend.db.models import CollectionLocalMediaProfile
    from backend.db.models.download_profile import DownloadProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services import download_plans
    from backend.services.source_options import save_ytdlp_source_options
    from downloader import DownloadError
    from downloader.lifecycle import DownloadTracker
    from downloader.plan import YtdlpSponsorBlock
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session)
    listed.videos = [_video("a", 2024, 2, 3)]
    index_listed_collection(session, collection_id=collection.id, source=listed)
    collection.ytdlp_options = "--concurrent-fragments 8"
    profile = CollectionLocalMediaProfile(
        slug="collections", name="Collections", preferred_format="format_1080p",
        output_template="/downloads/shows/{{ collection_title }}/{{ episode_title }}.ext",
    )
    session.add(profile)
    save_ytdlp_source_options(session, "# faster\n--concurrent-fragments 4\n--extractor-args 'youtube:player_client=web'")
    session.flush()
    session.add(DownloadProfile(
        collection_id=collection.id, local_media_profile_id=profile.id, filters=filter_rows(only_types("ep")),
    ))
    download = EpisodeMediaDownload(
        media=collection.episodes[0], local_media_profile=profile, type="episode", file_path="/downloads/x.ext",
    )
    session.add(download)
    session.commit()

    # A Source that takes no yt-dlp options of its own, such as NPO Start, ignores them.
    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert "--concurrent-fragments" not in plan.source.ytdlp_command

    # A site SponsorBlock doesn't cover gets no segments; your own options apply to the yt-dlp Source.
    from sources import Feature
    monkeypatch.setattr(ListedSource, "features", ListedSource.features | {Feature.YTDLP_OPTIONS})
    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert plan.source.ytdlp_sponsorblock == YtdlpSponsorBlock()
    command = plan.source.ytdlp_command
    assert command[1:7] == (
        "--concurrent-fragments", "4", "--extractor-args", "youtube:player_client=web", "--concurrent-fragments", "8",
    )

    # A new profile's default: chapters for sponsors, intros, outros and the highlight; nothing is cut out.
    _site_of.cache_clear()
    monkeypatch.setattr(ListedSource, "sites", (Site(
        "youtube", "YouTube", ("youtube.com",), settings=SiteSettings(shows=frozenset({SiteSetting.SPONSORBLOCK})),
    ),))
    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert plan.source.ytdlp_sponsorblock == YtdlpSponsorBlock(chapter=("sponsor", "intro", "outro", "poi_highlight"))
    assert "--sponsorblock-mark" in plan.source.ytdlp_command
    assert "--sponsorblock-remove" not in plan.source.ytdlp_command

    # Options saved before a check refused them stop the download with the reason.
    save_ytdlp_source_options(session, "-o elsewhere.mp4")
    session.commit()
    with pytest.raises(DownloadError, match="yt-dlp Source can no longer be used. Line 1: -o"):
        download_plans.prepare_download_plan(session, download.id, DownloadTracker())
