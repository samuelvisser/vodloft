"""The upgrade check: what counts as a better version, when it looks again, and downloading again."""
from __future__ import annotations

from profile_filters import filter_rows, line

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import available_artifact, use_database
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from sources import Site, SponsorBlockSegment, UpgradeChecks, UpgradeImprovement, UpgradeOffer, VideoFormat

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
YOUTUBE = Site("youtube", "YouTube", upgrade_checks=UpgradeChecks(tuple(UpgradeImprovement)[:4]))
DAILY_WIRE = Site("dailywire", "The Daily Wire", upgrade_checks=UpgradeChecks((UpgradeImprovement.LENGTH,)))


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    yield session
    session.close()
    engine.dispose()


def _download(session, *, local_values=None, profile_values=None, download_values=None):
    from backend.db.models import Collection, Episode, LocalMediaProfile, Season
    from backend.db.models.download_profile import DownloadProfile
    from backend.db.models.media_download import EpisodeMediaDownload

    collection = Collection(
        source_key="ytdlp", uuid="upgrade-uuid", slug="upgrade", title="Upgrade", description=None,
        sharing_url="https://www.youtube.com/@upgrade", membership_level="FREE", type="series",
        episode_identifier="date_based", author_name="Host", author_slug="host",
    )
    season = Season(collection=collection, index=1, slug="upgrade-s1", name="One")
    episode = Episode(
        source_key="ytdlp", uuid="upgrade-ep", type="episode", collection=collection, season=season, index=1,
        episode_identifier="ep.2026-11-01", slug="upgrade-1", title="One", publish_status="published_final",
        sharing_url="https://www.youtube.com/watch?v=abcdefghijk", published_date=NOW - timedelta(days=8),
    )
    local = LocalMediaProfile(
        slug="upgrade-local", name="Upgrade", preferred_format="format_1080p",
        output_template="/downloads/{{ collection }}/{{ episode }}.ext", **(local_values or {}),
    )
    session.add_all([collection, season, episode, local])
    session.flush()
    profile = DownloadProfile(
        collection=collection, local_media_profile=local, enable_profile=True, filters=filter_rows(line("only", "types", episode_types=["ep"])),
        **{"upgrade_check": True, **(profile_values or {})},
    )
    session.add(profile)
    session.flush()
    download = EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=local.id, download_profile_id=profile.id,
        file_path="/tmp/upgrade.mkv", **available_artifact(),
        **{"video_height": 720, "video_codec": "vp9", "subtitle_languages": [], "sponsorblock_segments": [], **(download_values or {})},
    )
    session.add(download)
    session.flush()
    return download


def _findings(download, offer, site=YOUTUBE):
    from backend.services.upgrade_check import upgrade_findings

    return upgrade_findings(offer, download, download.download_profile, download.local_media_profile, site)


def test_a_higher_resolution_up_to_the_profile_counts(db_session):
    download = _download(db_session)

    assert _findings(download, UpgradeOffer(videos=(VideoFormat(720, "vp9"),))).improvements == ()
    found = _findings(download, UpgradeOffer(videos=(VideoFormat(1080, "vp9"), VideoFormat(2160, "vp9"))))
    assert [value.value for value in found.improvements] == ["resolution"]
    assert found.best_height == 1080


def test_a_download_at_the_best_resolution_cannot_improve(db_session):
    download = _download(db_session, download_values={"video_height": 1080}, profile_values={"upgrade_improvements": ["resolution"]})

    found = _findings(download, UpgradeOffer(videos=(VideoFormat(2160, "vp9"),)))
    assert found.improvements == ()
    assert not found.could_improve


def test_new_sponsorblock_segments_count_but_moved_edges_do_not(db_session):
    download = _download(db_session, profile_values={"sponsorblock_enabled": True}, download_values={
        "video_height": 1080,
        "sponsorblock_segments": [{"category": "sponsor", "start": 10.0, "end": 40.0, "action": "cut"}],
    })

    same = UpgradeOffer(sponsorblock=(SponsorBlockSegment("sponsor", 10.4, 40.2),))
    assert _findings(download, same).improvements == ()
    assert _findings(download, same).could_improve
    more = UpgradeOffer(sponsorblock=(SponsorBlockSegment("sponsor", 10.0, 40.0), SponsorBlockSegment("selfpromo", 90.0, 99.0)))
    assert [value.value for value in _findings(download, more).improvements] == ["sponsorblock"]


