"""Bulk edit in the Library: settings change only where a collection's Site has them, and deletes take every one."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session():
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _collections(s: Session):
    """Two collections on The Daily Wire and two on YouTube."""
    from backend.db.models import Collection
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    collections = [
        Collection(
            source_key="ytdlp" if index >= 2 else "dailywire", site_key="youtube" if index >= 2 else "dailywire",
            uuid=f"collection-{index}", slug=f"show-{index}", title=f"Show {index:02d}", description=None,
            membership_level="FREE",
            sharing_url=f"https://www.youtube.com/@show{index}" if index >= 2 else f"https://www.dailywire.com/show/{index}",
            type=CollectionType.PODCAST.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
            author_name="Host", author_slug="host",
        )
        for index in range(4)
    ]
    s.add_all(collections)
    s.commit()
    return collections


def _changes(ids, **changes):
    from backend.api.models.collection import CollectionBulkChangeIn

    return CollectionBulkChangeIn.model_validate({"ids": ids, "changes": changes})


def test_collection_changes_skip_settings_a_site_does_not_have(session) -> None:
    from backend.api.endpoints.collections.bulk import change_collections, summarize_collections
    from backend.api.models.profile_bulk import BulkSelectionIn

    collections = _collections(session)
    ids = [item.id for item in collections]

    summary = summarize_collections(session, BulkSelectionIn(ids=ids))
    assert summary.count == 4
    assert summary.fields["cookiesMode"].offered == 2  # only the YouTube ones
    assert summary.fields["cookiesMode"].sites_without == ["The Daily Wire"]
    assert {item.value: item.count for item in summary.fields["checkFrequency"].values} == {"default": 4}

    result = change_collections(session, _changes(ids, checkFrequency="less_often", cookiesMode="always", genre=" Talk "))
    session.commit()
    assert (result.done, result.skipped) == (4, [])
    assert [item.check_frequency for item in collections] == ["less_often"] * 4
    assert [item.cookies_mode for item in collections] == ["automatic", "automatic", "always", "always"]
    assert [item.genre for item in collections] == ["Talk"] * 4

    result = change_collections(session, _changes(ids, genre=""))
    session.commit()
    assert result.done == 4
    assert [item.genre for item in collections] == [None] * 4

    only_cookies = change_collections(session, _changes(ids[:1], cookiesMode="never"))
    assert only_cookies.done == 0
    assert [item.name for item in only_cookies.skipped] == ["Show 00"]


def test_collection_changes_leave_an_own_schedule_to_the_edit_page() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _changes([1], checkFrequency="own")
    with pytest.raises(ValidationError):
        _changes([1])


def test_deleting_collections_takes_every_chosen_one(session) -> None:
    from backend.api.endpoints.collections.bulk import delete_collections
    from backend.api.models.profile_bulk import BulkSelectionIn
    from backend.db.models import Collection

    collections = _collections(session)
    result = delete_collections(session, BulkSelectionIn(ids=[collections[0].id, collections[2].id, 999]))
    session.commit()
    assert (result.done, result.skipped) == (2, [])
    assert [item.slug for item in session.query(Collection).order_by(Collection.id)] == ["show-1", "show-3"]


def test_deleting_creators_keeps_their_collections(session) -> None:
    from backend.api.endpoints.creators.bulk import delete_creators
    from backend.api.models.creator import CreatorBulkDeleteIn
    from backend.db.models import Collection, Creator

    collections = _collections(session)
    creator = Creator(uuid="c", slug="ben", title="Ben Shapiro")
    session.add(creator)
    session.flush()
    collections[0].creator = creator
    session.commit()

    result = delete_creators(session, CreatorBulkDeleteIn(ids=[creator.id]))
    session.commit()
    assert (result.done, result.skipped) == (1, [])
    assert session.query(Creator).count() == 0
    assert session.query(Collection).count() == 4
    assert collections[0].creator_id is None


def test_deleting_creators_with_their_collections(session) -> None:
    from backend.api.endpoints.creators.bulk import delete_creators
    from backend.api.models.creator import CreatorBulkDeleteIn
    from backend.db.models import Collection, Creator

    collections = _collections(session)
    creator = Creator(uuid="c", slug="ben", title="Ben Shapiro")
    session.add(creator)
    session.flush()
    collections[0].creator = creator
    collections[1].creator = creator
    session.commit()

    body = CreatorBulkDeleteIn.model_validate({"ids": [creator.id], "deleteCollections": True})
    result = delete_creators(session, body)
    session.commit()
    assert result.done == 1
    assert session.query(Creator).count() == 0
    assert [item.slug for item in session.query(Collection).order_by(Collection.id)] == ["show-2", "show-3"]
