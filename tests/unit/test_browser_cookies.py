"""Giving a Site its cookies from a browser: pasting them, and VODLoft's browser extension, which asks for the Site of
a page and sends the browser's cookies for it."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import use_database

YOUTUBE_COOKIES = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsigned-in\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tPREF\tf6=40000000\n"
    "www.google.com\tFALSE\t/\tTRUE\t0\tNID\tnot-for-youtube\n"
)
NEBULA_COOKIES = "# Netscape HTTP Cookie File\n.nebula.tv\tTRUE\t/\tTRUE\t0\tnebula_auth.apiToken\ttoken\n"


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


def test_the_site_of_a_page_names_the_domains_whose_cookies_to_send(client):
    found = client.get("/api/sources/authentication/site-of-page", params={"url": "https://www.youtube.com/watch?v=abc"})
    assert found.status_code == 200
    assert found.json()["key"] == "youtube" and found.json()["name"] == "YouTube"
    assert "youtube.com" in found.json()["domains"]
    assert found.json()["takesCookies"] is True


def test_a_page_of_no_site_is_refused_under_the_link(client):
    refused = client.get("/api/sources/authentication/site-of-page", params={"url": "about:blank"})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "url"]


def test_cookies_from_a_browser_become_the_sites_cookies_file(client):
    sent = client.post("/api/sources/authentication/browser-cookies", json={
        "url": "https://www.youtube.com/watch?v=abc", "content": YOUTUBE_COOKIES,
    })
    assert sent.status_code == 200
    # Only the Site's own cookies are kept.
    assert sent.json()["key"] == "youtube" and sent.json()["cookieCount"] == 2


def test_cookies_from_a_browser_add_a_site_vodloft_did_not_know(client):
    sent = client.post("/api/sources/authentication/browser-cookies", json={
        "url": "https://nebula.tv/videos/a-video", "content": NEBULA_COOKIES,
    })
    assert sent.status_code == 200
    assert sent.json()["name"] == "Nebula" and sent.json()["cookieCount"] == 1
    listed = {site["key"] for site in client.get("/api/sources/authentication").json()}
    assert "nebula" in listed


def test_cookies_of_another_site_are_refused_under_the_cookies(client):
    refused = client.post("/api/sources/authentication/browser-cookies", json={
        "url": "https://www.youtube.com/watch?v=abc", "content": NEBULA_COOKIES,
    })
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "content"]
    assert "youtube.com" in refused.json()["detail"][0]["msg"]


def test_pasted_text_that_is_no_cookies_file_lands_under_the_cookies(client):
    refused = client.put("/api/sources/authentication/youtube/cookies", json={"content": "just some text"})
    assert refused.status_code == 422
    assert refused.json()["detail"][0] == {
        "loc": ["body", "content"], "msg": "This is not a cookies.txt file in the Netscape format", "type": "value_error",
    }
