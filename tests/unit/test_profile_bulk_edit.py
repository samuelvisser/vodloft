"""Bulk edit on the three profile tables: Select all takes what the filters match, and changes skip what doesn't fit."""
from __future__ import annotations

import pytest
from conftest import available_artifact, use_database
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session():
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _collection(index: int, *, youtube: bool):
    from backend.db.models import Collection
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    return Collection(
        source_key="ytdlp" if youtube else "dailywire", uuid=f"collection-{index}", slug=f"show-{index}",
        title=f"Show {index:02d}", description=None, membership_level="FREE",
        sharing_url=f"https://www.youtube.com/@show{index}" if youtube else f"https://www.dailywire.com/show/{index}",
        type=CollectionType.PODCAST.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host", author_slug="host",
    )


def _library(s: Session):
    """Four collections, two on The Daily Wire and two on YouTube, each with an audio Download Profile and a feed."""
    from backend.db.models import DownloadProfile, LocalMediaProfile, RssStreamProfile

    audio = LocalMediaProfile(slug="audio", name="Audio", preferred_format="format_audio_only",
                              output_template="/downloads/audio/{{ episode }}.ext")
    video = LocalMediaProfile(slug="video", name="Video", preferred_format="format_1080p",
                              output_template="/downloads/video/{{ episode }}.ext")
    collections = [_collection(index, youtube=index >= 2) for index in range(4)]
    s.add_all([audio, video, *collections])
    s.flush()
    for index, collection in enumerate(collections):
        s.add(DownloadProfile(
            collection_id=collection.id, local_media_profile_id=audio.id, enable_profile=index % 2 == 0,
            download_with_countdown=False, redownload_final=False, delete_older_episodes=False,
            sponsorblock_enabled=False,
        ))
        s.add(RssStreamProfile(
            collection_id=collection.id, enable_profile=True, use_downloads=True, use_source_stream=False,
            preferred_format="format_audio_only", prefer_exact_match=False, max_items=50 if index else 100,
            feed_url=f"https://example.test/feed/{index}",
        ))
    s.commit()
    return audio, video, collections


def _download_profiles(s: Session):
    from backend.db.models import DownloadProfile

    return s.query(DownloadProfile).order_by(DownloadProfile.id).all()


def test_select_all_takes_every_download_profile_the_filters_match(session) -> None:
    from backend.api.endpoints.download_profiles.as_view.service import get_download_profile_ids
    from backend.api.models.profile_list import DownloadProfileListQuery

    _library(session)
    profiles = _download_profiles(session)
    assert get_download_profile_ids(session, DownloadProfileListQuery()).ids == [item.id for item in profiles]
    enabled = get_download_profile_ids(session, DownloadProfileListQuery(status=["enabled"])).ids
    assert enabled == [item.id for item in profiles if item.enable_profile]
    assert get_download_profile_ids(session, DownloadProfileListQuery(source=["ytdlp"], status=["disabled"])).ids == [
        profiles[3].id,
    ]


def test_download_profile_changes_skip_settings_a_site_does_not_have(session) -> None:
    from backend.api.endpoints.download_profiles.bulk import change_download_profiles, summarize_download_profiles
    from backend.api.models.profile_bulk import BulkChangeIn, BulkSelectionIn, DownloadProfileBulkChangesIn

    _library(session)
    profiles = _download_profiles(session)
    ids = [item.id for item in profiles]

    summary = summarize_download_profiles(session, BulkSelectionIn(ids=ids))
    assert summary.count == 4
    assert {item.value: item.count for item in summary.fields["enableProfile"].values} == {True: 2, False: 2}
    assert summary.fields["sponsorblockEnabled"].offered == 2  # only the YouTube ones
    assert summary.fields["sponsorblockEnabled"].sites_without == ["The Daily Wire"]
    assert summary.fields["enableProfile"].sites_without == []

    body = BulkChangeIn[DownloadProfileBulkChangesIn].model_validate(
        {"ids": ids, "changes": {"enableProfile": True, "sponsorblockEnabled": True}})
    result = change_download_profiles(session, body)
    session.commit()
    assert (result.done, result.skipped) == (4, [])
    assert all(item.enable_profile for item in profiles)
    assert [item.sponsorblock_enabled for item in profiles] == [False, False, True, True]

    only_sponsorblock = BulkChangeIn[DownloadProfileBulkChangesIn].model_validate(
        {"ids": ids[:1], "changes": {"sponsorblockEnabled": False}})
    result = change_download_profiles(session, only_sponsorblock)
    assert result.done == 0
    assert [item.name for item in result.skipped] == ["Show 00 (Audio)"]


def test_moving_download_profiles_to_another_media_profile_skips_a_collection_that_has_one(session) -> None:
    from backend.api.endpoints.download_profiles.bulk import change_download_profiles
    from backend.api.models.profile_bulk import BulkChangeIn, DownloadProfileBulkChangesIn
    from backend.db.models import DownloadProfile

    _audio, video, collections = _library(session)
    session.add(DownloadProfile(
        collection_id=collections[1].id, local_media_profile_id=video.id, enable_profile=True,
        download_with_countdown=False, redownload_final=False, delete_older_episodes=False,
    ))
    session.commit()
    first, second = _download_profiles(session)[:2]

    body = BulkChangeIn[DownloadProfileBulkChangesIn].model_validate(
        {"ids": [first.id, second.id], "changes": {"localMediaProfileId": video.id}})
    result = change_download_profiles(session, body)
    session.commit()
    assert result.done == 1
    assert [(item.id, item.reason) for item in result.skipped] == [
        (second.id, "This Collection already has a Download Profile for this Local Media Profile"),
    ]
    assert first.local_media_profile_id == video.id