def test_new_subtitles_count_only_in_a_wanted_language(db_session):
    download = _download(
        db_session,
        local_values={"subtitle_mode": "sidecar", "subtitle_language_mode": "listed", "subtitle_languages": ["nl", "en"]},
        profile_values={"upgrade_improvements": ["subtitles"]},
        download_values={"subtitle_languages": ["en"]},
    )

    assert _findings(download, UpgradeOffer(subtitle_languages=frozenset({"en", "de"}))).improvements == ()
    found = _findings(download, UpgradeOffer(subtitle_languages=frozenset({"en", "nl-NL"})))
    assert [value.value for value in found.improvements] == ["subtitles"]


def test_the_check_schedule_follows_how_often(db_session):
    from backend.services.upgrade_check import next_upgrade_check_at, schedule_first_upgrade_check

    download = _download(db_session, profile_values={"upgrade_after_days": 7, "upgrade_repeat": "every"})
    schedule_first_upgrade_check(download, YOUTUBE, NOW)
    assert download.upgrade_check_at == NOW + timedelta(days=7)

    profile = download.download_profile
    assert next_upgrade_check_at(profile, 1, NOW) == NOW + timedelta(days=7)
    assert next_upgrade_check_at(profile, 3, NOW) is None
    profile.upgrade_repeat = "twice"
    assert next_upgrade_check_at(profile, 1, NOW) == NOW + timedelta(days=30)
    assert next_upgrade_check_at(profile, 2, NOW) is None
    profile.upgrade_repeat = "once"
    assert next_upgrade_check_at(profile, 1, NOW) is None

    profile.upgrade_check = False
    download.upgrade_check_at = None
    schedule_first_upgrade_check(download, YOUTUBE, NOW)
    assert download.upgrade_check_at is None


def test_a_due_check_downloads_again_only_when_better(db_session, monkeypatch):
    from task_manager.tasks.workers.upgrade_check import service

    download = _download(db_session, profile_values={"upgrade_improvements": ["resolution"], "upgrade_repeat": "twice"}, download_values={
        "upgrade_check_at": NOW - timedelta(minutes=1),
    })
    download_id = download.id
    db_session.commit()
    source = SimpleNamespace(
        has=lambda feature: True,
        upgrade_offer=Mock(return_value=UpgradeOffer(videos=(VideoFormat(1080, "vp9"),))),
    )
    created = Mock()
    monkeypatch.setattr(service, "get_source", lambda key: source)
    monkeypatch.setattr(service, "create_media_download_operation", created)
    monkeypatch.setattr(service, "get_active_media_download_operation", Mock(return_value=None))
    monkeypatch.setattr(service, "dispatch_queued_media_download_operations", Mock(return_value=0))

    result = service.run_upgrade_checks(db_session, now=NOW)

    assert result.data == {"checked": 1, "upgraded": 1}
    source.upgrade_offer.assert_called_once_with("https://www.youtube.com/watch?v=abcdefghijk", sponsorblock_categories=())
    assert created.call_args.kwargs["is_redownload"] is True
    from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadHistory
    checked = db_session.get(EpisodeMediaDownload, download_id)
    assert (checked.upgrade_checks, checked.upgrade_result) == (1, "upgraded")
    assert checked.upgrade_check_at.replace(tzinfo=timezone.utc) == NOW + timedelta(days=30)
    history = db_session.query(MediaDownloadHistory).filter_by(media_download_id=download_id).one()
    assert history.event_metadata["improvements"] == ["resolution"]

    # Nothing better the second time: the check is recorded, nothing is downloaded, and it stops.
    created.reset_mock()
    checked.upgrade_check_at = NOW
    checked.video_height = 1080
    db_session.commit()
    result = service.run_upgrade_checks(db_session, now=NOW + timedelta(days=30))
    assert result.data == {"checked": 1, "upgraded": 0}
    created.assert_not_called()
    checked = db_session.get(EpisodeMediaDownload, download_id)
    assert (checked.upgrade_checks, checked.upgrade_result, checked.upgrade_check_at) == (2, "checked", None)


def test_a_profile_with_the_check_off_stops_its_checks(db_session, monkeypatch):
    from task_manager.tasks.workers.upgrade_check import service
    from backend.db.models.media_download import EpisodeMediaDownload

    download = _download(db_session, profile_values={"upgrade_check": False}, download_values={"upgrade_check_at": NOW})
    download_id = download.id
    db_session.commit()
    monkeypatch.setattr(service, "dispatch_queued_media_download_operations", Mock(return_value=0))

    assert service.run_upgrade_checks(db_session, now=NOW).data == {"checked": 0, "upgraded": 0}
    assert db_session.get(EpisodeMediaDownload, download_id).upgrade_check_at is None


