"""The optional YouTube Data API key of the yt-dlp Source: its client, quota and settings."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config.registry import get_settings, replace_settings
from config.settings.submodels import YouTubeApiSettings
from sources import ApiKeyRejected, Feature, get_source
from sources import ytdlp_runner as runner
from sources.ytdlp.youtube_api import (
    ApiKeyError, ApiNotEnabledError, NotFoundError, QuotaExceededError, Share, TemporaryApiError, YouTubeApiClient,
    client as client_module, key as key_store, quota,
)


@pytest.fixture(autouse=True)
def ytdlp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ytdlp_directory", lambda: tmp_path / "yt-dlp")
    monkeypatch.setattr(client_module.pacing, "pause", lambda *_args, **_kwargs: None)
    return tmp_path / "yt-dlp"


@pytest.fixture
def quota_settings():
    original = get_settings()

    def apply(**values):
        replace_settings(original.model_copy(update={"youtube_api": YouTubeApiSettings(**values)}))

    yield apply
    replace_settings(original)


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self.ok = status < 400
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    """Answers API calls in order, and remembers what was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def google_error(status: int, reason: str, **metadata) -> FakeResponse:
    return FakeResponse(status, {"error": {
        "code": status, "message": f"{reason} happened", "errors": [{"reason": reason}],
        "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "metadata": metadata}],
    }})


def test_calls_send_the_key_in_a_header_and_count_units_against_their_share():
    session = FakeSession(FakeResponse(200, {"items": [{"id": "v1"}]}), FakeResponse(200, {"items": []}))
    api = YouTubeApiClient("AIzaSECRET", session=session)

    assert api.videos(["v1", "v2"], share=Share.CHECKS) == [{"id": "v1"}]
    api.search("veritasium")

    url, params, headers = session.calls[0]
    assert url.endswith("/videos") and params["id"] == "v1,v2"
    assert headers == {"X-Goog-Api-Key": "AIzaSECRET"}
    assert "AIzaSECRET" not in str(params)
    status = quota.status()
    assert (status.usage(Share.CHECKS).used, status.usage(Share.SEARCH).used, status.used) == (1, 100, 101)


def test_a_full_share_stops_calls_but_test_key_always_runs(quota_settings):
    quota_settings(daily_quota=100, checks_quota=1, search_quota=0)
    session = FakeSession(FakeResponse(200, {"items": []}), FakeResponse(200, {"items": []}))
    api = YouTubeApiClient("key", session=session)

    api.playlist_items("UU1", share=Share.CHECKS)
    with pytest.raises(QuotaExceededError):
        api.playlist_items("UU1", share=Share.CHECKS)
    with pytest.raises(QuotaExceededError):
        api.search("anything")
    api.test()
    assert len(session.calls) == 2
    assert quota.status().usage(Share.RESERVE).limit == 99


def test_google_errors_become_the_kinds_the_source_acts_on():
    def error_for(response):
        api = YouTubeApiClient("key", stored=False, session=FakeSession(response))
        with pytest.raises(Exception) as caught:
            api.videos(["v"], share=Share.RESERVE)
        return caught.value

    assert isinstance(error_for(google_error(400, "API_KEY_INVALID")), ApiKeyError)
    not_enabled = error_for(google_error(403, "SERVICE_DISABLED", activationUrl="https://console.example/enable"))
    assert isinstance(not_enabled, ApiNotEnabledError) and not_enabled.fix_url == "https://console.example/enable"
    assert isinstance(error_for(google_error(403, "API_KEY_SERVICE_BLOCKED")), ApiKeyError)
    assert isinstance(error_for(google_error(404, "playlistNotFound")), NotFoundError)
    assert not quota.status().exhausted
    assert isinstance(error_for(google_error(403, "quotaExceeded")), QuotaExceededError)
    # Google's word counts for the rest of the Pacific day.
    assert quota.status().exhausted
    assert not quota.try_spend(Share.RESERVE, 1)


def test_temporary_failures_are_retried_and_never_show_the_key():
    session = FakeSession(
        requests.ConnectionError("https://www.googleapis.com/youtube/v3/videos?key=AIzaSECRET failed"),
        google_error(503, "backendError"),
        FakeResponse(200, {"items": [{"id": "v"}]}),
    )
    assert YouTubeApiClient("AIzaSECRET", session=session).videos(["v"], share=Share.CHECKS) == [{"id": "v"}]
    assert quota.status().usage(Share.CHECKS).used == 3

    failing = FakeSession(*[requests.ConnectionError("down with AIzaSECRET")] * 3)
    with pytest.raises(TemporaryApiError) as caught:
        YouTubeApiClient("AIzaSECRET", session=failing).videos(["v"], share=Share.CHECKS)
    assert "AIzaSECRET" not in str(caught.value)
    assert "•••" in str(caught.value)


