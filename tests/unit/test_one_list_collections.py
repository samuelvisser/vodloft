"""A collection of one list, such as a playlist or an album: the list is its one season, numbered in the list's
order, and it takes no other lists."""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

from sqlalchemy import select

from sources import ItemRef, VideoDetails
from test_creators import PLAYLIST, ROOT, _add, _collection, client, forget_lookups, tube  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401

MIGRATION = "backend.db.background_migrations.versions.ec22487a3a11_channel_and_list_collections"


def _video(slug: str, year: int) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://tube.example/watch?v={slug}", title=f"Video {slug}", duration=60.0,
        published_at=datetime(year, 1, 1, tzinfo=timezone.utc),
    )


def _cabin(session):
    """The Cabin playlist as a collection, with three videos of different years in the playlist's order."""
    from backend.db.core import run_write_transaction
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    cabin_id = _add("cabin", PLAYLIST)
    found = [_video("b", 2025), _video("a", 2019), _video("c", 2022)]
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=cabin_id, found=found))
    return _collection(session, "cabin")


def test_a_collection_of_one_list_is_one_season_numbered_in_the_lists_order(tube, session):
    from backend.db.models import Episode

    cabin = _cabin(session)

    assert cabin.kind == "list"
    assert len(cabin.seasons) == 1
    episodes = session.scalars(select(Episode).where(Episode.collection_id == cabin.id).order_by(Episode.index)).all()
    assert [episode.source_slug for episode in episodes] == ["b", "a", "c"]


def test_a_collection_of_one_list_takes_no_other_lists(client, session):
    _add("cabin", PLAYLIST)

    response = client.post("/api/collections/cabin/creator", json={})

    assert response.status_code == 422
    assert _collection(session, "cabin").lists == []


class _Progress:
    def set(self, percent, message, meta=None):
        pass


def _migrate():
    from backend.db.background_migrations.registry import get_background_migration_history
    from backend.db.background_migrations.runner import BackgroundMigrationContext

    module = importlib.import_module(MIGRATION)
    context = BackgroundMigrationContext(
        migration=next(m for m in get_background_migration_history() if m.revision == module.revision),
        migration_index=1, migration_total=1, progress=_Progress(),
    )
    asyncio.run(module.migrate(context))


def test_the_migration_tells_a_playlist_from_a_channel_and_takes_the_playlist_out_of_its_creator(client, session, monkeypatch):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection

    _add("workshop", ROOT)
    _add("cabin", PLAYLIST)
    client.post("/api/collections/workshop/creator", json={})
    creator_id = _collection(session, "workshop").creator_id

    def as_before(w):
        for collection in w.scalars(select(Collection)):
            collection.kind = "channel"
            collection.creator_id = creator_id
    run_write_transaction(as_before)

    _migrate()

    workshop, cabin = _collection(session, "workshop"), _collection(session, "cabin")
    assert (workshop.kind, workshop.creator_id) == ("channel", creator_id)
    assert (cabin.kind, cabin.creator_id) == ("list", None)


def test_the_migration_puts_the_year_seasons_of_a_playlist_into_one_season_in_the_lists_order(tube, session, monkeypatch):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, Episode, Season

    cabin_id = _cabin(session).id

    def as_before(w):
        collection = w.get(Collection, cabin_id)
        album = collection.seasons[0]
        years = {}
        for episode in w.scalars(select(Episode).where(Episode.collection_id == cabin_id)):
            year = episode.published_date.year
            years[year] = Season(collection_id=cabin_id, index=year, slug=str(year), name=str(year), season_number=year)
            w.add(years[year])
            w.flush()
            episode.season_id = years[year].id
        w.flush()
        w.delete(album)
        collection.episode_identifier = "date_based"
    run_write_transaction(as_before)
    monkeypatch.setattr(tube, "list_items", lambda url: [
        ItemRef(slug, f"https://tube.example/watch?v={slug}") for slug in ("c", "b", "a")
    ], raising=False)

    _migrate()

    cabin = _collection(session, "cabin")
    assert len(cabin.seasons) == 1 and cabin.seasons[0].season_number != 2019
    episodes = session.scalars(select(Episode).where(Episode.collection_id == cabin_id).order_by(Episode.index)).all()
    assert [episode.source_slug for episode in episodes] == ["c", "b", "a"]
    assert {episode.season_id for episode in episodes} == {cabin.seasons[0].id}
    assert (cabin.episode_identifier, cabin.episode_order) == ("date_based", "oldest_first")


def test_the_migration_leaves_a_channel_collections_settings_and_gives_a_list_its_season(tube, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection

    _add("workshop", ROOT)
    _cabin(session)

    def as_in_0_9_1(w):
        for collection in w.scalars(select(Collection)):
            collection.kind = "channel"
            collection.link_seasons = "off"
            collection.channel_season = "unlisted"
            for season in collection.seasons:
                season.origin = "vodloft"
    run_write_transaction(as_in_0_9_1)

    _migrate()

    workshop, cabin = _collection(session, "workshop"), _collection(session, "cabin")
    assert (workshop.kind, workshop.link_seasons, workshop.channel_season) == ("channel", "off", "unlisted")
    assert cabin.kind == "list"
    assert [season.origin for season in cabin.seasons] == ["list"]


def test_an_album_collection_by_album_is_numbered_in_the_albums_order(tube, session):
    """A Music collection of one album, By album as the Add Collection wizard suggests: the album is its one season,
    its tracks numbered in the album's order."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, Episode
    from backend.services.collections import add_collection
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    def add(s):
        collection = Collection(
            uuid="uuid-album", slug="album", source_key="tube", title="Album", sharing_url=PLAYLIST,
            membership_level="FREE", type="music", episode_identifier="seasonal", author_name="", author_slug="",
        )
        add_collection(s, collection)
        s.flush()
        return collection.id

    album_id = run_write_transaction(add)
    found = [_video("b", 2025), _video("a", 2019), _video("c", 2022)]
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=album_id, found=found))

    album = _collection(session, "album")
    assert len(album.seasons) == 1
    episodes = session.scalars(select(Episode).where(Episode.collection_id == album.id).order_by(Episode.index)).all()
    assert [(episode.source_slug, episode.episode_identifier) for episode in episodes] == [
        ("b", "ep.S01E01"), ("a", "ep.S01E02"), ("c", "ep.S01E03"),
    ]
