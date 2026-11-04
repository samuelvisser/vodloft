"""The metadata refresh sweep looks new uploads up again on their Site's schedule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sources import Feature, ItemRef, ItemRefresh, VideoDetails, registry
from sources.ytdlp import YtDlpSource

from test_quick_check import _collection, session  # noqa: F401
from test_youtube_catalogue import _video_item, lookups, youtube, ytdlp_dir  # noqa: F401
from test_ytdlp_collections import ListedSource


class SweptSource(ListedSource):
    id = "swept"
    features = frozenset({Feature.COLLECTIONS, Feature.EPISODE_LISTS, Feature.METADATA_REFRESH})

    def __init__(self):
        super().__init__()
        self.calls: list[list[str]] = []
        self.titles: dict[str, str] = {}
        self.removed: set[str] = set()

    def refresh_metadata(self, items):
        self.calls.append([item.slug for item in items])
        return ItemRefresh(
            details={
                item.slug: VideoDetails(slug=item.slug, url=item.url, title=self.titles[item.slug])
                for item in items if item.slug in self.titles
            },
            removed=frozenset(item.slug for item in items if item.slug in self.removed),
        )


@pytest.fixture
def swept(monkeypatch):
    from task_manager.tasks.workers.refresh_metadata import service

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    monkeypatch.setattr(service, "_last_sweep", None)
    return registry.register(SweptSource())


def _site_collection(session, *, mode="own", intervals="1h,1d"):
    from backend.db.models import Site

    session.add(Site(key="tube", name="Tube", domains=["tube.example"], refresh_mode=mode, refresh_intervals=intervals))
    collection = _collection(session, "UC1", source_key="swept")
    collection.site_key = "tube"
    session.commit()
    return collection


def _add(session, collection, slug: str, published: datetime):
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    add_listed_episodes(session, collection_id=collection.id, found=[
        VideoDetails(slug=slug, url=f"https://tube.example/{slug}", title=slug, published_at=published),
    ])
    session.commit()


def _episode(session, slug: str):
    from backend.db.models import Episode

    session.expire_all()
    return session.query(Episode).filter(Episode.source_slug == slug).one()


def test_an_upload_is_looked_up_on_each_interval_until_its_metadata_is_final(swept, session):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session)
    now = datetime.now(timezone.utc)
    _add(session, collection, "new", now - timedelta(minutes=30))
    # A video from the back catalogue is done from the start.
    _add(session, collection, "old", now - timedelta(days=30))
    assert not _episode(session, "new").metadata_is_final
    assert _episode(session, "old").metadata_is_final
    swept.titles["new"] = "A better title"

    # After a restart, every unfinished upload is looked up once.
    first = run_metadata_refresh(session, now=now)
    assert swept.calls == [["new"]]
    assert _episode(session, "new").title == "A better title"
    assert "Tube: looked up 1, 1 changed" in first.summary()

    # No interval passed since then.
    assert run_metadata_refresh(session, now=now + timedelta(minutes=10)).summary() == "No metadata refresh is due"
    assert len(swept.calls) == 1

    # The 1h interval passes.
    swept.titles["new"] = "The final title"
    run_metadata_refresh(session, now=now + timedelta(minutes=40))
    assert len(swept.calls) == 2 and not _episode(session, "new").metadata_is_final

    # The last interval passes: one more look, then the metadata is final.
    run_metadata_refresh(session, now=now + timedelta(days=1))
    episode = _episode(session, "new")
    assert len(swept.calls) == 3
    assert episode.metadata_is_final and episode.title == "The final title"
    # The identifier, which file names follow, never changes.
    assert episode.episode_identifier == "ep.1"


def test_a_failed_lookup_is_tried_again_and_a_removed_upload_is_marked(swept, session):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session)
    now = datetime.now(timezone.utc)
    _add(session, collection, "gone", now - timedelta(minutes=5))
    _add(session, collection, "flaky", now - timedelta(minutes=5))
    swept.removed.add("gone")

    result = run_metadata_refresh(session, now=now)

    assert swept.calls == [["gone", "flaky"], ["flaky"], ["flaky"]]
    assert _episode(session, "gone").removed_from_source
    assert not _episode(session, "flaky").removed_from_source
    assert result.sites["Tube"].failed == 1 and result.sites["Tube"].removed == 1


def test_a_site_with_its_refresh_off_is_never_looked_up(swept, session):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session, mode="off", intervals="1h,1d")
    now = datetime.now(timezone.utc)
    _add(session, collection, "new", now - timedelta(minutes=5))
    # Off means no schedule, so the upload is done from the start.
    assert _episode(session, "new").metadata_is_final

    _episode(session, "new").metadata_is_final = False
    session.commit()
    run_metadata_refresh(session, now=now)
    assert swept.calls == [] and _episode(session, "new").metadata_is_final


def test_a_new_site_starts_on_the_schedule_its_source_knows(session):
    from backend.services.metadata_refresh import site_refresh_offsets
    from backend.services.sites import site_record
    from sources import site_for

    youtube = site_record(session, site_for("https://www.youtube.com/@a-channel", "ytdlp"))
    vimeo = site_record(session, site_for("https://vimeo.com/123", "ytdlp"))
    assert (youtube.refresh_mode, youtube.refresh_intervals) == ("own", "30m,2h,6h,24h,3d,7d,14d")
    assert site_refresh_offsets(youtube)[-1] == 14 * 24 * 3600
    assert (vimeo.refresh_mode, vimeo.refresh_intervals) == ("system", None)


def _refs(*slugs: str) -> list[ItemRef]:
    return [ItemRef(slug, f"https://www.youtube.com/watch?v={slug}") for slug in slugs]


def test_with_a_key_youtube_answers_50_videos_at_a_time_and_says_which_are_gone(youtube):
    youtube.videos["v1"] = _video_item("v1")
    youtube.videos["v1"]["snippet"]["title"] = "A better title"
    youtube.videos["soon"] = _video_item("soon", broadcast="upcoming")

    refresh = YtDlpSource().refresh_metadata(_refs("v1", "soon", "gone"))

    assert refresh.details["v1"].title == "A better title"
    assert refresh.details["v1"].description == "About v1"
    # A video that is not finished yet is neither refreshed nor gone.
    assert set(refresh.details) == {"v1"} and refresh.removed == {"gone"}
    assert [name for name, _ in youtube.calls] == ["videos"]


def test_other_sites_are_looked_up_one_by_one_and_a_failure_removes_nothing(lookups):
    answers, calls = lookups
    answers[("--no-playlist", "https://vimeo.com/1")] = {"id": "1", "extractor_key": "Vimeo", "title": "Renamed",
                                                         "webpage_url": "https://vimeo.com/1"}

    refresh = YtDlpSource().refresh_metadata([ItemRef("vimeo-1", "https://vimeo.com/1"), ItemRef("vimeo-2", "https://vimeo.com/2")])

    assert [details.title for details in refresh.details.values()] == ["Renamed"]
    assert refresh.removed == frozenset()
    assert len(calls) == 2


@pytest.fixture
def client(session, monkeypatch):  # noqa: F811
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.settings import router as settings_router_module

    @contextmanager
    def db_session():
        yield session

    monkeypatch.setattr(settings_router_module, "db_session", db_session)
    app = FastAPI()
    app.include_router(settings_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def test_a_sites_schedule_is_chosen_in_the_settings(client, session):
    from backend.db.models import Site

    session.add(Site(key="youtube", name="YouTube", domains=["youtube.com"], refresh_mode="own", refresh_intervals="30m,2h"))
    session.commit()

    [row] = client.get("/api/settings/site-refresh").json()
    assert row == {
        "key": "youtube", "name": "YouTube", "domains": ["youtube.com"],
        "refreshMode": "own", "refreshIntervals": "30m,2h", "pendingChecks": True, "refreshes": True,
        "checksPending": True,
    }

    saved = client.put("/api/settings/site-refresh/youtube", json={"refreshMode": "system", "refreshIntervals": None}).json()
    # The Site's own schedule is kept for when it gets it back.
    assert (saved["refreshMode"], saved["refreshIntervals"]) == ("system", "30m,2h")

    refused = client.put("/api/settings/site-refresh/youtube", json={"refreshMode": "own", "refreshIntervals": "2h,1h"})
    assert refused.status_code == 422
    assert client.put("/api/settings/site-refresh/nope", json={"refreshMode": "off"}).status_code == 404
