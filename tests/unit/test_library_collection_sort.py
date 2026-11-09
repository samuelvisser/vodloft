"""The Library's Collection order: how often each Collection page is opened, and each user's chosen order."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from conftest import use_database
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.security.access import TEMPLATES, Access


@pytest.fixture
def session():
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _collection(session: Session, slug: str, *published: datetime):
    from backend.db.models import Collection, Episode, Season
    from backend.types.collection_types import CollectionType, EpisodeIdentifier
    from backend.types.media_types import MediaType

    collection = Collection(
        source_key="ytdlp", uuid=f"{slug}-uuid", slug=slug, title=slug.title(), description=None,
        sharing_url=f"https://example.test/{slug}", membership_level="FREE", type=CollectionType.SERIES.value,
        episode_identifier=EpisodeIdentifier.DATE_BASED.value, author_name="Host", author_slug="host",
    )
    session.add(collection)
    season = Season(collection=collection, index=1, slug=f"{slug}-season-1", name="Season 1")
    for index, moment in enumerate(published, start=1):
        session.add(Episode(
            source_key="ytdlp", uuid=f"{slug}-{index}", type=MediaType.EPISODE.value, collection=collection, season=season,
            index=index, episode_identifier=f"ep.{index}", slug=f"{slug}-{index}", title=f"Episode {index}",
            description=None, duration=60, publish_status="published_final",
            sharing_url=f"https://example.test/{slug}/{index}", published_date=moment,
        ))
    session.commit()
    return collection


def _user(user_id: int) -> Access:
    template = TEMPLATES["downloader"]
    return Access.for_user(
        user_id=user_id, username=f"user{user_id}", levels=template.levels, source_limits=None,
        members_only=False, delete_files=False, must_change_password=False,
        template_key="downloader", session_version=1,
    )


def test_opening_a_collection_page_counts_without_changing_when_it_was_updated(session):
    from backend.api.endpoints.collections.router import collection_opened
    from backend.api.endpoints.collections.as_view.service import get_collection_views_list

    collection = _collection(session, "often")
    _collection(session, "never")
    updated_at = collection.updated_at

    before = datetime.now(timezone.utc).replace(microsecond=0)
    collection_opened("often")
    collection_opened("often")

    session.expire_all()
    views = {view.slug: view for view in get_collection_views_list(session)}
    assert views["often"].open_count == 2
    assert views["never"].open_count == 0
    assert views["often"].updated_at == updated_at
    assert views["often"].last_opened_at >= before
    assert views["never"].last_opened_at is None
    with pytest.raises(HTTPException) as refused:
        collection_opened("missing")
    assert refused.value.status_code == 404


def test_the_collection_view_says_when_its_oldest_episode_came_out(session):
    from backend.api.endpoints.collections.as_view.service import get_collection_views_list

    _collection(session, "show", datetime(2022, 5, 1, tzinfo=timezone.utc), datetime(2019, 3, 4, tzinfo=timezone.utc))
    _collection(session, "empty")

    views = {view.slug: view.model_dump(by_alias=True) for view in get_collection_views_list(session)}
    assert views["show"]["firstPublishedDate"] == datetime(2019, 3, 4, tzinfo=timezone.utc)
    assert views["empty"]["firstPublishedDate"] is None


def test_each_user_keeps_their_own_library_order(session):
    from backend.api.endpoints.library.router import library_preferences, library_preferences_save
    from backend.api.models.library import LibraryPreferences
    from backend.db.models import User

    session.add_all([User(id=1, username="one", password_hash="x"), User(id=2, username="two", password_hash="x")])
    session.commit()

    assert library_preferences(_user(1)).model_dump() == {
        "collection_sort": "recently_used", "collection_sort_reversed": False, "saved": True,
    }
    library_preferences_save(
        LibraryPreferences.model_validate({"collectionSort": "recently_used", "collectionSortReversed": True}), _user(1),
    )

    assert library_preferences(_user(1)).model_dump()["collection_sort"] == "recently_used"
    assert library_preferences(_user(1)).collection_sort_reversed is True
    assert library_preferences(_user(2)).model_dump()["collection_sort"] == "recently_used"


def test_without_user_accounts_the_browser_keeps_the_library_order(session):
    from backend.api.endpoints.library.router import library_preferences, library_preferences_save
    from backend.api.models.library import LibraryPreferences

    assert library_preferences(Access.full()).saved is False
    with pytest.raises(HTTPException) as refused:
        library_preferences_save(LibraryPreferences.model_validate({"collectionSort": "name"}), Access.full())
    assert refused.value.status_code == 409
