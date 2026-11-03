"""The download speed limit, the night pause, and each Collection's check frequency and cookies."""
from __future__ import annotations

import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from downloader.speed import SpeedLimiter, SpeedPolicy


# ---------- Speed limit in the downloader ----------
def test_shared_limit_slows_chunks_down():
    limiter = SpeedLimiter()
    limiter.configure(lambda: SpeedPolicy(bytes_per_second=1_000_000))
    started = time.monotonic()
    slowed = [limiter.throttle(200_000) for _ in range(3)]
    elapsed = time.monotonic() - started
    assert slowed[0] is False and any(slowed[1:])
    assert 0.35 <= elapsed < 1.5


def test_full_speed_never_waits_and_shares_nothing():
    limiter = SpeedLimiter()
    assert limiter.throttle(50_000_000) is False
    assert limiter.share(3) is None


def test_ytdlp_gets_its_share_of_the_limit():
    limiter = SpeedLimiter()
    limiter.configure(lambda: SpeedPolicy(bytes_per_second=6_000_000))
    assert limiter.share(3) == 2_000_000
    assert limiter.share(0) == 6_000_000


def test_estimate_needs_a_few_measurements_and_stores_them():
    stored = []
    limiter = SpeedLimiter()
    limiter.configure(SpeedPolicy, samples=[10.0, 30.0], on_sample=stored.append)
    assert limiter.fastest_recent() is None
    limiter.record(20.0)
    assert limiter.fastest_recent() == 30.0
    assert stored == [20.0]


def test_pause_holds_downloads_until_it_ends():
    limiter = SpeedLimiter()
    until = time.time() + 0.3
    limiter.configure(lambda: SpeedPolicy(paused_until=until))
    announced = []
    limiter.wait_while_paused(waiting=announced.append)
    assert time.time() >= until
    assert announced == [until, None]


def test_pause_can_be_cancelled():
    from downloader.errors import DownloadCancelled

    limiter = SpeedLimiter()
    limiter.configure(lambda: SpeedPolicy(paused_until=time.time() + 60))
    with pytest.raises(DownloadCancelled):
        limiter.wait_while_paused(should_cancel=lambda: True)


def test_broken_policy_means_full_speed():
    limiter = SpeedLimiter()

    def broken():
        raise RuntimeError("settings unreadable")

    limiter.configure(broken)
    assert limiter.throttle(1_000) is False


# ---------- Speed limit settings ----------
@pytest.fixture
def download_settings(monkeypatch):
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "timezone", "Europe/Amsterdam")
    return settings.download_settings


@pytest.mark.parametrize(("start", "end", "clock", "paused"), [
    ("01:00", "07:00", "03:00", True),
    ("01:00", "07:00", "07:00", False),
    ("23:00", "06:00", "23:30", True),
    ("23:00", "06:00", "05:59", True),
    ("23:00", "06:00", "12:00", False),
])
def test_night_pause_window(download_settings, monkeypatch, start, end, clock, paused):
    from backend.services.speed_limit import paused_until

    monkeypatch.setattr(download_settings, "pause_at_night", True)
    monkeypatch.setattr(download_settings, "pause_start", start)
    monkeypatch.setattr(download_settings, "pause_end", end)
    hour, minute = map(int, clock.split(":"))
    now = datetime(2026, 11, 3, hour, minute, tzinfo=ZoneInfo("Europe/Amsterdam"))
    result = paused_until(now)
    assert (result is not None) is paused
    if result is not None:
        assert result > now and result - now <= timedelta(hours=24)
        assert result.strftime("%H:%M") == end


def test_night_pause_off(download_settings, monkeypatch):
    from backend.services.speed_limit import paused_until

    monkeypatch.setattr(download_settings, "pause_at_night", False)
    assert paused_until(datetime(2026, 11, 3, 3, tzinfo=timezone.utc)) is None


def test_streaming_mode_uses_half_the_measured_connection(download_settings, monkeypatch):
    from backend.services import speed_limit
    from downloader.speed import limiter

    monkeypatch.setattr(download_settings, "speed_limit_mode", "streaming")
    monkeypatch.setattr(download_settings, "pause_at_night", False)
    monkeypatch.setattr(limiter, "_samples", [])
    assert speed_limit.status().limit_mbps is None
    monkeypatch.setattr(limiter, "fastest_recent", lambda minimum_samples=3: 40_000_000)
    current = speed_limit.status()
    assert current.estimate_mbps == 40 and current.limit_mbps == 20
    monkeypatch.setattr(download_settings, "speed_limit_mode", "custom")
    monkeypatch.setattr(download_settings, "speed_limit_mbps", 3.5)
    assert speed_limit.status().limit_mbps == 3.5
    monkeypatch.setattr(download_settings, "speed_limit_mode", "full")
    assert speed_limit.status().limit_mbps is None


