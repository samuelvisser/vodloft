"""The server checks and runs regexes for Which episodes, and agrees with the regex editor."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.services.regex_check import MAX_PATTERN_LENGTH, check_pattern, compile_pattern, search

CASES = json.loads((Path(__file__).parents[1] / "fixtures" / "regex" / "patterns.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_server_matches_what_the_editor_promises(case):
    """tests/ui/regex_editor.test.cjs checks the same patterns in the browser."""
    result = check_pattern(case["regex"], case["ignoreCase"], case["matches"] + case["misses"])

    assert result.valid
    matched = [sample.matched for sample in result.samples]
    assert matched == [True] * len(case["matches"]) + [False] * len(case["misses"])


def test_a_mistake_says_where_it_is():
    result = check_pattern("Ep (\\d+", False, ["Ep 1"])

    assert not result.valid
    assert result.error == "Missing )"
    assert result.error_position == 7
    assert result.samples == []


def test_a_pasted_inline_flag_becomes_ignore_case():
    result = check_pattern("(?i)trailer", False, ["Official TRAILER"])

    assert (result.pattern, result.ignore_case) == ("trailer", True)
    assert result.samples[0].matched and result.samples[0].spans == ((9, 16),)


def test_long_patterns_are_refused():
    result = check_pattern("a" * (MAX_PATTERN_LENGTH + 1), False, [])

    assert not result.valid and "under" in result.error


def test_a_pattern_that_runs_too_long_counts_as_not_matching(monkeypatch):
    from backend.services import regex_check

    class Slow:
        def search(self, text, timeout):
            assert timeout == regex_check.MATCH_TIMEOUT_SECONDS
            raise TimeoutError

        def finditer(self, text, timeout):
            raise TimeoutError

    monkeypatch.setattr(regex_check, "compile_pattern", lambda pattern, ignore_case: Slow())

    assert search(Slow(), "any title") is None
    sample = regex_check.check_pattern("anything", False, ["any title"]).samples[0]
    assert sample.timed_out and not sample.matched


@pytest.fixture
def client(monkeypatch):
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.api.endpoints.regex import router as regex_router_module
    from backend.db import Base
    from backend.db.models import Collection, Episode, Season

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        collection = Collection(
            uuid="c", slug="c", source_key="ytdlp", title="C", sharing_url="https://www.youtube.com/@c",
            membership_level="FREE", type="podcast", episode_identifier="numbered", author_name="A", author_slug="a",
        )
        session.add(collection)
        session.flush()
        season = Season(collection_id=collection.id, index=1, slug="2026", name="2026", season_number=2026)
        session.add(season)
        session.flush()
        for index, title in enumerate(["Weekly highlights #38", "Why bridges sway", "Highlights: fusion"], start=1):
            session.add(Episode(
                uuid=f"e{index}", type="episode", source_key="ytdlp", collection_id=collection.id, season_id=season.id,
                index=index, episode_identifier=f"ep.{index}", slug=f"e{index}", publish_status="PUBLISHED_FINAL",
                sharing_url="https://example.com", title=title, description=f"Description {index}",
                published_date=datetime(2026, 10, index, tzinfo=timezone.utc),
            ))
        session.commit()
    monkeypatch.setattr(regex_router_module, "get_session", factory)
    app = FastAPI()
    app.include_router(regex_router_module.router, prefix="/api")
    yield TestClient(app)
    engine.dispose()


def test_the_check_tests_your_own_titles_and_the_collection_newest_first(client):
    response = client.post("/api/regex/check", json={
        "pattern": r"\bhighlights\b", "ignoreCase": True, "samples": ["My highlights", "  "], "collectionId": 1,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["valid"]
    assert [(s["text"], s["matched"], s["own"]) for s in body["samples"]] == [
        ("My highlights", True, True),
        ("Highlights: fusion", True, False),
        ("Why bridges sway", False, False),
        ("Weekly highlights #38", True, False),
    ]
    assert body["samples"][1]["spans"] == [[0, 10]]
    assert (body["collectionMatches"], body["collectionTotal"]) == (2, 3)


def test_the_check_can_test_descriptions(client):
    body = client.post("/api/regex/check", json={
        "pattern": "Description 2", "samples": [], "collectionId": 1, "field": "description",
    }).json()

    assert body["collectionMatches"] == 1


def test_an_unknown_collection_is_not_found(client):
    assert client.post("/api/regex/check", json={"pattern": "x", "collectionId": 99}).status_code == 404
