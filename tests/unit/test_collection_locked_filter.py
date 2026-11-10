"""The collection page's locked episodes filter: pages without the episodes VODLoft has no access to."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Newest first: (identifier, day published, access, refused).
EPISODES = [
    ("ep.1", 1, None, False),
    ("ep.2", 2, "members", False),
    ("ep.3", 3, None, False),
    ("ep.4", 4, "members", True),
    ("ep.5", 5, None, False),
]


@pytest.fixture
def session():
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from backend.db.models import Collection, Episode, Season
    from backend.types.collection_types import CollectionType, EpisodeIdentifier
    from backend.types.media_types import MediaType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        collection = Collection(
            source_key="ytdlp", uuid="c", slug="show", title="Show", description="",
            sharing_url="https://www.youtube.com/@show", membership_level="FREE", type=CollectionType.PODCAST.value,
            episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="Show", author_slug="show",
        )
        season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
        s.add_all([collection, season, *[
            Episode(
                source_key="ytdlp", uuid=identifier, type=MediaType.EPISODE.value, collection=collection,
                season=season, index=day, episode_identifier=identifier, slug=identifier.replace(".", "-"),
                title=identifier, description="", duration=60, publish_status="published_final",
                sharing_url=f"https://www.youtube.com/watch?v={day}",
                published_date=datetime(2026, 1, day, tzinfo=timezone.utc),
                access=access, access_refused_at=datetime(2026, 2, 1, tzinfo=timezone.utc) if refused else None,
            )
            for identifier, day, access, refused in EPISODES
        ]])
        s.commit()
        yield s


def _slugs(page):
    return [episode.slug for episode in page.items]


def test_locked_episodes_are_shown_until_hidden(session):
    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page

    page = get_episode_views_by_collection_page(session, "show", cursor=None, limit=10)
    assert _slugs(page) == ["ep-5", "ep-4", "ep-3", "ep-2", "ep-1"]
    # A members-only episode no download tried yet counts as well as one the Source refused.
    assert page.locked_total == 2


def test_hidden_locked_episodes_follow_the_cursor(session):
    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page

    first = get_episode_views_by_collection_page(session, "show", cursor=None, limit=2, hide_locked=True)
    assert _slugs(first) == ["ep-5", "ep-3"]
    assert (first.total, first.collection_total, first.locked_total) == (3, 5, 2)
    second = get_episode_views_by_collection_page(session, "show", cursor=first.next_cursor, limit=2, hide_locked=True)
    assert _slugs(second) == ["ep-1"]


def test_episodes_the_account_can_watch_are_never_hidden(session, monkeypatch):
    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page
    from sources import Access, Site, get_source

    source = get_source("ytdlp")
    monkeypatch.setattr(type(source), "sites", (Site("youtube", "YouTube", accesses=(Access("members", "Members only", ""),)),))
    monkeypatch.setattr(type(source), "has_access", lambda self, key: True)

    page = get_episode_views_by_collection_page(session, "show", cursor=None, limit=10, hide_locked=True)
    # The refused episode stays locked until a check finds it opened up.
    assert _slugs(page) == ["ep-5", "ep-3", "ep-2", "ep-1"]
    assert page.locked_total == 1


def test_youtube_collections_start_without_locked_episodes():
    from sources import site_of

    assert site_of("youtube").shows_locked is False
    assert site_of("dailywire").shows_locked is True