def test_bulk_changes_need_a_setting_with_a_value() -> None:
    from pydantic import ValidationError

    from backend.api.models.profile_bulk import BulkChangeIn, DownloadProfileBulkChangesIn

    for changes in ({}, {"enableProfile": None}):
        with pytest.raises(ValidationError):
            BulkChangeIn[DownloadProfileBulkChangesIn].model_validate({"ids": [1], "changes": changes})
    with pytest.raises(ValidationError):
        BulkChangeIn[DownloadProfileBulkChangesIn].model_validate({"ids": [], "changes": {"enableProfile": True}})


def test_stream_profile_changes_follow_the_feed_rules(session) -> None:
    from backend.api.endpoints.stream_profiles.as_view.service import get_stream_profile_ids
    from backend.api.endpoints.stream_profiles.bulk import change_stream_profiles, summarize_stream_profiles
    from backend.api.models.profile_bulk import BulkChangeIn, BulkSelectionIn, StreamProfileBulkChangesIn
    from backend.api.models.profile_list import StreamProfileListQuery
    from backend.db.models import RssStreamProfile
    from backend.security.access import Access

    _library(session)
    access = Access.full()
    ids = get_stream_profile_ids(session, access, StreamProfileListQuery()).ids
    assert len(ids) == 4

    summary = summarize_stream_profiles(session, access, BulkSelectionIn(ids=ids))
    assert {item.value: item.count for item in summary.fields["maxItems"].values} == {50: 3, 100: 1}
    # Audio feeds have no live episodes.
    assert summary.fields["streamLiveEpisodes"].offered == 0

    body = BulkChangeIn[StreamProfileBulkChangesIn].model_validate(
        {"ids": ids, "changes": {"maxItems": 25, "enableProfile": False}})
    result = change_stream_profiles(session, access, body)
    session.commit()
    assert (result.done, result.skipped) == (4, [])
    feeds = session.query(RssStreamProfile).all()
    assert {(item.max_items, item.enable_profile) for item in feeds} == {(25, False)}

    live = BulkChangeIn[StreamProfileBulkChangesIn].model_validate(
        {"ids": ids[:1], "changes": {"streamLiveEpisodes": True}})
    assert change_stream_profiles(session, access, live).done == 0


def test_local_media_profiles_change_behavior_and_delete_skips_one_in_use(session) -> None:
    from backend.api.endpoints.local_media_profiles.bulk import (
        change_local_media_profiles, delete_local_media_profiles,
    )
    from backend.api.endpoints.local_media_profiles.service import get_local_media_profile_ids
    from backend.api.models.profile_bulk import BulkChangeIn, BulkSelectionIn, LocalMediaProfileBulkChangesIn
    from backend.api.models.profile_list import LocalMediaProfileListQuery
    from backend.db.models import LocalMediaProfileBase, MovieLocalMediaProfile

    audio, video, _collections = _library(session)
    movie = MovieLocalMediaProfile(slug="movies", name="Movies", preferred_format="format_1080p",
                                   output_template="/downloads/movies/{{ title }}.ext")
    session.add(movie)
    session.commit()
    ids = get_local_media_profile_ids(session, LocalMediaProfileListQuery()).ids
    assert ids == [audio.id, movie.id, video.id]
    assert get_local_media_profile_ids(session, LocalMediaProfileListQuery(used_for=["movie"])).ids == [movie.id]

    body = BulkChangeIn[LocalMediaProfileBulkChangesIn].model_validate(
        {"ids": ids, "changes": {"thumbnailMode": "sidecar", "metadataMode": "nfo"}})
    assert change_local_media_profiles(session, body).done == 3
    session.commit()
    assert {(item.thumbnail_mode, item.metadata_mode) for item in session.query(LocalMediaProfileBase)} == {
        ("sidecar", "nfo"),
    }

    result = delete_local_media_profiles(session, BulkSelectionIn(ids=ids))
    session.commit()
    assert result.done == 2
    assert [item.name for item in result.skipped] == ["Audio"]
    assert "Download Profiles still use it" in result.skipped[0].reason
    assert [item.id for item in session.query(LocalMediaProfileBase)] == [audio.id]


def test_bulk_endpoints_take_camel_case_and_return_what_happened(session) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.download_profiles.router import router as download_profiles

    _library(session)
    use_database(session.get_bind())
    app = FastAPI()
    app.include_router(download_profiles)
    client = TestClient(app)

    ids = client.get("/download-profiles/as-view/ids", params={"status": ["disabled"]}).json()["ids"]
    assert len(ids) == 2
    response = client.post("/download-profiles/bulk/change", json={"ids": ids, "changes": {"enableProfile": True}})
    assert response.status_code == 200, response.text
    assert response.json() == {"done": 2, "skipped": []}
    assert client.get("/download-profiles/as-view/ids", params={"status": ["disabled"]}).json() == {"ids": []}
    assert client.post("/download-profiles/bulk/change", json={"ids": ids, "changes": {}}).status_code == 422
    response = client.post("/download-profiles/bulk/delete", json={"ids": ids})
    assert response.json() == {"done": 2, "skipped": []}
    assert len(client.get("/download-profiles/as-view/ids").json()["ids"]) == 2
