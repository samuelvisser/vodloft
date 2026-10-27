"""Quick checks for new videos: the API's first page, else RSS, else yt-dlp, and only new videos looked up."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sources import Feature, ItemRef, VideoDetails, registry
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource, youtube_rss
from sources.ytdlp.youtube_api import Share, key as key_store, quota

from test_youtube_catalogue import FakeResponse, _video_item, lookups, youtube, ytdlp_dir  # noqa: F401
from test_ytdlp_shows import ListedSource

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <entry><yt:videoId>new1</yt:videoId></entry>
 <entry><yt:videoId>old1</yt:videoId></entry>
</feed>"""


@pytest.fixture
def feeds(monkeypatch):
    asked: list[dict] = []
    answers = {"status": 200}

    def get(url, params=None, timeout=None):
        asked.append(params)
        return FakeResponse(answers["status"], {}) if answers["status"] != 200 else _Feed(FEED)

    monkeypatch.setattr(youtube_rss.requests, "get", get)
    return asked, answers


class _Feed:
    ok = True
    status_code = 200

    def __init__(self, text: str):
        self.content = text.encode()


def test_with_a_key_a_check_reads_the_first_uploads_page_and_remembers_the_handle(youtube):
    youtube.playlists["UU1"] = [f"v{n}" for n in range(80)]
    source = YtDlpSource()

    first = source.latest_items("https://www.youtube.com/@a-channel/videos")
    source.latest_items("https://www.youtube.com/@a-channel/videos")

    assert len(first) == 50 and first[0] == ItemRef("v0", "https://www.youtube.com/watch?v=v0")
    # The handle is looked up once; each check costs one unit from the checks share.
    assert [name for name, _ in youtube.calls] == ["channels", "playlistItems", "playlistItems"]
    assert quota.status().usage(Share.CHECKS).used == 3


def test_with_the_quota_used_up_a_check_reads_the_rss_feed(youtube, feeds):
    asked, _ = feeds
    quota.mark_exhausted()

    found = YtDlpSource().latest_items("https://www.youtube.com/channel/UC1/videos")

    assert [item.slug for item in found] == ["new1", "old1"]
    assert asked == [{"channel_id": "UC1"}]
    assert youtube.calls == []


def test_without_a_key_a_shorts_tab_reads_its_playlist_feed(lookups, feeds):
    answers, _ = lookups
    asked, _ = feeds
    answers[("--no-playlist", "--flat-playlist", "--playlist-items", "1", "https://www.youtube.com/@a-channel/shorts")] = {
        "_type": "playlist", "id": "UC1", "channel_id": "UC1",
    }

    YtDlpSource().latest_items("https://www.youtube.com/@a-channel/shorts")

    assert asked == [{"playlist_id": "UUSH1"}]


def test_when_the_feed_fails_too_a_check_lists_the_newest_videos_with_ytdlp(lookups, feeds):
    answers, calls = lookups
    _, feed = feeds
    feed["status"] = 404
    base = "https://www.youtube.com/channel/UC1"
    answers[("--flat-playlist", "--playlist-items", "1:15", f"{base}/videos")] = {"entries": [
        {"id": "v1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v1"},
    ]}
    answers[("--flat-playlist", "--playlist-items", "1:15", f"{base}/shorts")] = {"entries": [
        {"id": "s1", "ie_key": "Youtube", "url": "https://www.youtube.com/shorts/s1"},
    ]}

    found = YtDlpSource().latest_items(f"{base}/videos")

    assert found == [ItemRef("v1", "https://www.youtube.com/watch?v=v1"), ItemRef("s1", "https://www.youtube.com/shorts/s1")]
    # The channel has no Live tab.
    assert len(calls) == 3


def test_details_of_new_videos_come_in_one_batch_and_unfinished_ones_wait(youtube):
    youtube.videos["v1"] = _video_item("v1")
    youtube.videos["up"] = _video_item("up", broadcast="upcoming", live={"scheduledStartTime": "2030-01-01T00:00:00Z"})
    items = [ItemRef(slug, f"https://www.youtube.com/watch?v={slug}") for slug in ("v1", "up", "gone")]

    details = YtDlpSource().item_details(items)

    assert details["v1"].title == "Video v1"
    assert details["up"] is None and details["gone"] is None
    assert [name for name, _ in youtube.calls] == ["videos"]


