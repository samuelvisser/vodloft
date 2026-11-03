"""Which episodes: your own Skip, Only download and Keep rules, and retention from the download date."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from conftest import available_artifact
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


NOW = datetime.now(timezone.utc)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    yield session
    session.close()
    engine.dispose()


def _collection(session):
    from backend.db.models import Collection, Season

    collection = Collection(
        source_key="ytdlp", uuid="which-uuid", slug="which", title="Which", description=None,
        sharing_url="https://example.test/which", membership_level="FREE", type="series",
        episode_identifier="date_based", author_name="Host", author_slug="host",
    )
    session.add(collection)
    session.flush()
    season = Season(collection=collection, index=1, slug="which-s1", name="One")
    session.add(season)
    session.flush()
    return collection, season


def _episode(session, collection, season, index, title, *, days_ago=1, duration=600.0, description=None):
    from backend.db.models import Episode

    episode = Episode(
        source_key="ytdlp", uuid=f"which-ep-{index}", type="episode", collection=collection, season=season,
        index=index, episode_identifier=f"ep.2026-01-{index:02d}", slug=f"which-{index}", title=title,
        description=description, duration=duration, publish_status="published_final",
        sharing_url=f"https://example.test/which/{index}", published_date=NOW - timedelta(days=days_ago),
    )
    session.add(episode)
    session.flush()
    return episode


def _profile(session, collection, rules=(), **values):
    from backend.db.models import LocalMediaProfile
    from backend.db.models.download_profile import DownloadProfile
    from backend.services.episode_rules import set_profile_rules

    local = LocalMediaProfile(
        slug=f"which-local-{len(rules)}-{len(values)}", name="Which", preferred_format="format_1080p",
        output_template="/downloads/{{ collection }}/{{ episode }}.ext",
    )
    session.add(local)
    session.flush()
    profile = DownloadProfile(
        collection=collection, local_media_profile=local, enable_profile=True, ep_id_type_list=["ep"],
        download_with_countdown=False, redownload_final=False,
        **{"download_days_in_past": 0, "download_episode_count": 0, "delete_older_episodes": False, **values},
    )
    session.add(profile)
    set_profile_rules(profile, [_rule(**rule) for rule in rules])
    session.flush()
    return profile


def _rule(action, field, pattern=None, ignore_case=False, duration_operator=None, duration_seconds=None):
    return SimpleNamespace(
        action=action, field=field, pattern=pattern, ignore_case=ignore_case,
        duration_operator=duration_operator, duration_seconds=duration_seconds,
    )


def _wanted_titles(session, profile):
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    return {episode.title for episode in get_download_profile_episodes(session, profile)}


def test_skip_and_only_rules_narrow_the_episodes(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Official Trailer: Sleep")
    _episode(db_session, collection, season, 2, "Why bridges sway")
    _episode(db_session, collection, season, 3, "A 60 second teaser", duration=60)
    _episode(db_session, collection, season, 4, "Interview: bridges", description="A long talk")
    profile = _profile(db_session, collection, rules=[
        {"action": "skip", "field": "title", "pattern": r"\b(?:trailer|teaser)\b", "ignore_case": True},
        {"action": "only", "field": "title", "pattern": "bridges"},
        {"action": "skip", "field": "description", "pattern": "long"},
    ])

    assert _wanted_titles(db_session, profile) == {"Why bridges sway"}


def test_duration_rules_pass_episodes_of_unknown_length(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Short", duration=60)
    _episode(db_session, collection, season, 2, "Long", duration=3600)
    _episode(db_session, collection, season, 3, "Unknown", duration=0)
    profile = _profile(db_session, collection, rules=[
        {"action": "skip", "field": "duration", "duration_operator": "shorter", "duration_seconds": 120},
        {"action": "only", "field": "duration", "duration_operator": "shorter", "duration_seconds": 1800},
    ])

    assert _wanted_titles(db_session, profile) == {"Unknown"}


def test_keep_rules_never_stop_a_download(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Keep me")
    profile = _profile(db_session, collection, rules=[{"action": "keep", "field": "title", "pattern": "nothing"}])

    assert _wanted_titles(db_session, profile) == {"Keep me"}


def test_which_episodes_counts_each_line_in_order(db_session):
    from backend.services.which_episodes import EpisodeSelection, which_episodes

    collection, season = _collection(db_session)
    trailer = _episode(db_session, collection, season, 1, "Trailer", days_ago=1)
    short = _episode(db_session, collection, season, 2, "Tiny", days_ago=2, duration=30)
    old = _episode(db_session, collection, season, 3, "Old trailer", days_ago=200)
    kept = _episode(db_session, collection, season, 4, "Main", days_ago=3)
    removed = _episode(db_session, collection, season, 5, "Gone", days_ago=4)
    removed.removed_from_source = True
    db_session.flush()
    profile = _profile(db_session, collection, rules=[
        {"action": "skip", "field": "title", "pattern": "trailer", "ignore_case": True},
        {"action": "skip", "field": "duration", "duration_operator": "shorter", "duration_seconds": 60},
    ], download_days_in_past=90)

    result = which_episodes(db_session, EpisodeSelection.of_profile(profile))

    assert (result.total, result.unavailable, result.types, result.dates) == (5, 1, 0, 1)
    assert result.rules == [1, 1]
    assert result.downloaded == 1
    assert result.left_out_by == {
        removed.id: "unavailable", old.id: "dates", trailer.id: "rule:0", short.id: "rule:1",
    }
    assert kept.id not in result.left_out_by


def _download(session, profile, episode, **values):
    from backend.db.models.media_download import EpisodeMediaDownload

    download = EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=profile.local_media_profile_id,
        download_profile_id=profile.id, file_path=f"/tmp/which-{episode.id}.mkv", **available_artifact(), **values,
    )
    session.add(download)
    session.flush()
    return download


def _remaining(session):
    from backend.db.models.media_download import EpisodeMediaDownload

    return {row.media_item_id for row in session.query(EpisodeMediaDownload)}


def test_retention_skips_kept_downloads_and_keep_rule_matches(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection, season = _collection(db_session)
    old = _episode(db_session, collection, season, 1, "Old", days_ago=40)
    kept = _episode(db_session, collection, season, 2, "Old but kept", days_ago=40)
    favourite = _episode(db_session, collection, season, 3, "Old favourite", days_ago=40)
    profile = _profile(
        db_session, collection, rules=[{"action": "keep", "field": "title", "pattern": "favourite"}],
        download_days_in_past=30, delete_older_episodes=True,
    )
    _download(db_session, profile, old)
    _download(db_session, profile, kept, kept=True)
    _download(db_session, profile, favourite)

    assert cleanup_older_episodes(db_session, profile) == 1
    assert _remaining(db_session) == {kept.id, favourite.id}


def test_retention_can_count_from_the_download_date(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection, season = _collection(db_session)
    recent_download = _episode(db_session, collection, season, 1, "Published long ago", days_ago=60)
    old_download = _episode(db_session, collection, season, 2, "Downloaded long ago", days_ago=60)
    profile = _profile(
        db_session, collection, download_days_in_past=30, delete_older_episodes=True, retention_from="downloaded",
    )
    _download(db_session, profile, recent_download, downloaded_at=NOW - timedelta(days=2))
    _download(db_session, profile, old_download, downloaded_at=NOW - timedelta(days=31))

    assert cleanup_older_episodes(db_session, profile) == 1
    assert _remaining(db_session) == {recent_download.id}


def test_changing_rules_later_never_deletes_downloads(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection, season = _collection(db_session)
    trailer = _episode(db_session, collection, season, 1, "Trailer", days_ago=1)
    main = _episode(db_session, collection, season, 2, "Main", days_ago=2)
    profile = _profile(
        db_session, collection, rules=[{"action": "skip", "field": "title", "pattern": "Trailer"}],
        download_episode_count=5, delete_older_episodes=True,
    )
    _download(db_session, profile, trailer)
    _download(db_session, profile, main)

    assert cleanup_older_episodes(db_session, profile) == 0
    assert _remaining(db_session) == {trailer.id, main.id}


def test_rule_requests_check_the_pattern():
    from pydantic import ValidationError

    from backend.api.models.download_profile import DownloadProfileRuleAPIIn

    rule = DownloadProfileRuleAPIIn.model_validate({"action": "skip", "field": "title", "pattern": "(?i)trailer"})
    assert (rule.pattern, rule.ignore_case) == ("trailer", True)
    with pytest.raises(ValidationError):
        DownloadProfileRuleAPIIn.model_validate({"action": "skip", "field": "title", "pattern": "(unclosed"})
    with pytest.raises(ValidationError):
        DownloadProfileRuleAPIIn.model_validate({"action": "skip", "field": "duration", "durationSeconds": 60})


def test_skipped_by_filter_names_the_rule(db_session):
    from backend.api.endpoints.download_profiles.service import skipped_by_filter

    collection, season = _collection(db_session)
    trailer = _episode(db_session, collection, season, 1, "Trailer")
    _episode(db_session, collection, season, 2, "Main")
    profile = _profile(db_session, collection, rules=[{"action": "skip", "field": "title", "pattern": "Trailer"}])

    [skipped] = skipped_by_filter(db_session, collection.id)

    assert (skipped.episode_id, skipped.download_profile_id) == (trailer.id, profile.id)
    assert skipped.rule.pattern == "Trailer"


def test_a_duration_rule_request_needs_no_pattern():
    from backend.api.models.download_profile import DownloadProfileRuleAPIIn

    rule = DownloadProfileRuleAPIIn.model_validate(
        {"action": "skip", "field": "duration", "durationOperator": "shorter", "durationSeconds": 120}
    )
    assert rule.duration_seconds == 120 and rule.pattern is None


def test_without_an_episode_types_line_every_type_is_downloaded(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Regular")
    trailer = _episode(db_session, collection, season, 2, "Trailer")
    trailer.episode_identifier = "trailer.2026-01-02"
    db_session.flush()
    profile = _profile(db_session, collection)
    assert _wanted_titles(db_session, profile) == {"Regular"}

    profile.ep_id_type_list = []
    db_session.flush()
    assert _wanted_titles(db_session, profile) == {"Regular", "Trailer"}


def test_a_profile_for_every_type_overlaps_any_other(db_session):
    from fastapi import HTTPException

    from backend.api.endpoints.download_profiles.service import require_unique_download_profile_episode_types

    collection, _season = _collection(db_session)
    profile = _profile(db_session, collection)
    check = dict(collection_id=collection.id, local_media_profile_id=profile.local_media_profile_id)

    with pytest.raises(HTTPException, match="already downloads these episodes"):
        require_unique_download_profile_episode_types(db_session, episode_types=[], **check)
    # Editing the profile itself is no overlap.
    require_unique_download_profile_episode_types(db_session, episode_types=[], exclude_profile_id=profile.id, **check)
    profile.ep_id_type_list = []
    db_session.flush()
    with pytest.raises(HTTPException, match="already downloads these episodes"):
        require_unique_download_profile_episode_types(db_session, episode_types=["trailer"], **check)