def test_a_different_length_counts_only_beyond_the_profiles_minutes(db_session):
    download = _download(db_session, profile_values={"upgrade_improvements": ["length"], "upgrade_length_minutes": 5}, download_values={
        "duration": 7 * 3600 + 12 * 60,
    })

    cut_down = _findings(download, UpgradeOffer(duration=3 * 3600 + 31 * 60), DAILY_WIRE)
    assert [value.value for value in cut_down.improvements] == ["length"]
    # A few minutes either way is the same episode, and the site can still edit it later.
    trimmed = _findings(download, UpgradeOffer(duration=7 * 3600 + 8 * 60), DAILY_WIRE)
    assert (trimmed.improvements, trimmed.could_improve) == ((), True)
    # A length the site cannot tell, or one the file does not have, is never different.
    assert _findings(download, UpgradeOffer(), DAILY_WIRE).improvements == ()
    download.duration = None
    assert _findings(download, UpgradeOffer(duration=3600), DAILY_WIRE).improvements == ()


def test_sponsorblock_segments_the_download_cut_out_are_not_a_different_length(db_session):
    youtube = Site("youtube", "YouTube", upgrade_checks=UpgradeChecks((UpgradeImprovement.LENGTH,)))
    download = _download(db_session, profile_values={"upgrade_improvements": ["length"], "upgrade_length_minutes": 3}, download_values={
        "duration": 20 * 60,
        "sponsorblock_segments": [
            {"category": "sponsor", "start": 60.0, "end": 180.0, "action": "cut"},
            # Overlapping segments only count their seconds once.
            {"category": "selfpromo", "start": 120.0, "end": 240.0, "action": "cut"},
            {"category": "intro", "start": 0.0, "end": 30.0, "action": "chapter"},
        ],
    })

    # The video was 23 minutes; the file is 20 because 3 minutes were cut out.
    assert _findings(download, UpgradeOffer(duration=23 * 60), youtube).improvements == ()
    assert [value.value for value in _findings(download, UpgradeOffer(duration=19 * 60), youtube).improvements] == ["length"]


def test_only_what_the_site_offers_counts(db_session):
    from backend.services.upgrade_check import checks_profile

    download = _download(db_session, profile_values={"upgrade_improvements": ["resolution", "length"]}, download_values={
        "duration": 3600,
    })
    offer = UpgradeOffer(videos=(VideoFormat(1080, "vp9"),), duration=7200)

    assert [value.value for value in _findings(download, offer, YOUTUBE).improvements] == ["resolution"]
    assert [value.value for value in _findings(download, offer, DAILY_WIRE).improvements] == ["length"]
    download.download_profile.upgrade_improvements = ["resolution"]
    assert checks_profile(YOUTUBE, download.download_profile)
    assert not checks_profile(DAILY_WIRE, download.download_profile)
    assert not checks_profile(Site("example", "Example"), download.download_profile)


def test_a_countdown_download_waits_for_the_final_version(db_session):
    download = _download(db_session, profile_values={"upgrade_improvements": ["length"]}, download_values={
        "duration": 7200, "redownload_when_final": True,
    })
    assert _findings(download, UpgradeOffer(duration=3600), DAILY_WIRE).improvements == ()


def test_the_metadata_refresh_checks_a_changed_length_right_away(db_session):
    from backend.services.upgrade_check import check_refreshed_changes_now

    download = _download(db_session, profile_values={"upgrade_improvements": ["length"]}, download_values={
        "duration": 7 * 3600, "upgrade_check_at": NOW + timedelta(days=7),
    })
    episode = download.media

    episode.duration = 7 * 3600 + 120
    assert not check_refreshed_changes_now(episode, DAILY_WIRE, NOW)
    assert download.upgrade_check_at == NOW + timedelta(days=7)

    episode.duration = 3 * 3600
    assert not check_refreshed_changes_now(episode, YOUTUBE, NOW)
    assert download.upgrade_check_at == NOW + timedelta(days=7)
    assert check_refreshed_changes_now(episode, DAILY_WIRE, NOW)
    assert download.upgrade_check_at == NOW
    # A check that is already due is not started again.
    assert not check_refreshed_changes_now(episode, DAILY_WIRE, NOW)

    # The checks of a download that has had all of them come back too.
    download.upgrade_check_at = None
    assert check_refreshed_changes_now(episode, DAILY_WIRE, NOW)
    assert download.upgrade_check_at == NOW


def test_a_refresh_answers_yes_no_or_unknown_per_improvement(db_session):
    from backend.services.upgrade_check import RefreshedChange, refreshed_change

    download = _download(db_session, profile_values={"upgrade_improvements": ["length", "resolution"]}, download_values={
        "duration": 3600,
    })
    episode, profile = download.media, download.download_profile

    episode.duration = 3600
    assert refreshed_change("length", download, episode, profile) == RefreshedChange.NO
    episode.duration = 2 * 3600
    assert refreshed_change("length", download, episode, profile) == RefreshedChange.YES
    # What a refresh does not get, it cannot tell, and neither can a length nobody knows.
    for improvement in ("resolution", "sponsorblock", "subtitles", "codec"):
        assert refreshed_change(improvement, download, episode, profile) == RefreshedChange.UNKNOWN
    episode.duration = None
    assert refreshed_change("length", download, episode, profile) == RefreshedChange.UNKNOWN


