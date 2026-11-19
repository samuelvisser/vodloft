"""The daily catalogue refresh: new titles and thumbnails, and videos the Source no longer has."""
from __future__ import annotations

import pytest

from sources import Feature, ItemRef, ItemRefresh, VideoDetails, registry
from sources.ytdlp import YtDlpSource
from sources.ytdlp.youtube_api import quota

from test_quick_check import _collection, _video, session  # noqa: F401
from test_youtube_catalogue import _video_item, lookups, youtube, ytdlp_dir  # noqa: F401
from test_ytdlp_collections import ListedSource

CHANNEL = "https://www.youtube.com/channel/UC1/videos"


def _refs(*slugs: str) -> list[ItemRef]:
    return [ItemRef(slug, f"https://www.youtube.com/watch?v={slug}") for slug in slugs]


def test_with_a_key_videos_missing_from_the_answer_are_removed(youtube, lookups):
    youtube.videos["v1"] = _video_item("v1")
    youtube.videos["v1"]["snippet"]["title"] = "A better title"

    refresh = YtDlpSource().refresh_items(CHANNEL, _refs("v1", "gone"))

    assert refresh.details["v1"].title == "A better title"
    assert refresh.removed == {"gone"}
    # One unit for up to 50 videos, and no Shorts lookups: a refresh keeps the tag.
    assert [name for name, _ in youtube.calls] == ["videos"]


def test_a_video_the_api_leaves_out_is_only_removed_when_ytdlp_says_it_is_gone(youtube, lookups, monkeypatch):
    from sources import ytdlp_runner as runner

    answers, _ = lookups
    answers[("--no-playlist", "https://www.youtube.com/watch?v=hidden")] = {
        "id": "hidden", "extractor_key": "Youtube", "title": "Still there",
    }
    answer = runner.run_json

    def run_json(*args, **_kwargs):
        if args[-1].endswith("v=members"):
            raise runner.YtDlpError("ERROR: [youtube] members: Join this channel to get access to members-only content")
        return answer(*args)

    monkeypatch.setattr(runner, "run_json", run_json)

    refresh = YtDlpSource().refresh_items(CHANNEL, _refs("hidden", "members", "gone"))

    assert refresh.details["hidden"].title == "Still there"
    assert refresh.refused == {"members": "members"}
    assert refresh.removed == {"gone"}


