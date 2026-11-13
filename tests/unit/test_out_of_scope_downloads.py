"""Downloads a narrowed Download Profile no longer covers: listed for the person, never deleted by themselves."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import available_artifact
from profile_filters import downloaded_days, latest, line, with_filters
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
        source_key="ytdlp", uuid="scope-uuid", slug="scope", title="Scope", description=None,
        sharing_url="https://example.test/scope", membership_level="FREE", type="series",
        episode_identifier="date_based", author_name="Host", author_slug="host",
    )
    session.add(collection)
    session.flush()
    session.add(Season(collection=collection, index=1, slug="scope-s1", name="One"))
    session.flush()
    return collection


def _episode(session, collection, index, title, *, days_ago=1):
    from backend.db.models import Episode

    episode = Episode(
        source_key="ytdlp", uuid=f"scope-ep-{index}", type="episode", collection=collection,
        season=collection.seasons[0], index=index, episode_identifier=f"ep.2026-01-{index:02d}", slug=f"scope-{index}", title=title,
        duration=600.0, publish_status="published_final",
        sharing_url=f"https://example.test/scope/{index}", published_date=NOW - timedelta(days=days_ago),
    )
    session.add(episode)
    session.flush()
    return episode


def _profile(session, collection, *filters):
    from backend.db.models import LocalMediaProfile
    from backend.db.models.download_profile import DownloadProfile

    local = LocalMediaProfile(
        slug="scope-local", name="Scope", preferred_format="format_1080p",
        output_template="/downloads/{{ collection }}/{{ episode }}.ext",
    )
    session.add(local)
    session.flush()
    profile = DownloadProfile(
        collection=collection, local_media_profile=local, enable_profile=True,
        download_with_countdown=False, redownload_final=False, delete_older_episodes=False,
    )
    session.add(profile)
    with_filters(profile, *filters)
    session.flush()
    return profile


def _download(session, profile, episode, *, managed=True, **values):
    from backend.db.models.media_download import EpisodeMediaDownload

    download = EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=profile.local_media_profile_id,
        download_profile_id=profile.id if managed else None, file_path=f"/tmp/scope-{episode.id}.mkv",
        **{**available_artifact(), **values},
    )
    session.add(download)
    session.flush()
    return download


def _listed(session, profile, selection=None):
    from backend.services.out_of_scope_downloads import out_of_scope_downloads

    return {item.episode.title: item for item in out_of_scope_downloads(session, profile, selection)}


def test_lists_the_profiles_downloads_its_filters_leave_out(db_session):
    collection = _collection(db_session)
    wanted = _episode(db_session, collection, 1, "Bridges")
    trailer = _episode(db_session, collection, 2, "Trailer", days_ago=2)
    kept = _episode(db_session, collection, 3, "Old trailer", days_ago=3)
    by_hand = _episode(db_session, collection, 4, "Hand trailer", days_ago=4)
    profile = _profile(db_session, collection, line("skip", "title", pattern="(?i)trailer"))
    for episode in (wanted, trailer):
        _download(db_session, profile, episode)
    _download(db_session, profile, kept, kept=True)
    _download(db_session, profile, by_hand, managed=False)

    listed = _listed(db_session, profile)

    # A download made by hand is not the profile's, so it is never listed.
    assert set(listed) == {"Trailer", "Old trailer"}
    assert listed["Trailer"].kept_by is None
    assert listed["Trailer"].filter_index == 0
    assert listed["Old trailer"].kept_by == "hand"


def test_a_keep_filter_marks_a_listed_download_as_kept(db_session):
    collection = _collection(db_session)
    trailer = _episode(db_session, collection, 1, "Trailer")
    profile = _profile(
        db_session, collection, line("skip", "title", pattern="Trailer"), line("keep", "title", pattern="Trailer"),
    )
    _download(db_session, profile, trailer)

    assert _listed(db_session, profile)["Trailer"].kept_by == "keep_filter"


def test_a_downloaded_line_leaves_out_by_download_age_not_publication(db_session):
    collection = _collection(db_session)
    old_fresh = _episode(db_session, collection, 1, "Published long ago, downloaded today", days_ago=40)
    old_stale = _episode(db_session, collection, 2, "Downloaded long ago", days_ago=41)
    profile = _profile(db_session, collection, downloaded_days(30))
    _download(db_session, profile, old_fresh, downloaded_at=NOW)
    _download(db_session, profile, old_stale, downloaded_at=NOW - timedelta(days=35))

    assert set(_listed(db_session, profile)) == {"Downloaded long ago"}


def test_the_edit_forms_filters_preview_what_saving_would_leave_out(db_session):
    from backend.services.episode_filters import EpisodeSelection

    collection = _collection(db_session)
    newest = _episode(db_session, collection, 1, "Newest", days_ago=1)
    older = _episode(db_session, collection, 2, "Older", days_ago=2)
    profile = _profile(db_session, collection)
    _download(db_session, profile, newest)
    _download(db_session, profile, older)
    assert _listed(db_session, profile) == {}

    narrower = EpisodeSelection(collection=collection, download_with_countdown=False, filters=[latest(1)])

    assert set(_listed(db_session, profile, narrower)) == {"Older"}


def test_statistics_count_the_left_out_downloads_apart_from_the_kept_ones(db_session):
    from backend.services.out_of_scope_downloads import download_profile_statistics

    collection = _collection(db_session)
    wanted = _episode(db_session, collection, 1, "Bridges")
    trailer = _episode(db_session, collection, 2, "Trailer")
    kept = _episode(db_session, collection, 3, "Kept trailer")
    profile = _profile(db_session, collection, line("skip", "title", pattern="(?i)trailer"))
    _download(db_session, profile, wanted)
    _download(db_session, profile, trailer)
    _download(db_session, profile, kept, kept=True)

    statistics = download_profile_statistics(db_session, profile)

    assert (statistics.downloaded, statistics.wanted, statistics.out_of_scope, statistics.out_of_scope_kept) == (3, 1, 1, 1)


def test_a_page_carries_the_totals_of_every_out_of_scope_download(db_session):
    from backend.services.out_of_scope_downloads import out_of_scope_page

    collection = _collection(db_session)
    profile = _profile(db_session, collection, line("skip", "title", pattern="(?i)trailer"))
    for index in range(1, 6):
        episode = _episode(db_session, collection, index, f"Trailer {index}", days_ago=index)
        _download(db_session, profile, episode, kept=index == 5, artifact_size_bytes=100)

    first = out_of_scope_page(db_session, profile, offset=0, limit=2)
    last = out_of_scope_page(db_session, profile, offset=4, limit=2)

    assert [item.episode.title for item in first.items] == ["Trailer 1", "Trailer 2"]
    assert first.has_more and not last.has_more
    assert [item.episode.title for item in last.items] == ["Trailer 5"]
    assert (first.total, first.size_bytes, first.kept, first.kept_size_bytes) == (5, 500, 1, 100)
    assert first.filter_indexes == [0]


def test_a_delete_takes_the_downloads_picked_from_the_whole_list(db_session):
    from backend.services.out_of_scope_downloads import picked_out_of_scope

    collection = _collection(db_session)
    profile = _profile(db_session, collection, line("skip", "title", pattern="(?i)trailer"))
    wanted = _download(db_session, profile, _episode(db_session, collection, 1, "Bridges"))
    one = _download(db_session, profile, _episode(db_session, collection, 2, "Trailer one"))
    two = _download(db_session, profile, _episode(db_session, collection, 3, "Trailer two"))
    kept = _download(db_session, profile, _episode(db_session, collection, 4, "Kept trailer"), kept=True)

    def picked(not_kept=False, kept=False, include=(), exclude=()):
        return set(picked_out_of_scope(
            db_session, profile.id, not_kept=not_kept, kept=kept, include=include, exclude=exclude,
        ))

    assert picked(not_kept=True) == {one.id, two.id}
    assert picked(not_kept=True, include=[kept.id], exclude=[two.id]) == {one.id, kept.id}
    assert picked(kept=True) == {kept.id}
    assert picked(not_kept=True, kept=True) == {one.id, two.id, kept.id}
    # A download the filters cover is never deleted, even when it is asked for.
    assert picked(include=[wanted.id, one.id]) == {one.id}


def test_the_preview_only_counts_what_saving_newly_leaves_out(db_session):
    from backend.services.episode_filters import EpisodeSelection
    from backend.services.out_of_scope_downloads import newly_out_of_scope

    collection = _collection(db_session)
    profile = _profile(db_session, collection, line("skip", "title", pattern="(?i)trailer"))
    _download(db_session, profile, _episode(db_session, collection, 1, "Trailer", days_ago=1), artifact_size_bytes=10)
    newest = _download(db_session, profile, _episode(db_session, collection, 2, "Newest", days_ago=2), artifact_size_bytes=10)
    older = _download(db_session, profile, _episode(db_session, collection, 3, "Older", days_ago=3), artifact_size_bytes=20)
    _download(db_session, profile, _episode(db_session, collection, 4, "Oldest", days_ago=4), kept=True, artifact_size_bytes=40)
    narrower = EpisodeSelection(
        collection=collection, download_with_countdown=False,
        filters=[line("skip", "title", pattern="(?i)trailer"), line("skip", "title", pattern="Old")],
    )

    preview = newly_out_of_scope(db_session, profile, narrower, offset=0, limit=1)

    assert preview.not_kept_ids == [older.id]
    assert newest.id not in preview.not_kept_ids
    assert len(preview.kept_ids) == 1
    assert [item.download.id for item in preview.items] == [older.id]
    assert preview.has_more
    assert (preview.total, preview.size_bytes, preview.kept, preview.kept_size_bytes) == (2, 60, 1, 40)
    assert preview.filter_indexes == [1]
