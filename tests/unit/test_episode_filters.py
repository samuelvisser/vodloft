"""Which episodes: one ordered list of Skip, Only download and Keep filters, date lines included."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import available_artifact
from profile_filters import (
    downloaded_days, latest, line, only_seasons, only_types, published_days, with_filters,
)
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


def _profile(session, collection, *filters, **values):
    from backend.db.models import LocalMediaProfile
    from backend.db.models.download_profile import DownloadProfile

    number = session.query(LocalMediaProfile).count()
    local = LocalMediaProfile(
        slug=f"which-local-{number}", name=f"Which {number}", preferred_format="format_1080p",
        output_template=f"/downloads/{number}/{{{{ collection }}}}/{{{{ episode }}}}.ext",
    )
    session.add(local)
    session.flush()
    profile = DownloadProfile(
        collection=collection, local_media_profile=local, enable_profile=True,
        download_with_countdown=False, redownload_final=False, **{"delete_older_episodes": False, **values},
    )
    session.add(profile)
    with_filters(profile, *filters)
    session.flush()
    return profile


def _wanted_titles(session, profile):
    from task_manager.tasks.workers.download_profile_worker._helpers import get_download_profile_episodes

    return {episode.title for episode in get_download_profile_episodes(session, profile)}


def test_skip_and_only_filters_narrow_the_episodes(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Official Trailer: Sleep")
    _episode(db_session, collection, season, 2, "Why bridges sway")
    _episode(db_session, collection, season, 3, "A 60 second teaser", duration=60)
    _episode(db_session, collection, season, 4, "Interview: bridges", description="A long talk")
    profile = _profile(
        db_session, collection,
        line("skip", "title", pattern=r"(?i)\b(?:trailer|teaser)\b"),
        line("only", "title", pattern="bridges"),
        line("skip", "description", pattern="long"),
    )

    assert _wanted_titles(db_session, profile) == {"Why bridges sway"}


def test_duration_filters_pass_episodes_of_unknown_length(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Short", duration=60)
    _episode(db_session, collection, season, 2, "Long", duration=3600)
    _episode(db_session, collection, season, 3, "Unknown", duration=0)
    profile = _profile(
        db_session, collection,
        line("skip", "duration", duration_operator="shorter", duration_seconds=120),
        line("only", "duration", duration_operator="shorter", duration_seconds=1800),
    )

    assert _wanted_titles(db_session, profile) == {"Unknown"}


def test_keep_filters_never_stop_a_download(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Keep me")
    profile = _profile(db_session, collection, line("keep", "title", pattern="nothing"))

    assert _wanted_titles(db_session, profile) == {"Keep me"}


def test_each_filter_counts_what_it_leaves_out_in_order(db_session):
    from backend.services.episode_filters import EpisodeSelection, evaluate

    collection, season = _collection(db_session)
    trailer = _episode(db_session, collection, season, 1, "Trailer", days_ago=1)
    short = _episode(db_session, collection, season, 2, "Tiny", days_ago=2, duration=30)
    old = _episode(db_session, collection, season, 3, "Old trailer", days_ago=200)
    kept = _episode(db_session, collection, season, 4, "Main", days_ago=3)
    removed = _episode(db_session, collection, season, 5, "Gone", days_ago=4)
    removed.removed_from_source = True
    db_session.flush()
    profile = _profile(
        db_session, collection,
        only_types("ep"),
        line("skip", "duration", duration_operator="shorter", duration_seconds=60),
        published_days(90),
        line("skip", "title", pattern="(?i)trailer"),
    )

    result = evaluate(db_session, EpisodeSelection.of_profile(profile))

    assert (result.total, result.unavailable) == (5, 1)
    assert result.counts == [0, 1, 1, 1]
    assert [episode.id for episode in result.wanted] == [kept.id]
    assert result.left_out_by == {
        removed.id: "unavailable", short.id: "filter:1", old.id: "filter:2", trailer.id: "filter:3",
    }


def test_the_latest_n_count_what_the_filters_above_let_through(db_session):
    collection, season = _collection(db_session)
    for index in range(1, 5):
        _episode(db_session, collection, season, index, f"Trailer {index}", days_ago=index)
    for index in range(5, 8):
        _episode(db_session, collection, season, index, f"Episode {index}", days_ago=index)

    above = _profile(db_session, collection, line("skip", "title", pattern="Trailer"), latest(2))
    below = _profile(db_session, collection, latest(5), line("only", "title", pattern="Trailer"))

    # Skipping the trailers first keeps two real episodes; the latest five first keeps only their trailers.
    assert _wanted_titles(db_session, above) == {"Episode 5", "Episode 6"}
    assert _wanted_titles(db_session, below) == {"Trailer 1", "Trailer 2", "Trailer 3", "Trailer 4"}


def test_the_episode_list_comes_a_page_at_a_time(db_session):
    from backend.api.endpoints.download_profiles.service import count_which_episodes
    from backend.api.models.download_profile import WhichEpisodesAPIRequest

    collection, season = _collection(db_session)
    for index in range(1, 6):
        _episode(db_session, collection, season, index, f"Episode {index}", days_ago=index)

    def page(offset, limit):
        body = WhichEpisodesAPIRequest.model_validate({
            "collectionId": collection.id, "downloadWithCountdown": False,
            "filters": [{"action": "only", "field": "published", "count": 3}],
            "includeEpisodes": True, "episodesOffset": offset, "episodesLimit": limit,
        })
        return count_which_episodes(db_session, collection, body)

    first, rest = page(0, 2), page(2, 10)

    assert [episode.title for episode in first.episodes] == ["Episode 1", "Episode 2"]
    assert [episode.title for episode in rest.episodes] == ["Episode 3", "Episode 4", "Episode 5"]
    assert [episode.left_out_by for episode in rest.episodes] == [None, "filter:0", "filter:0"]
    # Every page still counts the whole Collection.
    assert first.total == rest.total == 5
    assert (first.filters, first.downloaded) == ([2], 3)


def test_the_episode_list_can_show_only_what_one_filter_leaves_out(db_session):
    from backend.api.endpoints.download_profiles.service import count_which_episodes
    from backend.api.models.download_profile import WhichEpisodesAPIRequest

    collection, season = _collection(db_session)
    for index in range(1, 7):
        title = f"Trailer {index}" if index % 2 else f"Episode {index}"
        _episode(db_session, collection, season, index, title, days_ago=index, duration=60.0 * index)

    def page(shown, offset=0, limit=50):
        body = WhichEpisodesAPIRequest.model_validate({
            "collectionId": collection.id, "downloadWithCountdown": False,
            "filters": [
                {"action": "skip", "field": "title", "pattern": "Trailer"},
                {"action": "only", "field": "published", "count": 1},
            ],
            "includeEpisodes": True, "episodesShown": shown, "episodesOffset": offset, "episodesLimit": limit,
        })
        return count_which_episodes(db_session, collection, body)

    trailers = page("filter:0")
    assert [episode.title for episode in trailers.episodes] == ["Trailer 1", "Trailer 3", "Trailer 5"]
    assert trailers.episodes_total == 3
    # The counts still cover every episode, whichever ones the list shows.
    assert (trailers.total, trailers.filters, trailers.downloaded) == (6, [3, 2], 1)
    assert [episode.title for episode in page("filter:1").episodes] == ["Episode 4", "Episode 6"]
    assert [episode.title for episode in page("downloads").episodes] == ["Episode 2"]
    assert page(None).episodes_total == 6

    # The filtered list still comes a page at a time.
    second = page("filter:0", offset=2, limit=2)
    assert [episode.title for episode in second.episodes] == ["Trailer 5"]
    assert second.episodes_total == 3

    episode = page("downloads").episodes[0]
    assert (episode.episode_type, episode.duration) == ("ep", 120.0)


def test_the_episode_list_shows_only_known_groups():
    from pydantic import ValidationError

    from backend.api.models.download_profile import WhichEpisodesAPIRequest

    with pytest.raises(ValidationError):
        WhichEpisodesAPIRequest.model_validate({
            "collectionId": 1, "downloadWithCountdown": False, "includeEpisodes": True, "episodesShown": "everything",
        })


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


def test_retention_skips_kept_downloads_and_keep_filter_matches(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection, season = _collection(db_session)
    old = _episode(db_session, collection, season, 1, "Old", days_ago=40)
    kept = _episode(db_session, collection, season, 2, "Old but kept", days_ago=40)
    favourite = _episode(db_session, collection, season, 3, "Old favourite", days_ago=40)
    # A Keep filter protects what it matches wherever it stands, even below the date line.
    profile = _profile(
        db_session, collection, published_days(30), line("keep", "title", pattern="favourite"),
        delete_older_episodes=True,
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
    profile = _profile(db_session, collection, downloaded_days(30), delete_older_episodes=True)
    _download(db_session, profile, recent_download, downloaded_at=NOW - timedelta(days=2))
    _download(db_session, profile, old_download, downloaded_at=NOW - timedelta(days=31))

    assert cleanup_older_episodes(db_session, profile) == 1
    assert _remaining(db_session) == {recent_download.id}


def test_only_date_lines_delete_downloads(db_session):
    from task_manager.tasks.workers.download_profile_worker._helpers import cleanup_older_episodes

    collection, season = _collection(db_session)
    trailer = _episode(db_session, collection, season, 1, "Trailer", days_ago=1)
    main = _episode(db_session, collection, season, 2, "Main", days_ago=2)
    older = _episode(db_session, collection, season, 3, "Older", days_ago=3)
    profile = _profile(
        db_session, collection, line("skip", "title", pattern="Trailer"), latest(1), delete_older_episodes=True,
    )
    for episode in (trailer, main, older):
        _download(db_session, profile, episode)

    # The skipped trailer keeps its download; the date line leaves the older episode out and deletes it.
    assert cleanup_older_episodes(db_session, profile) == 1
    assert _remaining(db_session) == {trailer.id, main.id}


def test_filter_requests_check_the_pattern():
    from pydantic import ValidationError

    from backend.api.models.download_profile import DownloadProfileFilterAPIIn

    item = DownloadProfileFilterAPIIn.model_validate({"action": "skip", "field": "title", "pattern": "(?i)trailer"})
    assert item.pattern == "(?i)trailer"
    with pytest.raises(ValidationError):
        DownloadProfileFilterAPIIn.model_validate({"action": "skip", "field": "title", "pattern": "(unclosed"})
    with pytest.raises(ValidationError):
        DownloadProfileFilterAPIIn.model_validate({"action": "skip", "field": "duration", "durationSeconds": 60})


def test_date_line_requests_choose_one_limit_and_cannot_skip():
    from pydantic import ValidationError

    from backend.api.models.download_profile import DownloadProfileFilterAPIIn

    assert DownloadProfileFilterAPIIn(action="only", field="published", count=25).count == 25
    assert DownloadProfileFilterAPIIn(action="keep", field="downloaded", days=7).days == 7
    with pytest.raises(ValidationError, match="only download or keep"):
        DownloadProfileFilterAPIIn(action="skip", field="published", count=5)
    with pytest.raises(ValidationError, match="a number of episodes or a date"):
        DownloadProfileFilterAPIIn(action="only", field="published", count=5, days=3)
    with pytest.raises(ValidationError, match="a number of days"):
        DownloadProfileFilterAPIIn(action="only", field="downloaded", count=5)


def test_a_profile_has_one_published_line_at_most():
    from pydantic import ValidationError

    from backend.api.models.download_profile import DownloadProfileAPIUpdate

    body = {
        "localMediaProfileId": 1, "enableProfile": True, "downloadWithCountdown": False, "redownloadFinal": False,
        "deleteOlderEpisodes": True,
        "filters": [{"action": "only", "field": "published", "count": 25}, {"action": "keep", "field": "published", "days": 7}],
    }
    with pytest.raises(ValidationError, match="one published line"):
        DownloadProfileAPIUpdate.model_validate(body)


def test_skipped_by_filter_names_the_filter(db_session):
    from backend.api.endpoints.download_profiles.service import skipped_by_filter

    collection, season = _collection(db_session)
    trailer = _episode(db_session, collection, season, 1, "Trailer", days_ago=1)
    _episode(db_session, collection, season, 2, "Main", days_ago=2)
    _episode(db_session, collection, season, 3, "Older", days_ago=3)
    profile = _profile(db_session, collection, line("skip", "title", pattern="Trailer"), latest(1))

    # The episode the date line leaves out is not skipped by a filter.
    [skipped] = skipped_by_filter(db_session, collection.id)

    assert (skipped.episode_id, skipped.download_profile_id) == (trailer.id, profile.id)
    assert skipped.filter.pattern == "Trailer"


def test_without_an_episode_types_line_every_type_is_downloaded(db_session):
    collection, season = _collection(db_session)
    _episode(db_session, collection, season, 1, "Regular")
    trailer = _episode(db_session, collection, season, 2, "Trailer")
    trailer.episode_identifier = "trailer.2026-01-02"
    db_session.flush()
    profile = _profile(db_session, collection, only_types("ep"))
    assert _wanted_titles(db_session, profile) == {"Regular"}

    with_filters(profile)
    db_session.flush()
    assert _wanted_titles(db_session, profile) == {"Regular", "Trailer"}


def test_a_collection_has_one_download_profile_per_local_media_profile(db_session):
    from fastapi import HTTPException

    from backend.api.endpoints.download_profiles.service import require_one_profile_per_local_media_profile

    collection, _season = _collection(db_session)
    profile = _profile(db_session, collection)
    check = dict(collection_id=collection.id, local_media_profile_id=profile.local_media_profile_id)

    with pytest.raises(HTTPException, match="already has a Download Profile"):
        require_one_profile_per_local_media_profile(db_session, **check)
    # Editing the profile itself is fine.
    require_one_profile_per_local_media_profile(db_session, exclude_profile_id=profile.id, **check)


def test_episode_type_filters_skip_and_keep_types(db_session):
    from backend.api.models.download_profile import DownloadProfileFilterAPIIn
    from backend.services.episode_filters import EpisodeSelection, evaluate

    collection, season = _collection(db_session)
    video = _episode(db_session, collection, season, 1, "A video")
    short = _episode(db_session, collection, season, 2, "A short")
    short.episode_identifier = "short.2"
    profile = _profile(
        db_session, collection,
        line("skip", "types", episode_types=["short"]), line("keep", "types", episode_types=["ep"]),
    )
    db_session.flush()

    assert _wanted_titles(db_session, profile) == {"A video"}
    assert profile.filters[0].episode_types == ["short"] and profile.filters[0].pattern is None
    assert evaluate(db_session, EpisodeSelection.of_profile(profile)).kept == {video.id}
    with pytest.raises(ValueError, match="at least one episode type"):
        DownloadProfileFilterAPIIn.model_validate({"action": "skip", "field": "types", "episodeTypes": []})


def test_without_a_seasons_line_every_season_is_downloaded(db_session):
    from backend.db.models import Season

    collection, first = _collection(db_session)
    collection.episode_identifier = "seasonal"
    second = Season(collection=collection, index=2, slug="which-s2", name="Two")
    db_session.add(second)
    db_session.flush()
    _episode(db_session, collection, first, 1, "First season")
    _episode(db_session, collection, second, 2, "Second season")
    profile = _profile(db_session, collection, only_seasons("which-s2"))
    assert _wanted_titles(db_session, profile) == {"Second season"}

    with_filters(profile)
    db_session.flush()
    assert _wanted_titles(db_session, profile) == {"First season", "Second season"}


def test_a_new_season_joins_seasons_lines_that_include_upcoming_seasons(db_session):
    from backend.services.seasons import create_season_record

    collection, first = _collection(db_session)
    collection.episode_identifier = "seasonal"
    upcoming = _profile(db_session, collection, only_seasons("which-s1", upcoming=True))
    fixed = _profile(db_session, collection, only_seasons("which-s1"))

    create_season_record(
        db_session, collection_id=collection.id, index=2, slug="which-s2", name="Two", update_collection_profiles=True,
    )

    assert upcoming.filters[0].season_slugs == ["which-s1", "which-s2"]
    assert fixed.filters[0].season_slugs == ["which-s1"]


def test_season_filters_skip_only_download_and_keep_seasons(db_session):
    from backend.db.models import Season
    from backend.services.episode_filters import EpisodeSelection, evaluate

    collection, first = _collection(db_session)
    collection.episode_identifier = "seasonal"
    second = Season(collection=collection, index=2, slug="which-s2", name="Two")
    db_session.add(second)
    db_session.flush()
    one = _episode(db_session, collection, first, 1, "First season")
    two = _episode(db_session, collection, second, 2, "Second season")
    profile = _profile(db_session, collection, line("skip", "seasons", season_slugs=["which-s1"]))
    assert _wanted_titles(db_session, profile) == {"Second season"}
    assert evaluate(db_session, EpisodeSelection.of_profile(profile)).left_out_by == {one.id: "filter:0"}

    with_filters(
        profile, line("only", "seasons", season_slugs=["which-s1"]), line("keep", "seasons", season_slugs=["which-s2"]),
    )
    db_session.flush()
    assert _wanted_titles(db_session, profile) == {"First season"}
    assert evaluate(db_session, EpisodeSelection.of_profile(profile)).kept == {two.id}


def test_a_season_filter_request_needs_a_season_or_upcoming_seasons():
    from backend.api.models.download_profile import DownloadProfileFilterAPIIn

    with pytest.raises(ValueError, match="at least one season"):
        DownloadProfileFilterAPIIn(action="skip", field="seasons", season_slugs=[])
    assert DownloadProfileFilterAPIIn(action="keep", field="seasons", season_slugs=["s1"]).season_slugs == ["s1"]
    assert DownloadProfileFilterAPIIn(action="only", field="seasons", season_slugs=[], include_upcoming=True)


def test_a_feed_lists_a_live_episode_only_past_the_filters_that_are_not_date_lines(db_session):
    from backend.services.episode_filters import filters_allow_new_episode

    collection, season = _collection(db_session)
    live = _episode(db_session, collection, season, 1, "Live: Trailer")

    assert filters_allow_new_episode([only_types("ep"), latest(1)], live)
    assert not filters_allow_new_episode([line("skip", "title", pattern="Trailer"), latest(1)], live)
