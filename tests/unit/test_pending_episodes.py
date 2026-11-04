"""Upcoming and live videos are added with their status and followed until they are published."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sources import MAIN_TAG, EpisodePublishStatus, Feature, ItemRefresh, VideoDetails, registry
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource

from test_quick_check import _collection, session  # noqa: F401
from test_ytdlp_collections import ListedSource

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
UPCOMING_ERROR = "This live event will begin in 3 hours."


# --- yt-dlp ---------------------------------------------------------------------------------------


@pytest.fixture
def lookups(monkeypatch):
    answers: dict[tuple[str, ...], dict | str] = {}
    calls: list[tuple[str, ...]] = []

    def run_json(*args):
        calls.append(args)
        answer = answers.get(args, "Video unavailable")
        if isinstance(answer, str):
            raise runner.YtDlpError(answer)
        return answer

    monkeypatch.setattr(runner, "run_json", run_json)
    monkeypatch.setattr("sources.ytdlp.source._LISTING_PAUSE_SECONDS", 0)
    return answers, calls


def _info(video_id: str, **fields) -> dict:
    return {
        "id": video_id, "extractor_key": "Youtube", "title": video_id,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}", **fields,
    }


def _url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def test_an_upcoming_video_is_looked_up_without_formats_and_keeps_its_start(lookups):
    answers, calls = lookups
    starts = datetime.now(timezone.utc) + timedelta(hours=3)
    answers[("--no-playlist", _url("soon"))] = UPCOMING_ERROR
    answers[("--no-playlist", "--ignore-no-formats-error", _url("soon"))] = _info(
        "soon", live_status="is_upcoming", media_type="video", release_timestamp=starts.timestamp(),
    )

    [details] = YtDlpSource().refresh_metadata([ref("soon")]).details.values()

    # yt-dlp calls a premiere a video, also before it starts.
    assert (details.publish_status, details.tag) == (EpisodePublishStatus.SCHEDULED, MAIN_TAG)
    assert abs(details.scheduled_at - starts) < timedelta(seconds=1)
    assert calls == [("--no-playlist", _url("soon")), ("--no-playlist", "--ignore-no-formats-error", _url("soon"))]


def test_yt_dlps_live_status_is_the_publish_status(lookups):
    answers, _ = lookups
    late = datetime.now(timezone.utc) - timedelta(minutes=10)
    answers[("--no-playlist", "--ignore-no-formats-error", _url("late"))] = _info(
        "late", live_status="is_upcoming", media_type="livestream", release_timestamp=late.timestamp(),
    )
    answers[("--no-playlist", _url("late"))] = UPCOMING_ERROR
    answers[("--no-playlist", _url("live"))] = _info("live", live_status="is_live", media_type="livestream")
    answers[("--no-playlist", _url("ended"))] = _info("ended", live_status="post_live", media_type="livestream")
    answers[("--no-playlist", _url("done"))] = _info("done", live_status="was_live", media_type="livestream")

    found = YtDlpSource().check_pending([ref(slug) for slug in ("late", "live", "ended", "done")]).details

    assert {slug: (details.publish_status, details.tag) for slug, details in found.items()} == {
        "late": (EpisodePublishStatus.DELAYED, "livestream"),
        "live": (EpisodePublishStatus.LIVE, "livestream"),
        "ended": (EpisodePublishStatus.SOURCE_PROCESSING, "livestream"),
        "done": (EpisodePublishStatus.PUBLISHED_FINAL, "livestream"),
    }


def test_only_a_video_the_site_no_longer_has_is_gone(lookups):
    answers, calls = lookups
    answers[("--no-playlist", _url("private"))] = "Private video. Sign in if you've been granted access to this video"
    answers[("--no-playlist", _url("blocked"))] = (
        "Video unavailable. The uploader has not made this video available in your country"
    )
    answers[("--no-playlist", _url("flaky"))] = "Unable to download webpage: timed out"

    refresh = YtDlpSource().check_pending([ref(slug) for slug in ("cancelled", "private", "blocked", "flaky")])

    assert refresh.removed == {"cancelled", "private"}
    assert refresh.details == {}
    # Only the error that may be an upcoming video is looked up again without formats.
    assert [args[-1] for args in calls if "--ignore-no-formats-error" in args] == [_url("blocked"), _url("flaky")]


def test_a_video_that_is_not_upcoming_still_fails_without_formats(lookups):
    answers, _ = lookups
    answers[("--no-playlist", _url("broken"))] = "Requested format is not available"
    answers[("--no-playlist", "--ignore-no-formats-error", _url("broken"))] = _info("broken", live_status="not_live")

    assert YtDlpSource().check_pending([ref("broken")]) == ItemRefresh(details={}, removed=frozenset())


def ref(slug: str):
    from sources import ItemRef

    return ItemRef(slug, _url(slug))


# --- How often an episode is looked up ------------------------------------------------------------


def test_an_upcoming_episode_is_checked_hourly_then_often_from_15_minutes_before():
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import HOURLY, OFTEN, WHILE_LIVE, interval, is_due

    starts = NOW + timedelta(hours=2)
    assert interval("scheduled", starts, NOW) == HOURLY
    assert interval("scheduled", starts, starts - timedelta(minutes=10)) == OFTEN
    assert interval("delayed", starts, starts + timedelta(minutes=30)) == OFTEN
    # A stream more than an hour late may wait for days.
    assert interval("delayed", starts, starts + timedelta(hours=2)) == HOURLY
    assert interval("live", None, NOW) == WHILE_LIVE

    assert is_due("scheduled", starts, None, NOW)
    assert not is_due("scheduled", starts, NOW, NOW + timedelta(minutes=30))
    assert is_due("scheduled", starts, NOW, NOW + timedelta(hours=1))
    # Checked 50 minutes before the start, it is checked again right when the last 15 minutes begin.
    assert is_due("scheduled", starts, starts - timedelta(minutes=50), starts - timedelta(minutes=15))
    assert not is_due("scheduled", starts, starts - timedelta(minutes=14), starts - timedelta(minutes=13))
    assert is_due("scheduled", starts, starts - timedelta(minutes=14), starts - timedelta(minutes=12))


# --- Adding and following episodes ---------------------------------------------------------------


class PendingSource(ListedSource):
    id = "pending"
    features = frozenset({Feature.COLLECTIONS, Feature.EPISODE_LISTS, Feature.PENDING_CHECKS})

    def __init__(self):
        super().__init__()
        self.now: dict[str, VideoDetails] = {}
        self.gone: set[str] = set()
        self.checked: list[list[str]] = []

    def check_pending(self, items):
        self.checked.append([item.slug for item in items])
        return ItemRefresh(
            details={item.slug: self.now[item.slug] for item in items if item.slug in self.now},
            removed=frozenset(item.slug for item in items if item.slug in self.gone),
        )


@pytest.fixture
def pending(monkeypatch):
    from task_manager.tasks.workers.monitor_pending_episode import pending_checks

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    monkeypatch.setattr(pending_checks, "_last_checked", {})
    return registry.register(PendingSource())


@pytest.fixture
def events(monkeypatch):
    from task_manager.events import transactional

    emitted: list[tuple[str, int]] = []
    monkeypatch.setattr(transactional, "emit_event", lambda name, data: emitted.append((name, data.get("resource_id"))))
    return emitted


def _upcoming(slug: str, starts: datetime, status=EpisodePublishStatus.SCHEDULED) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://pending.example/{slug}", title=slug, published_at=starts,
        publish_status=status, scheduled_at=starts,
    )


def _pending_collection(session, *, identifier="date_based", site_checks=True):
    from backend.db.models import Site

    session.add(Site(key="tube", name="Tube", domains=["pending.example"], pending_checks=site_checks))
    collection = _collection(session, "UC1", source_key="pending")
    collection.site_key = "tube"
    collection.episode_identifier = identifier
    session.commit()
    return collection


def _add(session, collection, *found: VideoDetails) -> int:
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    added = add_listed_episodes(session, collection_id=collection.id, found=list(found))
    session.commit()
    return added


def _episode(session, slug: str):
    from backend.db.models import Episode

    session.expire_all()
    return session.query(Episode).filter(Episode.source_slug == slug).one_or_none()


def test_an_upcoming_video_is_added_with_its_status_and_not_downloaded(pending, session, events):
    collection = _pending_collection(session)
    starts = NOW + timedelta(hours=3)

    assert _add(session, collection, _upcoming("soon", starts)) == 1

    episode = _episode(session, "soon")
    assert (episode.publish_status, episode.scheduled_date.replace(tzinfo=timezone.utc)) == ("scheduled", starts)
    # The metadata refresh follows it from its publication on.
    assert not episode.metadata_is_final
    assert ("episode.added", episode.id) in events
    assert not [name for name, _ in events if name.startswith("download_profile")]


def test_a_site_can_leave_upcoming_videos_out_until_they_are_published(pending, session):
    collection = _pending_collection(session, site_checks=False)

    assert _add(session, collection, _upcoming("soon", NOW + timedelta(hours=3))) == 0
    assert _episode(session, "soon") is None


def test_an_upcoming_video_is_followed_until_it_is_published(pending, session, events):
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import run_pending_checks

    collection = _pending_collection(session)
    starts = NOW + timedelta(hours=2)
    _add(session, collection, _upcoming("soon", starts))
    planned = _episode(session, "soon").episode_identifier

    pending.now["soon"] = _upcoming("soon", starts)
    assert run_pending_checks(session, now=NOW).checked == 1
    # Not due again for an hour.
    assert run_pending_checks(session, now=NOW + timedelta(minutes=30)).checked == 0

    pending.now["soon"] = replace(_upcoming("soon", starts, EpisodePublishStatus.LIVE), title="Now live")
    run_pending_checks(session, now=starts + timedelta(minutes=5))
    episode = _episode(session, "soon")
    assert (episode.publish_status, episode.title) == ("live", "Now live")
    assert episode.went_live_date is not None

    # It started five minutes late and was published once it ended.
    published = starts + timedelta(minutes=5)
    pending.now["soon"] = VideoDetails(slug="soon", url="https://pending.example/soon", title="Now live", published_at=published)
    result = run_pending_checks(session, now=starts + timedelta(hours=2))
    assert (result.checked, result.published) == (1, 1)

    episode = _episode(session, "soon")
    assert episode.publish_status == "published_final"
    assert episode.published_date.replace(tzinfo=timezone.utc) == published
    assert episode.episode_identifier != planned
    assert not episode.metadata_is_final
    assert ("episode.published_final", episode.id) in events

    # A published episode is no longer followed.
    assert run_pending_checks(session, now=starts + timedelta(hours=5)).checked == 0


def test_a_cancelled_stream_has_no_usable_media_and_is_deleted_after_the_grace_period(pending, session, monkeypatch):
    from config import get_settings
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import run_pending_checks

    collection = _pending_collection(session)
    _add(session, collection, _upcoming("cancelled", NOW + timedelta(hours=2)), _upcoming("flaky", NOW + timedelta(hours=2)))

    pending.gone.add("cancelled")
    result = run_pending_checks(session, now=NOW)
    assert (result.gone, result.failed) == (1, 1)
    assert _episode(session, "cancelled").publish_status == "no_usable_media"
    # A lookup that failed for another reason changes nothing.
    assert _episode(session, "flaky").publish_status == "scheduled"

    grace = get_settings().episode_status_timing.no_usable_media_delete_after_minutes
    run_pending_checks(session, now=NOW + timedelta(minutes=grace + 61))
    assert _episode(session, "cancelled") is None


def test_a_stream_that_comes_back_is_followed_again(pending, session):
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import run_pending_checks

    collection = _pending_collection(session)
    starts = NOW + timedelta(hours=2)
    _add(session, collection, _upcoming("back", starts))
    identifier = _episode(session, "back").episode_identifier

    pending.gone.add("back")
    run_pending_checks(session, now=NOW)
    pending.gone.clear()
    pending.now["back"] = _upcoming("back", starts)
    result = run_pending_checks(session, now=NOW + timedelta(hours=1))

    episode = _episode(session, "back")
    assert result.recovered == 1
    assert (episode.publish_status, episode.episode_identifier) == ("scheduled", identifier)
