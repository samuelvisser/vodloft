"""Media protected by DRM: Sources mark it, downloads skip it, and a DRM failure marks it."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import VideoDetails
from sources.ytdlp import YtDlpSource, runner


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.api.endpoints.videos.router  # noqa: F401  (loads every model first)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _details(slug="abc", drm=False):
    return VideoDetails(
        slug=slug, url=f"https://clips.example/v/{slug}", title=f"Clip {slug}",
        published_at=datetime(2026, 3, 4, tzinfo=timezone.utc), drm_protected=drm,
    )


def test_ytdlp_looks_up_a_drm_video_for_its_details(monkeypatch):
    calls = []

    def run_json(*args):
        calls.append(args)
        if "--allow-unplayable-formats" not in args:
            raise runner.YtDlpError("[Site] abc: This video is DRM protected")
        return {"id": "abc", "extractor_key": "Site", "title": "Locked", "webpage_url": "https://site.example/abc"}

    monkeypatch.setattr(runner, "run_json", run_json)
    source = YtDlpSource()
    link = source.resolve("https://site.example/abc")
    assert (link.title, link.drm_protected) == ("Locked", True)
    assert source.video_details("https://site.example/abc").drm_protected is True
    assert len(calls) == 2


def test_ytdlp_marks_a_video_whose_formats_all_have_drm(monkeypatch):
    info = {"id": "abc", "extractor_key": "Site", "title": "Locked", "formats": [{"has_drm": True}, {"has_drm": True}]}
    monkeypatch.setattr(runner, "run_json", lambda *args: info)
    assert YtDlpSource().video_details("https://site.example/abc").drm_protected is True

    info["formats"].append({"has_drm": False})
    assert YtDlpSource().video_details("https://site.example/abc").drm_protected is False


def test_a_protected_video_is_stored_but_cannot_be_downloaded(session):
    from fastapi import HTTPException

    from backend.api.endpoints.media_downloads.service import create_video_download
    from backend.api.models.media_download import MovieDownloadAPICreate
    from backend.api.models.video import VideoAPIRead
    from backend.db.models import VideoLocalMediaProfile
    from backend.services.videos import index_video

    video, _ = index_video(session, "clips", _details(drm=True))
    assert VideoAPIRead.model_validate(video).drm_protected is True
    profile = VideoLocalMediaProfile(
        slug="videos", name="Videos", preferred_format="format_1080p",
        output_template="/downloads/videos/{{ title }} [{{ slug }}].ext",
    )
    session.add(profile)
    session.flush()
    with pytest.raises(HTTPException) as exc:
        create_video_download(session, video, MovieDownloadAPICreate(local_media_profile_id=profile.id))
    assert (exc.value.status_code, exc.value.detail) == (422, "Protected by DRM, cannot be downloaded")


def test_automatic_downloads_skip_protected_episodes(session):
    from backend.db.models import Show, ShowLocalMediaProfile
    from backend.db.models.download_profile import PodcastDownloadProfile
    from sources import Feature, Source
    from task_manager.tasks.helpers.listed_shows import index_listed_show
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    class Listed(Source):
        id, name, domains = "listed", "Listed", ("listed.example",)
        features = frozenset({Feature.SHOWS, Feature.EPISODE_LISTS})

        def resolve(self, url):
            return None

        def episode_media(self, **_kwargs):
            raise NotImplementedError

        def movie_playback(self, **_kwargs):
            raise NotImplementedError

        def list_episodes(self, url, *, known):
            return iter([_details("open"), _details("locked", drm=True)])

    show = Show(
        uuid="u", slug="PL1", source_key="listed", title="A playlist", sharing_url="https://listed.example/PL1",
        membership_level="FREE", type="podcast", episode_identifier="seasonal", author_name="A", author_slug="a",
    )
    session.add(show)
    session.commit()
    index_listed_show(session, show_id=show.id, source=Listed())
    local = ShowLocalMediaProfile(slug="shows", name="Shows", preferred_format="format_1080p",
                                  output_template="/downloads/{{ show_title }}/{{ episode_title }}.ext")
    profile = PodcastDownloadProfile(
        show=show, local_media_profile=local, type="podcast", enable_profile=True, ep_id_type_list=["ep"],
        download_with_countdown=False, redownload_final=False, download_days_in_past=0,
        download_episode_count=0, delete_older_episodes=False,
    )
    session.add_all([local, profile])
    session.flush()
    assert [episode.slug for episode in get_download_profile_episodes(session, profile)] == ["open"]
