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

    # Joining the creator of the channel that made it only groups it: it takes none of the channel's lists.
    response = client.post("/api/collections/cabin/creator", json={})

    assert response.status_code == 200, response.text
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


def _save_seasons(session, slug: str, loose: str):
    """Save the Seasons dialog of the collection as it is, with its videos in one season or a season per year."""
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = seasons_view(session, slug)
    session.rollback()
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": x.id, "name": x.name} for x in view.seasons], custom_season_order=False,
        link_seasons="off", loose_videos=loose,
    )
    return run_write_transaction(lambda s: update_seasons(s, slug, body))


def test_a_collection_of_one_list_can_put_its_videos_in_a_season_per_year_and_back(tube, session):
    cabin_id = _cabin(session).id
    session.rollback()

    view = _save_seasons(session, "cabin", "by_year")

    assert view.made_from_list and not view.link_seasons_offered
    assert sorted(season.name for season in view.seasons) == ["2019", "2022", "2025"]
    session.rollback()
    assert _seasons_of(session, cabin_id) == {"a": "2019", "b": "2025", "c": "2022"}

    view = _save_seasons(session, "cabin", "one_season")

    assert len(view.seasons) == 1 and view.seasons[0].year is None
    session.rollback()
    assert set(_seasons_of(session, cabin_id).values()) == {view.seasons[0].slug}


def _seasons_of(session, collection_id: int) -> dict[str, str]:
    """The slug of each video's season, by the video."""
    from backend.db.models import Episode

    return {
        episode.source_slug: episode.season.slug
        for episode in session.scalars(select(Episode).where(Episode.collection_id == collection_id))
    }


def test_a_new_video_of_a_collection_of_one_list_by_year_goes_to_its_years_season(tube, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    cabin_id = _cabin(session).id
    session.rollback()
    _save_seasons(session, "cabin", "by_year")

    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=cabin_id, found=[_video("d", 2021)]))

    session.rollback()
    new = session.scalar(select(Episode).where(Episode.collection_id == cabin_id, Episode.source_slug == "d"))
    assert new.season.slug == "2021"


def test_the_migration_sets_a_list_that_keeps_its_year_seasons_to_a_season_per_year(tube, session, monkeypatch):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, Episode, Season

    cabin_id = _cabin(session).id

    def as_before(w):
        collection = w.get(Collection, cabin_id)
        collection.kind = "channel"
        album = collection.seasons[0]
        for episode in w.scalars(select(Episode).where(Episode.collection_id == cabin_id)):
            year = episode.published_date.year
            season = Season(collection_id=cabin_id, index=year, slug=str(year), name=str(year), season_number=year)
            w.add(season)
            w.flush()
            episode.season_id = season.id
        w.flush()
        w.delete(album)
    run_write_transaction(as_before)

    def unreadable(url):
        raise RuntimeError("The list could not be read")
    monkeypatch.setattr(tube, "list_items", unreadable, raising=False)

    _migrate()

    cabin = _collection(session, "cabin")
    assert cabin.kind == "list" and cabin.loose_videos == "by_year"
    assert sorted(season.slug for season in cabin.seasons) == ["2019", "2022", "2025"]
