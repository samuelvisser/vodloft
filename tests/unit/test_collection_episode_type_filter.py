"""The collection page's episode type filter: the types a collection has, and pages of only some of them."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Newest first: (identifier, day published).
EPISODES = [
    ("short.1", 1),
    ("ep.1", 2),
    ("short.2", 3),
    ("ep.2", 4),
    ("short.3", 5),
    ("ep.3", 6),
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
            )
            for identifier, day in EPISODES
        ]])
        s.commit()
        yield s


def test_collection_episode_tags_lists_only_the_types_its_episodes_have(session):
    from backend.api.endpoints.collections.service import get_collection_episode_tags

    # The YouTube Source also knows livestreams, but none of this show's episodes is one.
    assert [tag.key for tag in get_collection_episode_tags(session, "show")] == ["ep", "short"]


def test_episode_pages_of_one_type_follow_the_cursor(session):
    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page

    first = get_episode_views_by_collection_page(session, "show", cursor=None, limit=2, episode_types=["short"])
    assert [item.slug for item in first.items] == ["short-3", "short-2"]
    assert first.total == 3
    assert first.collection_total == 6

    second = get_episode_views_by_collection_page(
        session, "show", cursor=first.next_cursor, limit=2, episode_types=["short"],
    )
    assert [item.slug for item in second.items] == ["short-1"]
    assert second.next_cursor is None


def test_a_cursor_only_continues_the_filter_it_was_made_for(session):
    from fastapi import HTTPException

    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page

    first = get_episode_views_by_collection_page(session, "show", cursor=None, limit=2, episode_types=["short"])
    with pytest.raises(HTTPException):
        get_episode_views_by_collection_page(session, "show", cursor=first.next_cursor, limit=2)


def test_no_episode_types_lists_every_episode(session):
    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page

    page = get_episode_views_by_collection_page(session, "show", cursor=None, limit=10)
    assert page.total == 6
    assert len(page.items) == 6