def test_with_the_quota_used_up_titles_come_from_ytdlp_and_nothing_is_removed(youtube, lookups):
    answers, _ = lookups
    quota.mark_exhausted()
    answers[("--flat-playlist", CHANNEL)] = {"entries": [
        {"id": "v1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v1", "title": "From yt-dlp"},
        {"id": "v2", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v2", "title": "[Private video]"},
    ]}

    refresh = YtDlpSource().refresh_items(CHANNEL, _refs("v1", "v2", "gone"))

    assert refresh.details["v1"].title == "From yt-dlp"
    assert refresh.details["v1"].image_url is None
    assert set(refresh.details) == {"v1"}
    assert refresh.removed == frozenset()
    assert youtube.calls == []


def test_a_failed_batch_falls_back_to_ytdlp_on_its_own(youtube, lookups):
    answers, _ = lookups
    youtube.failing.add("videos")
    answers[("--flat-playlist", CHANNEL)] = {"entries": [
        {"id": "v1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v1", "title": "From yt-dlp"},
    ]}

    refresh = YtDlpSource().refresh_items(CHANNEL, _refs("v1", "gone"))

    assert set(refresh.details) == {"v1"} and refresh.removed == frozenset()


def test_without_a_key_other_sites_refresh_from_their_listing(lookups):
    answers, _ = lookups
    url = "https://vimeo.com/showcase/1"
    answers[("--flat-playlist", url)] = {"entries": [
        {"id": "1", "ie_key": "Vimeo", "url": "https://vimeo.com/1", "title": "Renamed"},
    ]}

    refresh = YtDlpSource().refresh_items(url, [ItemRef("vimeo-1", "https://vimeo.com/1")])

    assert refresh.details["vimeo-1"].title == "Renamed"


def test_with_a_key_the_listing_still_marks_members_only_videos(youtube, lookups):
    answers, _ = lookups
    youtube.videos["v1"] = _video_item("v1")
    youtube.videos["v2"] = _video_item("v2")
    answers[("--flat-playlist", CHANNEL)] = {"entries": [
        {"id": "v1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v1", "title": "v1",
         "availability": "subscriber_only"},
        {"id": "v2", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v2", "title": "v2", "availability": "public"},
    ]}

    refresh = YtDlpSource().refresh_items(CHANNEL, _refs("v1", "v2"))

    assert refresh.details["v1"].access == "members"
    assert refresh.details["v2"].access is None
    # The rest still comes from the API.
    assert refresh.details["v1"].image_url is not None


def test_without_a_key_the_listing_marks_premium_videos(lookups):
    answers, _ = lookups
    answers[("--flat-playlist", CHANNEL)] = {"entries": [
        {"id": "v1", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=v1", "title": "v1",
         "availability": "premium_only"},
    ]}

    refresh = YtDlpSource().refresh_items(CHANNEL, _refs("v1"))

    assert refresh.details["v1"].access == "premium"


class RefreshingSource(ListedSource):
    id = "refreshing"
    features = frozenset({Feature.COLLECTIONS, Feature.EPISODE_LISTS, Feature.CATALOGUE_REFRESH})

    def __init__(self):
        super().__init__()
        self.refresh = ItemRefresh()

    def refresh_items(self, url, items):
        return self.refresh


@pytest.fixture
def refreshing(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(RefreshingSource())


def test_the_refresh_updates_marks_and_unmarks_episodes(refreshing, session):
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes
    from task_manager.tasks.workers.fetch_new_episodes.refresh import run_catalogue_refresh

    collection = _collection(session, "UC1", source_key="refreshing")
    add_listed_episodes(session, collection_id=collection.id, found=[_video("v1", 1), _video("v2", 2), _video("v3", 3)])
    session.commit()
    session.query(Episode).filter(Episode.source_slug == "v3").one().removed_from_source = True
    session.commit()
    refreshing.refresh = ItemRefresh(
        details={
            "v1": VideoDetails(slug="v1", url="u", title="New title", image_url="https://i.example/v1.jpg"),
            "v3": VideoDetails(slug="v3", url="u", title="v3"),
        },
        removed=frozenset({"v2"}),
    )

    result = run_catalogue_refresh(session)

    episodes = {e.source_slug: e for e in session.query(Episode).filter(Episode.collection_id == collection.id)}
    assert (result.collections, result.updated, result.removed, result.returned) == (1, 1, 1, 1)
    assert episodes["v1"].title == "New title"
    assert episodes["v1"].thumbnail_landscape_path == "https://i.example/v1.jpg"
    # File names follow the identifier, which never changes.
    assert episodes["v1"].episode_identifier == "ep.1"
    assert episodes["v2"].removed_from_source and episodes["v2"].title == "v2"
    assert not episodes["v3"].removed_from_source

    # A second run with the same answer changes nothing.
    again = run_catalogue_refresh(session)
    assert (again.updated, again.removed, again.returned) == (0, 0, 0)


def test_the_refresh_locks_members_only_episodes_but_never_unlocks_them(refreshing, session):
    from datetime import datetime, timezone

    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes
    from task_manager.tasks.workers.fetch_new_episodes.refresh import run_catalogue_refresh

    collection = _collection(session, "UC1", source_key="refreshing")
    add_listed_episodes(session, collection_id=collection.id, found=[_video("v1", 1), _video("v2", 2)])
    session.commit()
    refused = session.query(Episode).filter(Episode.source_slug == "v2").one()
    refused.access, refused.access_refused_at = "members", datetime.now(timezone.utc)
    session.commit()
    add_listed_episodes(session, collection_id=collection.id, found=[_video("v3", 3)])
    session.commit()
    refreshing.refresh = ItemRefresh(details={
        "v1": VideoDetails(slug="v1", url="u", title="v1", access="members"),
        "v2": VideoDetails(slug="v2", url="u", title="v2"),
    }, refused={"v3": "members"})

    run_catalogue_refresh(session)

    episodes = {e.source_slug: e for e in session.query(Episode).filter(Episode.collection_id == collection.id)}
    assert episodes["v1"].access == "members"
    # Saying nothing about access does not prove anyone may download it.
    assert episodes["v2"].access == "members" and episodes["v2"].access_refused_at is not None
    # One the Source would not show for lack of a membership is locked, and checked again later.
    assert episodes["v3"].access_refused_at is not None and episodes["v3"].access_check_at is not None
    assert not episodes["v3"].removed_from_source
