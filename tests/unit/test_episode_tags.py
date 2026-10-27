"""Episode tags that each Source declares, such as YouTube's Video, Short and Livestream."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.utils.episode import EpisodeIdentifierInfo, episode_identifier_type_predicate
from sources import MAIN_TAG, RssEpisodeType, VideoDetails, get_source, registry
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource

from test_ytdlp_shows import ListedSource


def _video(slug: str, day: int, tag: str = MAIN_TAG) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://www.youtube.com/watch?v={slug}", title=f"Video {slug}",
        published_at=datetime(2024, 1, day, tzinfo=timezone.utc), tag=tag,
    )


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


def test_each_source_declares_its_tags_with_the_main_one_first():
    daily_wire = get_source("dailywire")
    assert [tag.key for tag in daily_wire.episode_tags] == ["ep", "ep-extra", "trailer", "aux"]
    assert daily_wire.episode_tag("aux").rss_episode_type == RssEpisodeType.BONUS
    # What new Daily Wire profiles tick stays what it was.
    assert [tag.key for tag in daily_wire.episode_tags if tag.selected_by_default] == ["ep", "aux"]

    ytdlp = get_source("ytdlp")
    youtube = ytdlp.episode_tags_for("https://www.youtube.com/@a/videos")
    assert [(tag.key, tag.label, tag.selected_by_default) for tag in youtube] == [
        ("ep", "Video", True), ("short", "Short", False), ("livestream", "Livestream", True),
    ]
    assert [tag.key for tag in ytdlp.episode_tags_for("https://vimeo.com/channels/a")] == ["ep"]
    assert [tag.key for tag in get_source("npo").episode_tags] == ["ep"]
    for source in (daily_wire, ytdlp, get_source("npo")):
        assert source.episode_tags[0].main and source.episode_tags[0].key == MAIN_TAG


@pytest.mark.parametrize("info, tag", [
    ({"media_type": "short"}, "short"),
    ({"media_type": "livestream", "live_status": "was_live"}, "livestream"),
    # A finished livestream stays a livestream, whatever yt-dlp calls the media.
    ({"media_type": "video", "live_status": "was_live"}, "livestream"),
    ({"live_status": "is_upcoming"}, "livestream"),
    ({"webpage_url": "https://www.youtube.com/shorts/abc"}, "short"),
    ({"media_type": "video", "live_status": "not_live"}, "ep"),
])
def test_youtube_videos_are_tagged_from_ytdlps_full_extraction(info, tag, monkeypatch):
    monkeypatch.setattr(runner, "run_json", lambda *args: {
        "_type": "video", "id": "abc", "extractor_key": "Youtube", "title": "A video", **info,
    })
    assert YtDlpSource().video_details("https://www.youtube.com/watch?v=abc").tag == tag


def test_other_sites_only_have_videos(monkeypatch):
    monkeypatch.setattr(runner, "run_json", lambda *args: {
        "_type": "video", "id": "1", "extractor_key": "Vimeo", "title": "V", "live_status": "was_live",
    })
    assert YtDlpSource().video_details("https://vimeo.com/1").tag == MAIN_TAG


def test_other_tags_count_on_their_own_across_the_show(listed, session):
    from backend.db.models import Episode, Show
    from task_manager.tasks.helpers.listed_shows import index_listed_show

    show = Show(
        uuid="uuid-UC1", slug="UC1", source_key="listed", title="A channel",
        sharing_url="https://www.youtube.com/@a/videos", membership_level="FREE", type="podcast",
        episode_identifier="seasonal", author_name="A", author_slug="a",
    )
    session.add(show)
    session.commit()
    listed.videos = [
        _video("v1", 1), _video("s1", 2, "short"), _video("l1", 3, "livestream"), _video("v2", 4), _video("s2", 5, "short"),
    ]
    index_listed_show(session, show_id=show.id, source=listed)
    episodes = session.query(Episode).order_by(Episode.index).all()
    assert [(e.source_slug, e.episode_identifier, e.index) for e in episodes] == [
        ("v1", "ep.S2024E01", 1),
        ("s1", "short.1", 2),
        ("l1", "livestream.1", 3),
        ("v2", "ep.S2024E02", 4),
        ("s2", "short.2", 5),
    ]
    assert episodes[1].episode_type == "short"

    # A profile with Short unticked never wants the Shorts.
    wanted = session.scalars(
        select(Episode.source_slug).where(episode_identifier_type_predicate(Episode.episode_identifier, {"ep", "livestream"}))
    ).all()
    assert sorted(wanted) == ["l1", "v1", "v2"]


def test_identifiers_of_any_tag_parse():
    short = EpisodeIdentifierInfo.from_identifier("short.12")
    assert (short.type, short.episode_number, short.label) == ("short", "12", "12")
    assert EpisodeIdentifierInfo.from_identifier("livestream.3").type == "livestream"
    assert EpisodeIdentifierInfo.from_identifier("aux.1").type == "aux"
    with pytest.raises(ValueError):
        EpisodeIdentifierInfo.from_identifier("short.abc")


def test_the_episode_tags_endpoint_and_profiles_accept_source_tags():
    from backend.api.endpoints.sources import router as source_router_module
    from backend.api.models.download_profile import DownloadProfileAPICreate
    from pydantic import ValidationError

    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    client = TestClient(app)
    tags = client.get("/api/sources/ytdlp/episode-tags", params={"url": "https://youtu.be/abc"}).json()
    assert [(tag["key"], tag["rssEpisodeType"], tag["main"]) for tag in tags] == [
        ("ep", "full", True), ("short", "bonus", False), ("livestream", "full", False),
    ]
    assert client.get("/api/sources/nope/episode-tags").status_code == 404

    body = {
        "show_id": 1, "local_media_profile_id": 1, "enable_profile": True, "ep_id_type_list": ["ep", "livestream"],
        "download_with_countdown": False, "redownload_final": False, "download_days_in_past": 0,
        "download_episode_count": 0, "download_starting_from": None, "delete_older_episodes": False,
        "seasons": [], "include_upcoming_seasons": False,
    }
    assert DownloadProfileAPICreate.model_validate(body).ep_id_type_list == ["ep", "livestream"]
    with pytest.raises(ValidationError):
        DownloadProfileAPICreate.model_validate({**body, "ep_id_type_list": ["ep; drop"]})
