"""Single videos: added by link, stored per Source, and downloaded with a Video profile."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import Feature, LinkKind, Playback, ResolvedLink, Source, VideoDetails, registry
from conftest import use_database


VIDEO_TEMPLATE = (
    "{% set output_date = date ~ ' - ' if date %}"
    "/downloads/videos/{{ author or source }}/"
    "{{ output_date }}{{ title }} [{{ slug }}].ext"
)


class VideoSource(Source):
    id = "clips"
    name = "Clips"
    domains = ("clips.example",)
    features = frozenset({Feature.VIDEOS})

    def __init__(self):
        self.titles: dict[str, str] = {}
        self.playback_requests: list[tuple[str, str]] = []

    def resolve(self, url):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return ResolvedLink(kind=LinkKind.VIDEO, slug=slug, url=url, title=f"Clip {slug}")

    def video_details(self, url):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return VideoDetails(
            slug=slug,
            url=f"https://clips.example/v/{slug}",
            title=self.titles.get(slug, f"Clip {slug}"),
            description="A clip",
            duration=61.4,
            image_url=f"https://img.clips.example/{slug}.jpg",
            author_name="A Channel",
            author_url="https://clips.example/c/a-channel",
            published_at=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
        )

    def video_playback(self, *, slug, url):
        self.playback_requests.append((slug, url))
        return Playback(url=f"https://cdn.clips.example/{slug}.mp4")

    def episode_media(self, *, slug, members_only, interactive=False):
        raise NotImplementedError

    def movie_playback(self, **_kwargs):
        raise NotImplementedError


class CollectionOnlySource(VideoSource):
    id = "collections_only"
    name = "Shows Only"
    domains = ("collections.example",)
    features = frozenset({Feature.COLLECTIONS})


@pytest.fixture
def video_sources(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    clips = registry.register(VideoSource())
    registry.register(CollectionOnlySource())
    return clips


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.api.endpoints.videos.router  # noqa: F401  (loads every model first)

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    use_database(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture
def client(video_sources, session, monkeypatch):
    from backend.api.endpoints.videos import router as video_router_module

    @contextmanager
    def db_session():
        yield session

    monkeypatch.setattr(video_router_module, "db_session", db_session)
    app = FastAPI()
    app.include_router(video_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def _video_profile(session, **overrides):
    from backend.db.models import VideoLocalMediaProfile

    profile = VideoLocalMediaProfile(
        slug="videos", name="Videos", output_template=VIDEO_TEMPLATE,
        preferred_format=overrides.pop("preferred_format", "format_1080p"), **overrides,
    )
    session.add(profile)
    session.flush()
    return profile


def test_adding_a_video_stores_it_and_adding_it_again_refreshes_it(client, video_sources, session):
    from backend.db.models import Video

    response = client.post("/api/videos", json={"url": "https://clips.example/v/abc", "sourceKey": "clips"})
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "abc"
    assert body["sourceKey"] == "clips"
    assert body["sourceFeatures"] == ["videos"]
    assert body["authorName"] == "A Channel"
    assert body["thumbnailLandscapePath"] == "https://img.clips.example/abc.jpg"

    video_sources.titles["abc"] = "Renamed"
    again = client.post("/api/videos", json={"url": "clips.example/v/abc", "sourceKey": "clips"}).json()
    assert again["id"] == body["id"]
    assert again["title"] == "Renamed"
    assert session.query(Video).count() == 1

    assert [video["id"] for video in client.get("/api/videos").json()] == [body["id"]]
    assert client.get(f"/api/videos/{body['id']}").json()["title"] == "Renamed"


def test_the_same_id_at_two_sources_is_two_videos(video_sources, session):
    from backend.services.videos import index_video

    details = video_sources.video_details("https://clips.example/v/same")
    first, created_first = index_video(session, "clips", details)
    second, created_second = index_video(session, "other", details)
    assert created_first and created_second
    assert first.id != second.id


def test_only_sources_with_videos_can_add_one(client):
    response = client.post("/api/videos", json={"url": "https://collections.example/v/x", "sourceKey": "collections_only"})
    assert response.status_code == 422
    assert "Shows Only has no single videos" in response.json()["detail"]

    unknown = client.post("/api/videos", json={"url": "https://x.example/v/x", "sourceKey": "nope"})
    assert unknown.status_code == 422


def test_deleting_a_video_removes_it(client, session):
    from backend.db.models import Video

    video_id = client.post("/api/videos", json={"url": "https://clips.example/v/gone", "sourceKey": "clips"}).json()["id"]
    assert client.delete(f"/api/videos/{video_id}").status_code == 200
    assert session.query(Video).count() == 0
    assert client.get(f"/api/videos/{video_id}").status_code == 404


def test_video_output_paths_use_the_channel_date_and_id(video_sources, session):
    from backend.services.videos import index_video
    from backend.utils.output_template import resolve_video_output_path, video_output_template_values

    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    values = video_output_template_values(video)
    assert values["source"] == "Clips"
    assert values["duration_seconds"] == "61"
    path = resolve_video_output_path(VIDEO_TEMPLATE, video=video, extension="mp4")
    assert path.as_posix().endswith("/videos/A Channel/2026-03-04 - Clip abc [abc].mp4")

    video.author_name = None
    video.published_at = None
    path = resolve_video_output_path(VIDEO_TEMPLATE, video=video, extension="mp4")
    assert path.as_posix().endswith("/videos/Clips/Clip abc [abc].mp4")


def test_video_profiles_take_audio_but_not_hls_or_collection_variables():
    from pydantic import ValidationError

    from backend.api.models.video_local_media_profile import VideoLocalMediaProfileAPICreate

    audio = VideoLocalMediaProfileAPICreate(
        name="Audio", preferred_format="format_audio_only", output_template=VIDEO_TEMPLATE,
    )
    assert audio.type == "video"
    with pytest.raises(ValidationError, match="HLS"):
        VideoLocalMediaProfileAPICreate(name="HLS", preferred_format="format_hls", output_template=VIDEO_TEMPLATE)
    with pytest.raises(ValidationError, match="collection_title"):
        VideoLocalMediaProfileAPICreate(
            name="Wrong", preferred_format="format_1080p",
            output_template="/downloads/{{ collection_title }}/{{ title }}.ext",
        )


def test_a_video_download_needs_a_video_profile(video_sources, session):
    from fastapi import HTTPException

    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.db.models import MovieLocalMediaProfile
    from backend.services.videos import index_video

    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    movie_profile = MovieLocalMediaProfile(
        slug="movies", name="Movies", output_template="/downloads/{{ title }}.ext", preferred_format="format_1080p",
    )
    session.add(movie_profile)
    session.flush()
    with pytest.raises(HTTPException) as exc:
        create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=movie_profile.id))
    assert exc.value.status_code == 422
    assert "Videos require a Video Local Media Profile" in exc.value.detail

    profile = _video_profile(session)
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    assert download.type == "video"
    assert download.file_path.endswith("/videos/A Channel/2026-03-04 - Clip abc [abc].ext")


def test_the_downloads_view_can_be_scoped_to_one_video(video_sources, session):
    from backend.api.endpoints.media_downloads.service import create_video_download, get_media_downloads_view
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services.videos import index_video

    profile = _video_profile(session)
    first, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/one"))
    second, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/two"))
    create_video_download(session, first, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    create_video_download(session, second, MediaDownloadAPICreate(local_media_profile_id=profile.id))

    views = get_media_downloads_view(session, video_id=second.id)
    assert [(view.media_slug, view.source_key, view.type) for view in views] == [("two", "clips", "video")]


def test_the_download_plan_asks_the_source_for_the_video(video_sources, session, monkeypatch):
    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services import download_plans
    from backend.services.videos import index_video
    from downloader.lifecycle import DownloadTracker
    from downloader.plan import ResolvedDownloadSource

    profile = _video_profile(session, preferred_format="format_audio_only")
    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    session.commit()

    probed = {}

    def resolve_download_source(url, **kwargs):
        probed.update(url=url, **kwargs)
        return ResolvedDownloadSource(
            url=url, format_downloaded="audio", use_hls=False, remux_to_mp4=False,
            extension="m4a", audio_only=True,
        )

    monkeypatch.setattr(download_plans, "resolve_download_source", resolve_download_source)
    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())

    assert video_sources.playback_requests == [("abc", "https://clips.example/v/abc")]
    assert probed["url"] == "https://cdn.clips.example/abc.mp4"
    assert probed["audio_only"] is True
    assert str(plan.requested_destination).endswith("/videos/A Channel/2026-03-04 - Clip abc [abc].m4a")


def test_a_ytdlp_playback_plans_a_ytdlp_download(video_sources, session, monkeypatch):
    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services import download_plans
    from backend.services.videos import index_video
    from downloader.lifecycle import DownloadTracker
    from sources import PlaybackKind

    def ytdlp_playback(*, slug, url):
        return Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp", "--cookies", "c.txt"))

    monkeypatch.setattr(video_sources, "video_playback", ytdlp_playback)
    monkeypatch.setattr(download_plans, "resolve_download_source", lambda *_a, **_k: pytest.fail("yt-dlp pages are not probed"))
    profile = _video_profile(session, preferred_format="format_720p")
    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    session.commit()

    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert plan.source.url == "https://clips.example/v/abc"
    assert plan.source.ytdlp_command[:3] == ("yt-dlp", "--cookies", "c.txt")
    assert "res:720,vcodec:h264,acodec:aac" in plan.source.ytdlp_command
    assert str(plan.requested_destination).endswith("/videos/A Channel/2026-03-04 - Clip abc [abc].mp4")


@pytest.mark.parametrize(("mode", "publish", "embedded"), [
    ("no_subtitles", None, ()),
    ("sidecar", True, ()),
    ("embed", False, ("subtitles",)),
    ("embed_and_sidecar", True, ("subtitles",)),
])
def test_a_ytdlp_download_asks_ytdlp_for_subtitles_as_the_profile_says(video_sources, session, monkeypatch, mode, publish, embedded):
    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services import download_plans
    from backend.services.videos import index_video
    from downloader.lifecycle import DownloadTracker
    from sources import PlaybackKind

    monkeypatch.setattr(video_sources, "video_playback", lambda *, slug, url: Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp",)))
    profile = _video_profile(session, subtitle_mode=mode)
    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    session.commit()

    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    subtitles = [asset for asset in plan.assets if asset.kind == "subtitle"]
    if publish is None:
        assert subtitles == []
    else:
        assert [(asset.source_format, asset.publish) for asset in subtitles] == [("ytdlp", publish)]
    assert plan.subtitle_asset_ids == embedded


def test_a_ytdlp_download_follows_the_profile_quality_and_subtitle_languages(video_sources, session, monkeypatch):
    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services import download_plans
    from backend.services.videos import index_video
    from downloader.lifecycle import DownloadTracker
    from sources import PlaybackKind

    monkeypatch.setattr(video_sources, "video_playback", lambda *, slug, url: Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp",)))
    profile = _video_profile(
        session, preferred_format="format_1440p", subtitle_mode="sidecar",
        subtitle_languages=["nl", "en"], subtitle_language_mode="listed", quality_goal="custom",
        video_codecs=[{"codec": "av1", "allowed": True}, {"codec": "vp9", "allowed": False},
                      {"codec": "h264", "allowed": True}, {"codec": "h265", "allowed": False}],
        container="mkv", audio_codec="opus", audio_language="nl",
    )
    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    profile.auto_subtitles = "always"
    session.commit()

    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    command = plan.source.ytdlp_command
    assert "res:1440,vcodec:av01,acodec:opus" in command
    assert any("av0?1|avc|h264" in part and "language^=nl" in part for part in command)
    assert plan.source.extension == "mkv"
    # A single video has no Download Profile, and follows the profile's choice for its Site.
    assert (plan.source.ytdlp_subtitles.languages, plan.source.ytdlp_subtitles.auto_generated) == (("nl", "en"), "always")


@pytest.mark.parametrize(("container", "audio_only", "embeds"), [("mkv", False, True), ("mp4", False, True), ("opus", True, False)])
def test_a_ytdlp_download_plans_thumbnails_and_nfo_in_every_container(video_sources, session, monkeypatch, container, audio_only, embeds):
    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services import download_plans
    from backend.services.videos import index_video
    from downloader.lifecycle import DownloadTracker
    from sources import PlaybackKind

    monkeypatch.setattr(video_sources, "video_playback", lambda *, slug, url: Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp",)))
    profile = _video_profile(
        session, preferred_format="format_audio_only" if audio_only else "format_1080p",
        thumbnail_mode="embed_and_sidecar", metadata_mode="embed_and_nfo", subtitle_mode="no_subtitles",
        quality_goal="custom", container="mkv" if container == "mkv" else "mp4", audio_format="opus" if audio_only else "m4a",
    )
    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    session.commit()

    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    assert plan.source.extension == container
    assets = {asset.id: asset for asset in plan.assets}
    assert assets["artwork"].url == "https://img.clips.example/abc.jpg" and assets["artwork"].publish
    assert assets["nfo"].target_suffix == ".nfo" and b"<title>" in assets["nfo"].content
    # An Opus file gets the thumbnail and NFO beside it; VODLoft can't embed into it.
    assert (plan.artwork_asset_id == "artwork") is embeds
    assert bool(plan.metadata_tags) is embeds


def test_a_frame_vodloft_took_from_the_video_is_embedded_and_kept_beside_it(video_sources, session, monkeypatch, tmp_path):
    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.services import download_plans
    from backend.services.videos import index_video
    from config import get_settings
    from downloader.lifecycle import DownloadTracker
    from sources import PlaybackKind

    monkeypatch.setattr(get_settings().download_settings, "thumbnail_root", tmp_path / "thumbnails")
    (tmp_path / "thumbnails").mkdir()
    monkeypatch.setattr(video_sources, "video_playback", lambda *, slug, url: Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp",)))
    profile = _video_profile(
        session, preferred_format="format_1080p", thumbnail_mode="embed_and_sidecar", metadata_mode="no_metadata",
        subtitle_mode="no_subtitles", quality_goal="custom", container="mp4",
    )
    video, _ = index_video(session, "clips", video_sources.video_details("https://clips.example/v/abc"))
    (tmp_path / "thumbnails" / f"{video.uuid}.jpg").write_bytes(b"frame")
    video.thumbnail_landscape_path = video.background_image_path = f"thumbnails/{video.uuid}.jpg"
    download = create_video_download(session, video, MediaDownloadAPICreate(local_media_profile_id=profile.id))
    session.commit()

    plan = download_plans.prepare_download_plan(session, download.id, DownloadTracker())
    artwork = {asset.id: asset for asset in plan.assets}["artwork"]
    assert (artwork.url, artwork.content, artwork.extension, artwork.publish) == (None, b"frame", "jpg", True)
    assert plan.artwork_asset_id == "artwork"
