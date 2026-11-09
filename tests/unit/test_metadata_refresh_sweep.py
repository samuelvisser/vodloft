"""The metadata refresh sweep looks new uploads up again on their Site's schedule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sources import Feature, ItemRef, ItemRefresh, VideoDetails, registry
from sources import ytdlp_runner as runner
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
        self.refused: set[str] = set()
        self.open: set[str] = set()

    def refresh_metadata(self, items):
        self.calls.append([item.slug for item in items])
        return ItemRefresh(
            details={
                item.slug: VideoDetails(slug=item.slug, url=item.url, title=self.titles[item.slug])
                for item in items if item.slug in self.titles
            },
            removed=frozenset(item.slug for item in items if item.slug in self.removed),
            refused={item.slug: "members" for item in items if item.slug in self.refused},
            open=frozenset(item.slug for item in items if item.slug in self.open),
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


@pytest.fixture
def swept(monkeypatch):
    from task_manager.tasks.workers.refresh_metadata import service

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    monkeypatch.setattr(service, "_last_sweep", None)
    return registry.register(SweptSource())


def _site_collection(session, site_settings, *, refresh="1h,1d"):
    from backend.db.models import Site

    site_settings(tube={"metadata_refresh": refresh})
    session.add(Site(key="tube", name="Tube", domains=["tube.example"]))
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


def test_an_upload_is_looked_up_on_each_interval_until_its_metadata_is_final(swept, session, site_settings):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session, site_settings)
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


def test_a_failed_lookup_is_tried_again_and_a_removed_upload_is_marked(swept, session, site_settings):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session, site_settings)
    now = datetime.now(timezone.utc)
    _add(session, collection, "gone", now - timedelta(minutes=5))
    _add(session, collection, "flaky", now - timedelta(minutes=5))
    swept.removed.add("gone")

    result = run_metadata_refresh(session, now=now)

    assert swept.calls == [["gone", "flaky"], ["flaky"], ["flaky"]]
    assert _episode(session, "gone").removed_from_source
    assert not _episode(session, "flaky").removed_from_source
    assert result.sites["Tube"].failed == 1 and result.sites["Tube"].removed == 1


def test_an_upload_only_members_may_see_is_locked_and_checked_again_later(swept, session, site_settings):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session, site_settings)
    now = datetime.now(timezone.utc)
    _add(session, collection, "members", now - timedelta(minutes=5))
    swept.refused.add("members")

    result = run_metadata_refresh(session, now=now)

    episode = _episode(session, "members")
    # Refused is an answer, so it is not asked again within the sweep.
    assert swept.calls == [["members"]] and result.sites["Tube"].failed == 0
    assert episode.access == "members" and episode.access_refused_at is not None
    assert episode.access_check_at is not None


def test_an_upload_that_opened_up_loses_its_badge(swept, session, site_settings):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session, site_settings)
    now = datetime.now(timezone.utc)
    _add(session, collection, "members", now - timedelta(minutes=5))
    _episode(session, "members").access = "members"
    session.commit()
    swept.titles["members"] = "Now for everyone"
    swept.open.add("members")

    run_metadata_refresh(session, now=now)

    assert _episode(session, "members").access is None


def test_a_site_with_its_refresh_off_is_never_looked_up(swept, session, site_settings):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    collection = _site_collection(session, site_settings, refresh="off")
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
    assert site_refresh_offsets(youtube.key)[-1] == 14 * 24 * 3600
    assert site_refresh_offsets(vimeo.key) == site_refresh_offsets(None)


def test_a_site_follows_its_own_schedule_then_its_default_then_the_system(site_settings):
    from backend.services.metadata_refresh import site_metadata_refresh, site_refresh_offsets
    from config import get_settings

    system = get_settings().new_episode_schedule.metadata_refresh_intervals
    assert site_metadata_refresh("youtube") == "30m,2h,6h,24h,3d,7d,14d"
    assert site_metadata_refresh("generic:vimeo.com") == system
    site_settings(youtube={"metadata_refresh": "1h"}, dailywire={"metadata_refresh": "off"})
    assert site_metadata_refresh("youtube") == "1h"
    assert site_refresh_offsets("dailywire") == ()


def _refs(*slugs: str) -> list[ItemRef]:
    return [ItemRef(slug, f"https://www.youtube.com/watch?v={slug}") for slug in slugs]


def test_with_a_key_youtube_answers_50_videos_at_a_time_and_says_which_are_gone(youtube, lookups):
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


def test_the_settings_list_each_site_with_the_settings_it_shows_and_starts_with(client, session):
    from backend.db.models import Site

    session.add(Site(key="youtube", name="YouTube", domains=["youtube.com"]))
    session.add(Site(key="generic:vimeo.com", name="vimeo.com", domains=["vimeo.com"]))
    session.commit()

    body = client.get("/api/settings/sites").json()
    specs = {spec["key"]: spec for spec in body["specs"]}
    assert specs["metadataRefresh"] == {"key": "metadataRefresh", "group": "scheduling", "hasSystemDefault": True}
    assert specs["sponsorblock"]["hasSystemDefault"] is False
    youtube, vimeo = body["sites"]
    assert (youtube["key"], vimeo["key"]) == ("youtube", "generic:vimeo.com")
    shown = {site["key"]: {setting["key"]: setting for setting in site["settings"]} for site in body["sites"]}
    # YouTube starts on its own preset; Vimeo follows the system default.
    assert shown["youtube"]["metadataRefresh"] == {"key": "metadataRefresh", "start": "30m,2h,6h,24h,3d,7d,14d", "preset": True}
    assert shown["generic:vimeo.com"]["metadataRefresh"] == {"key": "metadataRefresh", "start": None, "preset": False}
    # SponsorBlock has no system default, so only YouTube shows it, starting on its built-in value.
    assert shown["youtube"]["sponsorblock"] == {"key": "sponsorblock", "start": True, "preset": False}
    assert "sponsorblock" not in shown["generic:vimeo.com"]
    assert "autoSubtitles" in shown["generic:vimeo.com"] and "downloadWithCountdown" not in shown["youtube"]
    assert youtube["upgradeImprovements"] == ["resolution", "sponsorblock", "subtitles", "codec", "length"]


# --- The Daily Wire's episodes ------------------------------------------------------------------


def _dailywire_episode(session, slug: str, published: datetime):
    from backend.db.models import Episode, Season, Site

    session.add(Site(key="dailywire", name="The Daily Wire", domains=["dailywire.com"]))
    collection = _collection(session, f"show-{slug}", source_key="dailywire")
    collection.site_key = "dailywire"
    season = Season(collection=collection, index=1, slug="season-1", name="One")
    episode = Episode(
        uuid=f"uuid-{slug}", type="episode", source_key="dailywire", collection=collection, season=season, index=1,
        episode_identifier=f"ep.{slug}", slug=slug, title=slug, publish_status="published_final",
        metadata_is_final=False, sharing_url=f"https://example.test/{slug}", published_date=published,
    )
    session.add(episode)
    session.commit()
    return episode.id


@pytest.fixture
def daily_wire(monkeypatch, site_settings):
    """The Daily Wire's own refresh, answering from a list instead of The Daily Wire."""
    from task_manager.tasks.workers.refresh_metadata import service

    site_settings(dailywire={"metadata_refresh": "1h,1d"})

    monkeypatch.setattr(service, "_last_sweep", None)
    answers: list[bool | None | Exception] = []
    asked: list[int] = []

    def refresh(_session, episode_id):
        asked.append(episode_id)
        answer = answers.pop(0) if answers else True
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(service, "refresh_dailywire_episode", refresh)
    return answers, asked


