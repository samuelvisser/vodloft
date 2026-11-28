"""The note on Home that asks for a YouTube API key while YouTube collections or creators are in the Library."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sources.ytdlp.youtube_api import key as key_store

from test_youtube_catalogue import ytdlp_dir  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401


@pytest.fixture
def client(session, ytdlp_dir):
    from backend.api.endpoints.sources import router as sources_router

    app = FastAPI()
    app.include_router(sources_router.router, prefix="/api/v1")
    with TestClient(app) as test_client:
        yield test_client


def _collection(session, url):
    from backend.db.models import Collection

    session.add(Collection(
        uuid=f"uuid-{url}", slug=url.rsplit("/", 1)[-1], source_key="ytdlp", title="A channel", sharing_url=url,
        membership_level="FREE", type="series", episode_identifier="seasonal", author_name="x", author_slug="x",
    ))
    session.commit()


def _notes(client):
    return client.get("/api/v1/sources/api-key-notes").json()


def test_youtube_collections_without_a_key_get_the_note(client, session):
    assert _notes(client) == []
    _collection(session, "https://vimeo.com/channels/staffpicks")
    assert _notes(client) == []

    _collection(session, "https://www.youtube.com/@workshop")

    assert _notes(client) == [{"sourceKey": "ytdlp", "siteName": "YouTube"}]
    key_store.save("AIza-test")
    assert _notes(client) == []


def test_a_youtube_creator_without_collections_gets_the_note_too(client, session):
    from backend.db.models import Creator, CreatorAccount

    creator = Creator(uuid="c", slug="workshop", title="Northwind Workshop")
    creator.accounts.append(CreatorAccount(
        source_key="ytdlp", site_key="youtube", site_ref="UCworkshop", url="https://www.youtube.com/@workshop",
    ))
    session.add(creator)
    session.commit()

    assert _notes(client) == [{"sourceKey": "ytdlp", "siteName": "YouTube"}]


def test_remind_me_later_puts_the_note_off_for_a_week(client, session):
    from backend.db.models import Settings

    _collection(session, "https://www.youtube.com/@workshop")

    assert client.post("/api/v1/sources/api-key-notes", json={"action": "later"}).status_code == 204

    assert _notes(client) == []
    settings = session.query(Settings).one()
    session.refresh(settings)
    assert settings.api_key_note_after > datetime.now(timezone.utc) + timedelta(days=6)
    settings.api_key_note_after = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.commit()
    assert _notes(client) == [{"sourceKey": "ytdlp", "siteName": "YouTube"}]


def test_never_turns_the_note_off(client, session):
    _collection(session, "https://www.youtube.com/@workshop")

    assert client.post("/api/v1/sources/api-key-notes", json={"action": "never"}).status_code == 204

    assert _notes(client) == []