# ---------- Collections ----------
@pytest.fixture
def db(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _collection(session, slug="show", **values):
    from backend.db.models import Collection

    collection = Collection(
        source_key="ytdlp", uuid=f"{slug}-uuid", slug=slug, title=slug.title(), description=None,
        sharing_url=f"https://www.youtube.com/@{slug}", membership_level="FREE", type="series",
        episode_identifier="date_based", author_name="Host", author_slug="host", **values,
    )
    session.add(collection)
    session.flush()
    return collection


def test_check_frequency_decides_which_scans_include_a_collection(db, monkeypatch):
    from backend.services import check_frequency

    monkeypatch.setattr(check_frequency, "_last_full_scan", {})
    regular = _collection(db, "regular")
    rare = _collection(db, "rare", check_frequency="less_often")
    own = _collection(db, "own", check_frequency="own", check_cron="0 6 * * *")
    assert check_frequency.full_scan_due(regular) and check_frequency.full_scan_due(rare)
    assert not check_frequency.full_scan_due(own)
    check_frequency.full_scan_done(rare.id)
    assert not check_frequency.full_scan_due(rare)
    assert check_frequency.full_scan_due(rare, now=time.monotonic() + 6 * 3600)
    assert check_frequency.quick_check_minutes(rare, 15) == 360
    assert check_frequency.quick_check_minutes(regular, 15) == 15


def test_quick_checks_skip_own_schedules_and_slow_down_rare_collections(db, monkeypatch):
    from task_manager.tasks.workers.fetch_new_episodes import quick_check

    regular = _collection(db, "regular")
    rare = _collection(db, "rare", check_frequency="less_often")
    _collection(db, "own", check_frequency="own", check_cron="0 6 * * *")
    monkeypatch.setattr(quick_check, "_last_checked", {})
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)

    class Source:
        def has(self, feature):
            return True

        def quick_check_minutes(self, collections):
            return 15

    monkeypatch.setattr(quick_check, "get_source", lambda key: Source())
    due = [collection.slug for collection, _, _ in quick_check._due_collections(db, now)]
    assert due == ["regular", "rare"]
    quick_check._last_checked.update({regular.id: now, rare.id: now})
    later = now + timedelta(minutes=30)
    assert [collection.slug for collection, _, _ in quick_check._due_collections(db, later)] == ["regular"]


def test_suggestion_after_three_weeks_of_posts(db):
    from backend.db.models import Episode
    from backend.services.check_frequency import check_suggestion

    collection = _collection(db)
    assert check_suggestion(db, collection) is None
    start = datetime.now(timezone.utc) - timedelta(days=60)
    for number in range(6):
        _episode(db, collection, number, published_date=start + timedelta(days=10 * number))
    assert "every 10 days" in check_suggestion(db, collection)


def test_update_needs_a_schedule_for_its_own_schedule():
    from pydantic import ValidationError
    from backend.api.models.collection import CollectionAPIUpdate

    base = {"title": "Show", "sharingUrl": "https://example.com", "authorName": "Host"}
    with pytest.raises(ValidationError):
        CollectionAPIUpdate.model_validate({**base, "checkFrequency": "own"})
    with pytest.raises(ValidationError):
        CollectionAPIUpdate.model_validate({**base, "checkFrequency": "own", "checkCron": "every day"})
    assert CollectionAPIUpdate.model_validate({**base, "checkFrequency": "own", "checkCron": "0 6 * * *"}).check_cron == "0 6 * * *"


def test_automatic_cookies_start_after_a_sign_in_failure(db, monkeypatch):
    from backend.services import collection_cookies

    collection = _collection(db)
    assert not collection_cookies.uses_cookies(collection)

    class Source:
        name = "yt-dlp"

        def has(self, feature):
            return True

        def has_cookies(self):
            return True

        def needs_cookies(self, error):
            return "Sign in to confirm" in error

    episode = _episode(db, collection)
    monkeypatch.setattr(db, "get", lambda model, key: SimpleNamespace(media=episode))
    monkeypatch.setattr(collection_cookies, "get_source", lambda key: Source())
    assert not collection_cookies.note_failed_download(db, 1, "HTTP Error 404")
    assert collection_cookies.note_failed_download(db, 1, "ERROR: Sign in to confirm you're not a bot")
    assert collection_cookies.uses_cookies(collection)
    assert not collection_cookies.uses_cookies(collection, now=datetime.now(timezone.utc) + timedelta(days=8))

    collection.cookies_mode = "never"
    assert not collection_cookies.uses_cookies(collection)
    collection.cookies_mode = "always"
    collection.cookies_needed_until = None
    assert collection_cookies.uses_cookies(collection)


def _episode(session, collection, number=0, **values):
    from backend.db.models import Episode, Season

    season = session.query(Season).filter_by(collection_id=collection.id).first()
    if season is None:
        season = Season(collection=collection, index=1, slug=f"{collection.slug}-s1", name="One")
        session.add(season)
    episode = Episode(
        source_key="ytdlp", uuid=f"e{number}", type="episode", collection=collection, season=season, index=number,
        episode_identifier=f"ep.{number}", slug=f"e{number}", title=f"E{number}", publish_status="published_final",
        sharing_url=f"https://www.youtube.com/watch?v=e{number}", **values,
    )
    session.add(episode)
    session.flush()
    return episode


def test_ytdlp_tells_sign_in_errors_apart():
    from sources.ytdlp.source import YtDlpSource

    source = YtDlpSource.__new__(YtDlpSource)
    assert source.needs_cookies("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser")
    assert source.needs_cookies("ERROR: Join this channel to get access to members-only content")
    assert not source.needs_cookies("ERROR: HTTP Error 503: Service Unavailable")
