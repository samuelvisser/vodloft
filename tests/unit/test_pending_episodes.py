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
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import Rhythm, interval, is_due

    usual = Rhythm(timedelta(hours=1), timedelta(minutes=2), timedelta(minutes=5))
    starts = NOW + timedelta(hours=2)
    assert interval("scheduled", starts, NOW, usual) == usual.upcoming == timedelta(hours=1)
    assert interval("scheduled", starts, starts - timedelta(minutes=10), usual) == usual.starting == timedelta(minutes=2)
    assert interval("delayed", starts, starts + timedelta(minutes=30), usual) == usual.starting
    # A stream more than an hour late may wait for days.
    assert interval("delayed", starts, starts + timedelta(hours=2), usual) == usual.upcoming
    # One without a known start may start any moment.
    assert interval("scheduled", None, NOW, usual) == usual.starting
    assert interval("live", None, NOW, usual) == usual.live == timedelta(minutes=5)
    assert interval("published_preliminary", None, NOW, usual) == usual.live
    assert interval("no_usable_media", None, NOW, usual) == usual.upcoming

    assert is_due("scheduled", starts, None, NOW, usual)
    assert not is_due("scheduled", starts, NOW, NOW + timedelta(minutes=30), usual)
    assert is_due("scheduled", starts, NOW, NOW + timedelta(hours=1), usual)
    # Checked 50 minutes before the start, it is checked again right when the last 15 minutes begin.
    assert is_due("scheduled", starts, starts - timedelta(minutes=50), starts - timedelta(minutes=15), usual)
    assert not is_due("scheduled", starts, starts - timedelta(minutes=14), starts - timedelta(minutes=13), usual)
    assert is_due("scheduled", starts, starts - timedelta(minutes=14), starts - timedelta(minutes=12), usual)


def test_a_site_sets_its_own_rhythm():
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import Rhythm, is_due

    relaxed = Rhythm(upcoming=timedelta(hours=6), starting=timedelta(minutes=10), live=timedelta(minutes=30))
    starts = NOW + timedelta(hours=12)
    assert not is_due("scheduled", starts, NOW, NOW + timedelta(hours=2), relaxed)
    assert is_due("scheduled", starts, NOW, NOW + timedelta(hours=6), relaxed)
    assert not is_due("live", None, NOW, NOW + timedelta(minutes=20), relaxed)
    assert is_due("live", None, NOW, NOW + timedelta(minutes=30), relaxed)


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


@pytest.fixture
def site_settings():
    """Give Sites settings of their own, as under siteSettings in config.yml."""
    from config.registry import get_settings, replace_settings
    from config.settings.site_settings import SiteSettingValues

    original = get_settings()

    def apply(**schedules: dict):
        replace_settings(original.model_copy(update={
            "site_settings": {key: SiteSettingValues(**own) for key, own in schedules.items()},
        }))

    yield apply
    replace_settings(original)


def _pending_collection(session, *, identifier="date_based"):
    from backend.db.models import Site

    session.add(Site(key="tube", name="Tube", domains=["pending.example"]))
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


def test_a_site_can_leave_upcoming_videos_out_until_they_are_published(pending, session, site_settings):
    site_settings(tube={"upcoming_and_live": False})
    collection = _pending_collection(session)

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


# --- The Daily Wire's pending episodes -----------------------------------------------------------


@pytest.fixture
def monitored(monkeypatch):
    """The Daily Wire's own monitor, answering from a table instead of The Daily Wire."""
    from types import SimpleNamespace

    from backend.db.models import Episode
    from task_manager.tasks.workers.monitor_pending_episode import pending_checks

    monkeypatch.setattr(pending_checks, "_last_checked", {})
    answers: dict[int, EpisodePublishStatus | Exception] = {}
    checked: list[int] = []

    def monitor(s, *, episode_id):
        checked.append(episode_id)
        answer = answers.get(episode_id, EpisodePublishStatus.LIVE)
        if isinstance(answer, Exception):
            raise answer
        s.get(Episode, episode_id).publish_status = answer.value
        s.commit()
        return answer

    monkeypatch.setattr(pending_checks, "run_monitor_pending_episode", monitor)
    return SimpleNamespace(answers=answers, checked=checked)