def test_a_refresh_that_finds_a_change_starts_the_upgrade_check(db_session, monkeypatch):
    from task_manager.tasks.helpers import refreshed_metadata

    queued = []
    monkeypatch.setattr(refreshed_metadata, "collection_site", lambda collection: DAILY_WIRE)
    monkeypatch.setattr(refreshed_metadata, "queue_task_after_commit", lambda s, **kwargs: queued.append(kwargs))
    download = _download(db_session, profile_values={"upgrade_improvements": ["length"]}, download_values={
        "duration": 7 * 3600, "upgrade_check_at": NOW + timedelta(days=7),
    })
    episode = download.media

    episode.duration = 7 * 3600
    refreshed_metadata.check_upgrades_after_refresh(db_session, episode)
    assert queued == []

    episode.duration = 3 * 3600
    refreshed_metadata.check_upgrades_after_refresh(db_session, episode)
    assert queued == [{"def_key": "upgrade_check", "resource_type": "system", "resource_id": 0}]


def test_history_says_what_improved():
    from backend.api.endpoints.media_downloads.history import _presentation

    entry = SimpleNamespace(action="upgrade_checked", event_metadata={
        "improvements": ["resolution", "sponsorblock"], "best_height": 1080, "kept_height": 720,
    })
    assert _presentation(entry) == (
        "Better version found", "redownloaded", "Higher resolution (720p → 1080p) · New SponsorBlock segments",
    )
    entry.event_metadata = {"improvements": []}
    assert _presentation(entry) == ("Checked for a better version", "downloaded", "Nothing better yet")
    entry.event_metadata = {"improvements": ["length"], "kept_duration": 25_940.2, "offered_duration": 12_660.0}
    assert _presentation(entry) == ("Better version found", "redownloaded", "Different length (7h 12m → 3h 31m)")


def test_ytdlp_reports_the_kept_video_stream():
    from downloader.models import VideoStream
    from downloader.ytdlp import _video_stream

    assert _video_stream("1920 1080 avc1.640028") == VideoStream(1080, "h264")
    assert _video_stream("1080 1920 vp09.00.40.08") == VideoStream(1080, "vp9")
    assert _video_stream("NA NA none") is None


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_downloads_length_is_read_from_its_file(tmp_path):
    import subprocess
    from downloader import media_duration

    path = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3.5:size=64x64:rate=10", str(path)],
        check=True,
    )
    assert media_duration(str(path)) == pytest.approx(3.5, abs=0.1)
    assert media_duration(str(tmp_path / "missing.mp4")) is None


def test_an_imported_file_is_checked_from_its_publish_date(db_session):
    from backend.services.upgrade_check import schedule_imported_upgrade_check

    download = _download(db_session, profile_values={"upgrade_after_days": 7}, download_values={"sponsorblock_segments": None})
    profile = download.download_profile
    schedule_imported_upgrade_check(download, profile, NOW - timedelta(days=2), YOUTUBE, NOW)
    assert download.upgrade_check_at == NOW + timedelta(days=5)

    # A check it already has stays as it is.
    schedule_imported_upgrade_check(download, profile, NOW - timedelta(days=1), YOUTUBE, NOW)
    assert download.upgrade_check_at == NOW + timedelta(days=5)

    download.upgrade_check_at = None
    schedule_imported_upgrade_check(download, profile, NOW - timedelta(days=8), YOUTUBE, NOW)
    assert download.upgrade_check_at is None
    schedule_imported_upgrade_check(download, profile, None, YOUTUBE, NOW)
    assert download.upgrade_check_at is None
    profile.upgrade_check = False
    schedule_imported_upgrade_check(download, profile, NOW - timedelta(days=2), YOUTUBE, NOW)
    assert download.upgrade_check_at is None


def test_ytdlp_and_npo_offer_the_length_they_serve_now(monkeypatch):
    from sources.npo.source import NpoSource
    from sources.ytdlp import source as ytdlp

    monkeypatch.setattr(ytdlp, "_lookup", lambda *args: {"id": "abcdefghijk", "duration": 1385, "formats": []})
    assert ytdlp.YtDlpSource().upgrade_offer("https://www.youtube.com/watch?v=abcdefghijk").duration == 1385.0

    client = SimpleNamespace(program_detail=Mock(return_value={"durationInSeconds": 2700}))
    assert NpoSource(client).upgrade_offer("https://npo.nl/start/afspelen/episode-1").duration == 2700.0
