from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _episode(*, collection, season, index: int, slug: str, published: datetime, number: int | None = None):
    from backend.db.models.media_item import Episode
    from backend.types.episode_types import EpisodePublishStatus
    from backend.types.media_types import MediaType

    return Episode(
        source_key="dailywire",
        uuid=f"uuid-{slug}",
        type=MediaType.EPISODE.value,
        collection_id=collection.id,
        season_id=season.id,
        index=index,
        episode_identifier=f"ep.S{season.index:02d}E{number or index:02d}",
        dw_episode_number=str(index),
        slug=slug,
        publish_status=EpisodePublishStatus.PUBLISHED_FINAL.value,
        video_url=None,
        audio_url=None,
        sharing_url=f"https://example.test/{slug}",
        went_live_date=None,
        published_date=published,
        scheduled_date=None,
        title=slug,
        description=None,
        duration=60,
        background_image_path=None,
        thumbnail_landscape_path=None,
        thumbnail_portrait_path=None,
        thumbnail_square_path=None,
    )


def test_episode_view_page_is_bounded_and_season_filtered():
    import backend.db.models  # noqa: F401

    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page
    from backend.db import Base
    from backend.db.models import Season, Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        collection = Collection(
            source_key="dailywire",
            uuid="collection-pagination",
            slug="pagination-collection",
            title="Pagination Show",
            description=None,
            sharing_url="https://example.test/collection",
            membership_level="FREE",
            type=CollectionType.SERIES.value,
            episode_identifier=EpisodeIdentifier.SEASONAL.value,
            author_name="Host",
            author_slug="host",
        )
        session.add(collection)
        session.flush()

        season_one = Season(collection_id=collection.id, index=1, slug="season-1", name="Season 1")
        season_two = Season(collection_id=collection.id, index=2, slug="season-2", name="Season 2")
        session.add_all([season_one, season_two])
        session.flush()

        session.add_all([
            _episode(
                collection=collection,
                season=season_one,
                index=1,
                slug="season-1-episode-1",
                published=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            _episode(
                collection=collection,
                season=season_two,
                index=2,
                number=1,
                slug="season-2-episode-1",
                published=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
            _episode(
                collection=collection,
                season=season_two,
                index=3,
                number=2,
                slug="season-2-episode-2",
                published=datetime(2026, 2, 2, tzinfo=timezone.utc),
            ),
        ])
        session.commit()

        newest = get_episode_views_by_collection_page(
            session,
            collection.slug,
            cursor=None,
            limit=2,
        )
        assert [item.slug for item in newest.items] == [
            "season-2-episode-2",
            "season-2-episode-1",
        ]
        assert newest.total == 3
        assert newest.collection_total == 3
        assert newest.has_more is True
        assert newest.next_cursor is not None

        second_season = get_episode_views_by_collection_page(
            session,
            collection.slug,
            cursor=None,
            limit=1,
            season_id=season_two.id,
        )
        assert [item.slug for item in second_season.items] == ["season-2-episode-1"]
        assert second_season.total == 2
        assert second_season.collection_total == 3
        assert second_season.has_more is True

        second_page = get_episode_views_by_collection_page(
            session,
            collection.slug,
            cursor=second_season.next_cursor,
            limit=1,
            season_id=season_two.id,
        )
        assert [item.slug for item in second_page.items] == ["season-2-episode-2"]
        assert second_page.has_more is False

    engine.dispose()



def test_recently_indexed_episode_views_use_index_time_and_limit():
    import backend.db.models  # noqa: F401

    from backend.api.endpoints.episodes.service import get_recently_indexed_episodes
    from backend.db import Base
    from backend.db.models import Season, Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        collection = Collection(
            source_key="dailywire",
            uuid="collection-recent-indexing",
            slug="recent-indexing-collection",
            title="Recent Indexing Show",
            description=None,
            sharing_url="https://example.test/collection",
            membership_level="FREE",
            type=CollectionType.SERIES.value,
            episode_identifier=EpisodeIdentifier.SEASONAL.value,
            author_name="Host",
            author_slug="host",
        )
        session.add(collection)
        session.flush()

        season = Season(collection_id=collection.id, index=1, slug="season-1", name="Season 1")
        session.add(season)
        session.flush()

        oldest = _episode(
            collection=collection,
            season=season,
            index=1,
            slug="indexed-oldest",
            published=datetime(2026, 4, 3, tzinfo=timezone.utc),
        )
        newest = _episode(
            collection=collection,
            season=season,
            index=2,
            slug="indexed-newest",
            published=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        middle = _episode(
            collection=collection,
            season=season,
            index=3,
            slug="indexed-middle",
            published=datetime(2026, 4, 2, tzinfo=timezone.utc),
        )
        oldest.created_at = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
        newest.created_at = datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc)
        middle.created_at = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
        session.add_all([oldest, newest, middle])
        session.commit()

        recent = get_recently_indexed_episodes(session, limit=2)

        assert [item.slug for item in recent] == ["indexed-newest", "indexed-middle"]
        assert [item.collection_title for item in recent] == [
            "Recent Indexing Show",
            "Recent Indexing Show",
        ]
        assert [item.collection_slug for item in recent] == [
            "recent-indexing-collection",
            "recent-indexing-collection",
        ]

    engine.dispose()



def test_episode_cursor_survives_insert_and_delete_before_boundary():
    import backend.db.models  # noqa: F401

    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page
    from backend.db import Base
    from backend.db.models import Season, Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        collection = Collection(
            source_key="dailywire",
            uuid="collection-cursor-mutation",
            slug="cursor-mutation-collection",
            title="Cursor Mutation Show",
            description=None,
            sharing_url="https://example.test/cursor-collection",
            membership_level="FREE",
            type=CollectionType.PODCAST.value,
            episode_identifier=EpisodeIdentifier.NUMBERED.value,
            author_name="Host",
            author_slug="host",
        )
        session.add(collection)
        session.flush()
        season = Season(collection_id=collection.id, index=1, slug="season-1", name="Season 1")
        session.add(season)
        session.flush()

        newest = _episode(
            collection=collection, season=season, index=3, slug="newest",
            published=datetime(2026, 3, 3, tzinfo=timezone.utc),
        )
        boundary = _episode(
            collection=collection, season=season, index=2, slug="boundary",
            published=datetime(2026, 3, 2, tzinfo=timezone.utc),
        )
        oldest = _episode(
            collection=collection, season=season, index=1, slug="oldest",
            published=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        session.add_all([newest, boundary, oldest])
        session.commit()

        first = get_episode_views_by_collection_page(
            session, collection.slug, cursor=None, limit=2,
        )
        assert [item.slug for item in first.items] == ["newest", "boundary"]
        assert first.next_cursor is not None

        # Both changes happen before the keyset boundary and therefore must not
        # move the continuation point.
        session.delete(newest)
        session.add(_episode(
            collection=collection, season=season, index=4, slug="inserted-newest",
            published=datetime(2026, 3, 4, tzinfo=timezone.utc),
        ))
        session.commit()

        second = get_episode_views_by_collection_page(
            session, collection.slug, cursor=first.next_cursor, limit=2,
        )
        assert [item.slug for item in second.items] == ["oldest"]
        assert second.has_more is False

    engine.dispose()



def test_episode_cursor_restarts_when_existing_sort_key_changes():
    import backend.db.models  # noqa: F401

    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page
    from backend.db import Base
    from backend.db.models import Season, Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        collection = Collection(
            source_key="dailywire",
            uuid="collection-cursor-revision",
            slug="cursor-revision-collection",
            title="Cursor Revision Show",
            description=None,
            sharing_url="https://example.test/cursor-revision-collection",
            membership_level="FREE",
            type=CollectionType.PODCAST.value,
            episode_identifier=EpisodeIdentifier.NUMBERED.value,
            author_name="Host",
            author_slug="host",
        )
        session.add(collection)
        session.flush()
        season = Season(collection_id=collection.id, index=1, slug="season-1", name="Season 1")
        session.add(season)
        session.flush()

        first_episode = _episode(
            collection=collection, season=season, index=3, slug="first",
            published=datetime(2026, 5, 3, tzinfo=timezone.utc),
        )
        boundary = _episode(
            collection=collection, season=season, index=2, slug="boundary-revision",
            published=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )
        last_episode = _episode(
            collection=collection, season=season, index=1, slug="last",
            published=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        session.add_all([first_episode, boundary, last_episode])
        session.commit()

        first = get_episode_views_by_collection_page(
            session, collection.slug, cursor=None, limit=2,
        )
        assert first.next_cursor is not None

        # Move the last episode ahead of the old cursor and explicitly advance
        # updated_at to model a metadata correction to an existing row.
        last_episode.published_date = datetime(2026, 5, 4, tzinfo=timezone.utc)
        last_episode.updated_at = last_episode.created_at + timedelta(minutes=1)
        session.commit()

        changed = get_episode_views_by_collection_page(
            session, collection.slug, cursor=first.next_cursor, limit=2,
        )

        assert changed.revision != first.revision
        assert [item.slug for item in changed.items] == [
            "last",
            "first",
        ]

    engine.dispose()