def test_a_daily_wire_episode_is_refreshed_one_by_one_on_its_sites_schedule(daily_wire, session):
    from task_manager.tasks.workers.refresh_metadata.service import refresh_episode_now, run_metadata_refresh

    answers, asked = daily_wire
    now = datetime.now(timezone.utc)
    episode_id = _dailywire_episode(session, "show", now - timedelta(minutes=30))

    assert "The Daily Wire: looked up 1, 1 changed" in run_metadata_refresh(session, now=now).summary()
    assert run_metadata_refresh(session, now=now + timedelta(minutes=10)).summary() == "No metadata refresh is due"
    # A lookup that fails is tried again within the sweep.
    answers.extend([RuntimeError("HTTP error 503"), True])
    run_metadata_refresh(session, now=now + timedelta(minutes=40))
    assert asked == [episode_id] * 3

    run_metadata_refresh(session, now=now + timedelta(days=1))
    session.expire_all()
    assert _episode(session, "show").metadata_is_final

    # Refresh now looks it up again, and the sweep follows it as long as its schedule says.
    refresh_episode_now(session, episode_id, now=now + timedelta(days=2))
    session.expire_all()
    assert len(asked) == 5 and _episode(session, "show").metadata_is_final


def test_a_daily_wire_episode_that_changed_hands_is_not_made_final(daily_wire, session):
    from task_manager.tasks.workers.refresh_metadata.service import run_metadata_refresh

    answers, _ = daily_wire
    now = datetime.now(timezone.utc)
    _dailywire_episode(session, "show", now - timedelta(days=2))

    # Live again: the pending checks follow it from here.
    answers.append(False)
    run_metadata_refresh(session, now=now)
    session.expire_all()
    assert not _episode(session, "show").metadata_is_final



