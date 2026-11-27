"""Giving a Site its cookies by pasting the text of a cookies file, which is refused under the pasted text when it is
no cookies file for the Site."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import use_database

NEBULA_COOKIES = "# Netscape HTTP Cookie File\n.nebula.tv\tTRUE\t/\tTRUE\t0\tnebula_auth.apiToken\ttoken\n"
YOUTUBE_COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsigned-in\n"


@pytest.fixture
def client(monkeypatch):
    from backend.api.endpoints.sources import router as router_module
    from backend.db.core import Base
    from backend.db.models import Site
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    with sessionmaker(bind=engine)() as s:
        s.add(Site(key="youtube", name="YouTube", domains=["youtube.com"]))
        s.commit()
    monkeypatch.setattr(router_module, "access_changed", lambda source_key: None)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_pasted_text_that_is_no_cookies_file_lands_under_the_cookies(client):
    refused = client.put("/api/sources/authentication/youtube/cookies", json={"content": "just some text"})
    assert refused.status_code == 422
    assert refused.json()["detail"][0] == {
        "loc": ["body", "content"], "msg": "This is not a cookies.txt file in the Netscape format", "type": "value_error",
    }


def test_pasted_cookies_become_the_sites_cookies_file(client):
    saved = client.put("/api/sources/authentication/youtube/cookies", json={"content": YOUTUBE_COOKIES})
    assert saved.status_code == 200
    assert saved.json()["cookieCount"] == 1


def test_pasted_cookies_of_another_site_are_refused_under_the_cookies(client):
    refused = client.put("/api/sources/authentication/youtube/cookies", json={"content": NEBULA_COOKIES})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "content"]
    assert "youtube.com" in refused.json()["detail"][0]["msg"]