def test_the_quota_day_follows_pacific_time():
    # 07:30 UTC on 28 October is still 27 October in California.
    morning = datetime(2026, 10, 28, 7, 30, tzinfo=timezone.utc)
    assert quota.pacific_day(morning).isoformat() == "2026-10-28"
    late = datetime(2026, 10, 28, 6, 30, tzinfo=timezone.utc)
    assert quota.pacific_day(late).isoformat() == "2026-10-27"
    assert quota.next_reset(late) == datetime(2026, 10, 28, 7, 0, tzinfo=timezone.utc)

    quota.try_spend(Share.CHECKS, 5, now=late)
    assert quota.status(now=late).usage(Share.CHECKS).used == 5
    assert quota.status(now=morning).usage(Share.CHECKS).used == 0


def test_check_interval_follows_the_show_count_and_the_budget():
    # 100 channels of 500 videos: the daily re-scan costs 2,000 units.
    rescan = quota.rescan_units([500] * 100)
    assert rescan == 2_000
    assert 30 <= quota.check_interval_minutes(100, rescan, 7_000, 10) <= 35
    assert quota.check_interval_minutes(20, quota.rescan_units([100] * 20), 7_000, 10) == 10
    assert quota.check_interval_minutes(100, rescan, 1_000, 10) is None


def test_the_shares_must_fit_in_the_daily_quota():
    with pytest.raises(ValidationError):
        YouTubeApiSettings(daily_quota=10_000, checks_quota=9_000, search_quota=2_000)
    with pytest.raises(ValidationError):
        YouTubeApiSettings(min_check_interval_minutes=5)
    assert YouTubeApiSettings().daily_quota == 10_000


def test_saving_a_key_tests_it_first(monkeypatch):
    source = get_source("ytdlp")
    assert source.has(Feature.API_KEY)
    sessions = [FakeSession(google_error(400, "API_KEY_INVALID")), FakeSession(FakeResponse(200, {"items": []}))]
    monkeypatch.setattr(client_module.requests, "Session", lambda: sessions.pop(0))

    with pytest.raises(ApiKeyRejected):
        source.save_api_key("AIzaBAD")
    assert source.api_status().key_hint is None
    # A rejected new key is not a problem with the stored one.
    assert source.problems() == []

    source.save_api_key("  AIzaGOODQ4c ")
    status = source.api_status()
    assert status.key_hint == "Q4c"
    assert key_store.load() == "AIzaGOODQ4c"
    assert key_store.redact("calling with AIzaGOODQ4c") == "calling with •••"


def test_a_stored_key_that_stops_working_needs_attention(monkeypatch):
    source = get_source("ytdlp")
    key_store.save("AIzaOLD")
    monkeypatch.setattr(client_module.requests, "Session", lambda: FakeSession(google_error(403, "SERVICE_DISABLED")))

    with pytest.raises(ApiKeyRejected) as caught:
        source.test_api_key()
    assert "not enabled" in str(caught.value)
    [problem] = source.problems()
    assert problem.title == "YouTube API key does not work"
    assert problem.fix_url

    quota.mark_exhausted()
    assert [p.title for p in source.problems()] == ["YouTube API key does not work", "YouTube API quota used up"]
    source.remove_api_key()
    assert source.problems() == []


@pytest.fixture
def api_client(monkeypatch):
    from backend.api.endpoints.sources import router as source_router_module
    from backend.db.core import Base
    from backend.db.models import Episode, Show
    import backend.api.endpoints.shows.router  # noqa: F401  (loads every model first)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as s:
        for slug, url in (("yt", "https://www.youtube.com/@a/videos"), ("vimeo", "https://vimeo.com/channels/b")):
            s.add(Show(
                uuid=f"uuid-{slug}", slug=slug, source_key="ytdlp", title=slug, sharing_url=url,
                membership_level="FREE", type="podcast", episode_identifier="seasonal", author_name="A",
                author_slug="a",
            ))
        s.commit()

    @contextmanager
    def db_session():
        with session_factory() as s:
            yield s

    monkeypatch.setattr(source_router_module, "db_session", db_session)
    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_the_api_key_endpoints(api_client, monkeypatch):
    sessions = [FakeSession(google_error(400, "API_KEY_INVALID")), FakeSession(FakeResponse(200, {"items": []}))]
    monkeypatch.setattr(client_module.requests, "Session", lambda: sessions.pop(0))

    status = api_client.get("/api/sources/ytdlp/api").json()
    assert status["keyHint"] is None
    # Only the YouTube show counts towards the checks.
    assert (status["showCount"], status["rescanUnits"]) == (1, 2)
    assert [share["name"] for share in status["shares"]] == ["checks", "search", "reserve"]

    rejected = api_client.put("/api/sources/ytdlp/api/key", json={"key": "bad"})
    assert rejected.status_code == 422
    assert "does not accept" in rejected.json()["detail"]["message"]
    assert rejected.json()["detail"]["fixUrl"]

    saved = api_client.put("/api/sources/ytdlp/api/key", json={"key": "AIzaGOOD"}).json()
    assert saved["keyHint"] == "OOD"
    assert api_client.get("/api/sources/problems").json() == []
    assert api_client.delete("/api/sources/ytdlp/api/key").json()["keyHint"] is None
    assert api_client.get("/api/sources/dailywire/api").status_code == 404
