"""VODLoft's extra index: one number for every extra of a collection, kept once given."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def _collection(session):
    from backend.db.models import Collection, Season

    collection = Collection(
        source_key="dailywire", uuid="show", slug="show", title="The Show", sharing_url="https://example.test",
        membership_level="FREE", type="podcast", episode_identifier="numbered", author_name="Host", author_slug="host",
    )
    session.add(collection)
    session.add_all([
        Season(collection=collection, index=1, slug="season-1", name="Season 1", season_number=1),
        Season(collection=collection, index=2, slug="extras", name="Extras", season_type="extra", season_number=0),
    ])
    session.flush()
    return collection


def _episode(session, collection, index, identifier, season=0):
    from backend.db.models import Episode

    episode = Episode(
        source_key="dailywire", uuid=f"e{index}", type="episode", collection=collection,
        season=collection.seasons[season], index=index, episode_identifier=identifier, slug=f"e{index}",
        title=f"Episode {index}", publish_status="published_final", sharing_url="https://example.test",
    )
    session.add(episode)
    session.flush()
    return episode


def _numbers(session, episodes):
    session.expire_all()
    return [episode.extra_index for episode in episodes]


def test_extras_share_one_count_in_episode_index_order(db_session):
    from backend.services.extra_indexes import number_extras

    collection = _collection(db_session)
    episodes = [
        _episode(db_session, collection, 3, "aux.1"),
        _episode(db_session, collection, 1, "ep.1"),
        _episode(db_session, collection, 2, "ep.2", season=1),
        _episode(db_session, collection, 4, "short.1"),
    ]

    number_extras(db_session, collection.id)

    assert _numbers(db_session, episodes) == [2, None, 1, 3]


def test_an_extra_keeps_its_number_and_a_new_one_takes_the_next(db_session):
    from backend.services.extra_indexes import number_extras

    collection = _collection(db_session)
    trailer = _episode(db_session, collection, 2, "trailer.1")
    aux = _episode(db_session, collection, 3, "aux.1")
    number_extras(db_session, collection.id)

    # An older extra shows up later, and the trailer becomes a normal episode.
    older = _episode(db_session, collection, 1, "aux.2")
    trailer.episode_identifier = "ep.5"
    db_session.flush()
    number_extras(db_session, collection.id)

    assert _numbers(db_session, [trailer, aux, older]) == [None, 2, 3]
