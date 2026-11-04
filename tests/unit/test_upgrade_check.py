"""The upgrade check: what counts as a better version, when it looks again, and downloading again."""
from __future__ import annotations

from profile_filters import filter_rows, line

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import available_artifact
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sources import SponsorBlockSegment, UpgradeOffer, VideoFormat

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
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


def _findings(download, offer):
    from backend.services.upgrade_check import upgrade_findings

    return upgrade_findings(offer, download, download.download_profile, download.local_media_profile)


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
    from sources import get_source

    download = _download(db_session, profile_values={"upgrade_after_days": 7, "upgrade_repeat": "every"})
    schedule_first_upgrade_check(download, get_source("ytdlp"), NOW)
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
    schedule_first_upgrade_check(download, get_source("ytdlp"), NOW)
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


def test_ytdlp_reports_the_kept_video_stream():
    from downloader.models import VideoStream
    from downloader.ytdlp import _video_stream

    assert _video_stream("1920 1080 avc1.640028") == VideoStream(1080, "h264")
    assert _video_stream("1080 1920 vp09.00.40.08") == VideoStream(1080, "vp9")
    assert _video_stream("NA NA none") is None