def test_without_a_key_details_come_from_ytdlp(lookups):
    answers, _ = lookups
    url = "https://vimeo.com/1"
    answers[("--no-playlist", url)] = {"id": "1", "extractor_key": "Vimeo", "title": "On Vimeo", "webpage_url": url}

    details = YtDlpSource().item_details([ItemRef("vimeo-1", url)])

    assert details["vimeo-1"].title == "On Vimeo"


def test_the_check_interval_follows_the_quota(youtube):
    source = YtDlpSource()
    shows = [(f"https://www.youtube.com/channel/UC{n}/videos", 500) for n in range(100)]
    assert 30 <= source.quick_check_minutes(shows) <= 35
    assert source.quick_check_minutes(shows[:5]) == 10
    key_store.remove()
    # RSS needs no quota.
    assert source.quick_check_minutes(shows) == 10


class QuickSource(ListedSource):
    id = "quick"
    features = frozenset({Feature.SHOWS, Feature.EPISODE_LISTS, Feature.QUICK_CHECK})

    def __init__(self):
        super().__init__()
        self.checked: list[str] = []
        self.detailed: list[list[str]] = []

    def latest_items(self, url):
        self.checked.append(url)
        return [ItemRef(video.slug, video.url) for video in self.videos]

    def item_details(self, items):
        self.detailed.append([item.slug for item in items])
        return {item.slug: next(v for v in self.videos if v.slug == item.slug) for item in items}

    def quick_check_minutes(self, shows):
        return 15


@pytest.fixture
def quick(monkeypatch):
    from task_manager.tasks.workers.fetch_new_episodes import quick_check

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    monkeypatch.setattr(quick_check, "_last_checked", {})
    return registry.register(QuickSource())


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


def _show(session, slug: str, source_key: str = "quick"):
    from backend.db.models import Show

    show = Show(
        uuid=f"uuid-{slug}", slug=slug, source_key=source_key, title=f"Show {slug}",
        sharing_url=f"https://www.youtube.com/channel/{slug}/videos", membership_level="FREE", type="podcast",
        episode_identifier="numbered", author_name="A", author_slug="a",
    )
    session.add(show)
    session.commit()
    return show


def _video(slug: str, day: int) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://www.youtube.com/watch?v={slug}", title=slug,
        published_at=datetime(2024, 1, day, tzinfo=timezone.utc),
    )


def test_a_quick_check_adds_only_new_videos_and_waits_for_the_next_interval(quick, session):
    from backend.db.models import Episode
    from task_manager.tasks.workers.fetch_new_episodes.quick_check import run_quick_check

    show = _show(session, "UC1")
    never_indexed = _show(session, "UC2")
    quick.videos = [_video("v1", 1), _video("v2", 2)]
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)

    first = run_quick_check(session, now=now)
    # Both shows were never indexed, so both get their full first index.
    assert (first.checked, first.found) == (2, 4)
    assert quick.checked == []

    quick.videos.append(_video("v3", 3))
    assert run_quick_check(session, now=now + timedelta(minutes=5)).checked == 0
    later = run_quick_check(session, now=now + timedelta(minutes=15))

    assert (later.checked, later.found) == (2, 2)
    assert quick.detailed == [["v3"], ["v3"]]
    episodes = session.query(Episode).filter(Episode.show_id == show.id).order_by(Episode.index).all()
    assert [(e.source_slug, e.episode_identifier) for e in episodes] == [("v1", "ep.1"), ("v2", "ep.2"), ("v3", "ep.3")]
    assert session.query(Episode).filter(Episode.show_id == never_indexed.id).count() == 3


def test_scheduled_scans_leave_quick_checked_shows_to_the_daily_rescan(quick, listed_too, session):
    import asyncio
    from task_manager.tasks.workers.fetch_new_episodes.service import run_fetch_new_episodes

    _show(session, "UC1")
    _show(session, "PL1", source_key="listed")
    quick.videos = [_video("v1", 1)]
    listed_too.videos = [_video("p1", 1)]

    scheduled = asyncio.run(run_fetch_new_episodes(session, show_id=0, quick_checked=False))
    rescan = asyncio.run(run_fetch_new_episodes(session, show_id=0, quick_checked=True))

    assert [show.show_slug for show in scheduled.shows] == ["PL1"]
    assert [show.show_slug for show in rescan.shows] == ["UC1"]


@pytest.fixture
def listed_too(quick):
    return registry.register(ListedSource())