def _dailywire_episode(session, slug: str, status: str = "live", site=None) -> int:
    from backend.db.models import Episode, Season

    collection = _collection(session, f"show-{slug}", source_key="dailywire")
    collection.site_key = site
    season = Season(collection=collection, index=1, slug="season-1", name="One")
    episode = Episode(
        uuid=f"uuid-{slug}", type="episode", source_key="dailywire", collection=collection, season=season, index=1,
        episode_identifier=f"ep.{slug}", slug=slug, title=slug, publish_status=status, metadata_is_final=False,
        sharing_url=f"https://example.test/{slug}",
    )
    session.add(episode)
    session.commit()
    return episode.id


def _sweep(session, now):
    from task_manager.tasks.workers.monitor_pending_episode.pending_checks import run_pending_checks

    return run_pending_checks(session, now=now)


def test_a_live_daily_wire_episode_follows_the_same_rhythm_one_by_one(monitored, session):
    live = _dailywire_episode(session, "live")
    _dailywire_episode(session, "done", status="published_final")

    # Every pending episode is looked up once, also right after a restart.
    assert _sweep(session, NOW).checked == 1
    assert monitored.checked == [live]
    # A live one again after five minutes.
    assert _sweep(session, NOW + timedelta(minutes=4)).checked == 0
    assert _sweep(session, NOW + timedelta(minutes=5)).checked == 1

    monitored.answers[live] = EpisodePublishStatus.PUBLISHED_FINAL
    result = _sweep(session, NOW + timedelta(minutes=10))
    assert (result.checked, result.changed, result.published) == (1, 1, 1)
    # A published episode is no longer followed.
    assert _sweep(session, NOW + timedelta(minutes=30)).checked == 0


def test_a_failed_daily_wire_lookup_is_tried_again_on_the_next_round(monitored, session):
    flaky = _dailywire_episode(session, "flaky")
    gone = _dailywire_episode(session, "gone", status="scheduled")
    monitored.answers[flaky] = RuntimeError("HTTP error 503")
    monitored.answers[gone] = EpisodePublishStatus.NO_USABLE_MEDIA

    result = _sweep(session, NOW)
    assert (result.checked, result.failed, result.gone) == (2, 1, 1)

    del monitored.answers[flaky]
    # The episode without usable media is left to the no-usable-media checks.
    assert _sweep(session, NOW + timedelta(minutes=5)).checked == 1
    assert monitored.checked == [flaky, gone, flaky]


def test_a_daily_wire_episode_follows_the_rhythm_of_its_site(monitored, session, site_settings):
    from backend.db.models import Site

    site_settings(dailywire={"lookup_minutes": {"upcoming": 60, "starting": 2, "live": 20}})
    session.add(Site(key="dailywire", name="The Daily Wire", domains=["dailywire.com"]))
    session.commit()
    _dailywire_episode(session, "live", site="dailywire")

    assert _sweep(session, NOW).checked == 1
    assert _sweep(session, NOW + timedelta(minutes=10)).checked == 0
    assert _sweep(session, NOW + timedelta(minutes=20)).checked == 1


def test_a_site_with_upcoming_and_live_off_is_not_followed(monitored, session, site_settings):
    from backend.db.models import Site

    site_settings(dailywire={"upcoming_and_live": False})
    session.add(Site(key="dailywire", name="The Daily Wire", domains=["dailywire.com"]))
    session.commit()
    _dailywire_episode(session, "live", site="dailywire")

    assert _sweep(session, NOW).checked == 0
    assert monitored.checked == []


def test_a_site_follows_the_system_setting_unless_it_has_its_own(site_settings):
    from config import get_settings
    from backend.services import pending_episodes

    site_settings(b={"upcoming_and_live": False}, c={
        "lookup_minutes": {"upcoming": 90, "starting": 3, "live": 10},
    })
    system = get_settings().new_episode_schedule

    assert pending_episodes.site_follows_pending("a") == system.upcoming_and_live
    assert not pending_episodes.site_follows_pending("b")
    assert pending_episodes.site_pending_minutes(None) == pending_episodes.PendingMinutes(
        system.pending_upcoming_minutes, system.pending_starting_minutes, system.pending_live_minutes,
    )
    assert pending_episodes.site_pending_minutes("c") == pending_episodes.PendingMinutes(90, 3, 10)
