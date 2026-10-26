"""Channels and playlists from a Source that lists their episodes, as shows with a season per year."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import Feature, LinkKind, Playback, PlaybackKind, ShowDetails, Source, VideoDetails, registry
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource
from sources.ytdlp.source import show_url


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
    features = frozenset({Feature.SHOWS, Feature.EPISODE_LISTS})

    def __init__(self):
        self.videos: list[VideoDetails] = []
        self.known_seen: list[frozenset[str]] = []

    def resolve(self, url):
        return None

    def episode_media(self, **_kwargs):
        raise NotImplementedError

    def movie_playback(self, **_kwargs):
        raise NotImplementedError

    def show_details(self, url):
        return ShowDetails(slug="PL1", url=url, title="A playlist", author_name="A Channel")

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
    import backend.api.endpoints.shows.router  # noqa: F401  (loads every model first)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _show(session, slug="PL1", source_key="listed"):
    from backend.db.models import Show

    show = Show(
        uuid=f"uuid-{slug}", slug=slug, source_key=source_key, title="A playlist",
        sharing_url=f"https://www.youtube.com/playlist?list={slug}", membership_level="FREE",
        type="podcast", episode_identifier="seasonal", author_name="A Channel", author_slug="a-channel",
    )
    session.add(show)
    session.commit()
    return show


def _pending_events(session) -> list[str]:
    from task_manager.events.transactional import _PENDING_EVENTS_KEY

    return [event.name for event in session.info.get(_PENDING_EVENTS_KEY, [])]


def test_listed_episodes_get_a_season_per_upload_year(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    show = _show(session)
    listed.videos = [_video("c", 2024, 3), _video("a", 2023, 5), _video("b", 2023, 9)]
    assert index_listed_show(session, show_id=show.id, source=listed) == 3

    episodes = session.query(Episode).order_by(Episode.index).all()
    assert [(e.slug, e.episode_identifier, e.season.name, e.index) for e in episodes] == [
        ("a", "ep.S2023E01", "2023", 1),
        ("b", "ep.S2023E02", "2023", 2),
        ("c", "ep.S2024E01", "2024", 3),
    ]
    assert {e.publish_status for e in episodes} == {"published_final"}
    assert all(e.metadata_is_final and e.source_key == "listed" for e in episodes)
    assert episodes[0].sharing_url == "https://www.youtube.com/watch?v=a"
    assert [(s.season_number, s.index) for s in sorted(show.seasons, key=lambda s: s.index)] == [(2023, 1), (2024, 2)]
    assert _pending_events(session).count("episode.added") == 3
    assert _pending_events(session).count("episode.published_final") == 3
    assert _pending_events(session).count("season.added") == 2


def test_listed_episodes_can_be_identified_by_date_or_number(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    by_date, numbered = _show(session, "UC1"), _show(session, "PL1")
    by_date.episode_identifier, numbered.episode_identifier = "date_based", "numbered"
    session.commit()
    listed.videos = [_video("c", 2024, 3), _video("a", 2023, 5), _video("b", 2023, 5)]
    index_listed_show(session, show_id=by_date.id, source=listed)
    session.commit()
    index_listed_show(session, show_id=numbered.id, source=listed)
    session.commit()

    def identifiers(show):
        episodes = session.query(Episode).filter_by(show_id=show.id).order_by(Episode.index)
        return [(e.source_slug, e.episode_identifier, e.season.name) for e in episodes]

    # Videos uploaded at the same moment: the second one is auxiliary.
    assert identifiers(by_date) == [
        ("a", "ep.2023-05-01T00:00:00.000000", "2023"),
        ("b", "aux.1", "2023"),
        ("c", "ep.2024-03-01T00:00:00.000000", "2024"),
    ]
    assert identifiers(numbered) == [("a", "ep.1", "2023"), ("b", "ep.2", "2023"), ("c", "ep.3", "2024")]

    listed.videos.append(_video("d", 2024, 6))
    index_listed_show(session, show_id=numbered.id, source=listed)
    assert identifiers(numbered)[-1] == ("d", "ep.4", "2024")


def test_later_episodes_keep_existing_numbers_and_older_years_sort_first(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    show = _show(session)
    listed.videos = [_video("b", 2024, 6)]
    index_listed_show(session, show_id=show.id, source=listed)
    session.commit()

    # A newer video, plus an older one added to the playlist later.
    listed.videos += [_video("c", 2024, 9), _video("a", 2022, 1)]
    assert index_listed_show(session, show_id=show.id, source=listed) == 2
    assert listed.known_seen[-1] == frozenset({"b"})
    identifiers = {e.slug: e.episode_identifier for e in session.query(Episode)}
    assert identifiers == {"b": "ep.S2024E01", "a": "ep.S2022E01", "c": "ep.S2024E02"}
    session.refresh(show)
    assert [s.name for s in sorted(show.seasons, key=lambda s: s.index)] == ["2022", "2024"]

    assert index_listed_show(session, show_id=show.id, source=listed) == 0


def test_the_same_video_in_two_shows_is_two_episodes(listed, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    channel, playlist = _show(session, "UC1"), _show(session, "PL1")
    listed.videos = [_video("x", 2024)]
    index_listed_show(session, show_id=channel.id, source=listed)
    session.commit()
    index_listed_show(session, show_id=playlist.id, source=listed)
    session.commit()

    assert sorted(e.slug for e in session.query(Episode)) == ["PL1-x", "x"]
    # Each show still knows the video by the Source's own id.
    assert index_listed_show(session, show_id=playlist.id, source=listed) == 0
    assert listed.known_seen[-1] == frozenset({"x"})


def test_a_scan_of_a_listed_show_skips_the_daily_wire(listed, session, monkeypatch):
    import asyncio

    from backend.db.models import Episode
    from task_manager.tasks.workers.fetch_new_episodes import service

    show = _show(session)
    listed.videos = [_video("a", 2024)]

    async def no_daily_wire(*_args, **_kwargs):
        pytest.fail("A listed show must not be fetched from The Daily Wire")

    monkeypatch.setattr(service, "_fetch_show", no_daily_wire)
    monkeypatch.setattr(service.DeviceAuthClient, "get_token", lambda self: None)
    result = asyncio.run(service.run_fetch_new_episodes(session, show_id=show.id))
    assert result.shows[0].episodes_found == 1
    assert session.query(Episode).count() == 1


def test_listed_episodes_download_through_the_page(listed, session, monkeypatch):
    from backend.db.models import ShowLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services import download_plans
    from downloader.lifecycle import DownloadTracker
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    show = _show(session)
    listed.videos = [_video("a", 2024, 2, 3)]
    index_listed_show(session, show_id=show.id, source=listed)
    profile = ShowLocalMediaProfile(
        slug="shows", name="Shows", preferred_format="format_1080p",
        output_template="/downloads/shows/{{ show_title }}/{{ season_name }}/{{ episode_title }}.ext",
    )
    session.add(profile)
    session.flush()
    episode = show.episodes[0]
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
    from backend.db.models import ShowLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services import download_plans
    from downloader import EncryptedMediaError
    from downloader.lifecycle import DownloadTracker
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    show = _show(session)
    listed.videos = [_video("a", 2024, 2, 3)]
    index_listed_show(session, show_id=show.id, source=listed)
    profile = ShowLocalMediaProfile(slug="shows", name="Shows", preferred_format="format_1080p", output_template="/downloads/{{ episode_title }}.ext")
    session.add(profile)
    session.flush()
    download = EpisodeMediaDownload(media=show.episodes[0], local_media_profile=profile, type="episode", file_path="/downloads/x.ext")
    session.add(download)
    session.commit()
    monkeypatch.setattr(listed, "video_playback", lambda **_: Playback(url="https://cdn.example/drm.m3u8", drm_protected=True))

    with pytest.raises(EncryptedMediaError, match="Listed protects 'Video a' with DRM"):
        download_plans.prepare_download_plan(session, download.id, DownloadTracker())


def test_a_listed_show_bundle_is_seasonal_and_streams_only_downloads(listed, session):
    from fastapi import HTTPException

    from backend.api.endpoints.shows.as_bundle.service import create_show_bundle
    from backend.api.models.show_as_bundle import ShowAPICreateBundle

    show = {
        "slug": "PL1", "sourceKey": "listed", "title": "A playlist", "sharingUrl": "https://listed.example/PL1",
        "membershipLevel": "WL_ANY", "type": "series", "episodeIdentifier": "numbered",
        "authorName": "A Channel", "authorSlug": "a-channel",
    }
    seasons = [{"slug": "s1", "name": "Season 1"}]
    stream = {
        "title": "A playlist", "enableProfile": True, "useDownloads": True, "useDwStream": True,
        "preferredFormat": "format_1080p", "epIdTypeList": ["ep"], "preferExactMatch": False,
    }
    with pytest.raises(HTTPException, match="downloaded files only"):
        create_show_bundle(session, None, ShowAPICreateBundle.model_validate({"show": show, "seasons": seasons, "streamProfile": stream}))
    session.rollback()

    created = create_show_bundle(session, None, ShowAPICreateBundle.model_validate({"show": show, "seasons": seasons}))
    # The episode identification is the one picked in the wizard.
    assert (created.source_key, created.episode_identifier, created.membership_level) == ("listed", "numbered", "FREE")
    assert created.model_dump(by_alias=True).get("seasons") in (None, [])

    with pytest.raises(HTTPException, match="Unknown|No Source"):
        create_show_bundle(session, None, ShowAPICreateBundle.model_validate({"show": {**show, "slug": "x", "sourceKey": "nope"}, "seasons": []}))


@pytest.fixture
def lookups(monkeypatch):
    answers: dict[tuple[str, ...], dict] = {}
    calls: list[tuple[str, ...]] = []

    def run_json(*args):
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
    answers[("--flat-playlist", playlist)] = {"_type": "playlist", "entries": [
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
    assert show_url("https://www.youtube.com/@a-channel") == "https://www.youtube.com/@a-channel/videos"
    assert show_url("https://www.youtube.com/@a-channel/shorts") == "https://www.youtube.com/@a-channel/shorts"
    assert show_url("https://www.youtube.com/playlist?list=PL1") == "https://www.youtube.com/playlist?list=PL1"

    tab = "https://www.youtube.com/@a-channel/videos"
    answers[("--no-playlist", "--flat-playlist", "--playlist-items", "1", tab)] = {
        "_type": "playlist", "id": "UC1", "channel_id": "UC1", "channel": "A Channel",
        "title": "A Channel - Videos", "channel_url": "https://www.youtube.com/channel/UC1",
        "extractor_key": "YoutubeTab",
    }
    source = YtDlpSource()
    details = source.show_details("https://www.youtube.com/@a-channel")
    assert (details.slug, details.title, details.author_name) == ("UC1", "A Channel", "A Channel")
    link = source.resolve("https://www.youtube.com/@a-channel")
    assert (link.kind, link.slug, link.url) == (LinkKind.SHOW, "UC1", tab)


def test_the_show_lookup_endpoint(listed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.sources import router as source_router_module

    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    with TestClient(app) as client:
        body = client.get("/api/sources/listed/show", params={"url": "https://listed.example/PL1"}).json()
        assert body["slug"] == "PL1"
        assert (body["authorName"], body["authorSlug"], body["sourceKey"]) == ("A Channel", "a-channel", "listed")
        assert client.get("/api/sources/dailywire/show", params={"url": "https://x"}).status_code == 404


def test_a_show_bundle_can_use_an_existing_profile(listed, session):
    from backend.api.endpoints.shows.as_bundle.service import create_show_bundle
    from backend.api.models.show_as_bundle import ShowAPICreateBundle
    from backend.db.models import Show, ShowLocalMediaProfile

    template = "/downloads/shows/{{ show_title }}/{{ season_name }}/{{ episode_title }}.ext"
    session.add(ShowLocalMediaProfile(slug="shows", name="Shows", preferred_format="format_1080p", output_template=template))
    session.commit()
    show = {
        "slug": "PL1", "sourceKey": "listed", "title": "A playlist", "sharingUrl": "https://listed.example/PL1",
        "membershipLevel": "FREE", "type": "series", "episodeIdentifier": "seasonal",
        "authorName": "A Channel", "authorSlug": "a-channel",
    }
    profile = {
        "op": "update_by_slug", "slug": "shows", "name": "Shows", "preferredFormat": "format_1080p",
        "outputTemplate": template, "indexingValues": [],
    }
    created = create_show_bundle(session, None, ShowAPICreateBundle.model_validate({"show": show, "seasons": [], "localMediaProfile": profile}))
    assert session.get(Show, created.id) is not None
    assert session.query(ShowLocalMediaProfile).count() == 1