_MEMBERS_ERROR = "ERROR: [youtube] v2: Join this channel to get access to members-only content like this video"


def _refusing(monkeypatch, slug: str) -> None:
    """yt-dlp refuses to look up this one video for lack of a channel membership."""
    answer = runner.run_json

    def run_json(*args, **_kwargs):
        if args[-1].endswith(f"v={slug}"):
            raise runner.YtDlpError(_MEMBERS_ERROR)
        return answer(*args)

    monkeypatch.setattr(runner, "run_json", run_json)


def test_with_a_key_ytdlp_says_which_youtube_videos_are_for_members(youtube, lookups, monkeypatch):
    answers, _ = lookups
    youtube.videos["v1"] = _video_item("v1")
    youtube.videos["v2"] = _video_item("v2")
    answers[("--no-playlist", "https://www.youtube.com/watch?v=v1")] = {
        "id": "v1", "extractor_key": "Youtube", "title": "v1", "availability": "subscriber_only",
    }
    _refusing(monkeypatch, "v2")

    refresh = YtDlpSource().refresh_metadata(_refs("v1", "v2"))

    # The API still gives the details; yt-dlp only adds the access.
    assert refresh.details["v1"].access == "members" and refresh.details["v1"].description == "About v1"
    assert refresh.details["v2"].access is None
    assert refresh.refused == {"v2": "members"}


def test_without_a_key_a_refused_lookup_says_the_video_is_for_members(lookups, monkeypatch):
    _refusing(monkeypatch, "v1")

    refresh = YtDlpSource().refresh_metadata(_refs("v1", "v2"))

    assert refresh.details == {} and refresh.refused == {"v1": "members"}


def test_a_lookup_that_needs_no_access_says_the_video_is_open(lookups):
    answers, _ = lookups
    answers[("--no-playlist", "https://www.youtube.com/watch?v=v1")] = {
        "id": "v1", "extractor_key": "Youtube", "title": "v1", "availability": "public",
    }
    answers[("--no-playlist", "https://www.youtube.com/watch?v=v2")] = {
        "id": "v2", "extractor_key": "Youtube", "title": "v2", "availability": "subscriber_only",
    }

    refresh = YtDlpSource().refresh_metadata(_refs("v1", "v2"))

    assert refresh.open == {"v1"} and refresh.details["v2"].access == "members"
