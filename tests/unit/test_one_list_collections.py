"""A collection made from one of a creator's lists, such as a playlist or an album: the list is its one season, numbered
in the list's order, until the creator gives it more lists, which it then holds as seasons, and only those."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from sources import VideoDetails
from test_creators import ROOT, client, tube  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401


def _video(slug: str, year: int) -> VideoDetails:
    return VideoDetails(
        slug=slug, url=f"https://tube.example/watch?v={slug}", title=f"Video {slug}", duration=60.0,
        published_at=datetime(year, 1, 1, tzinfo=timezone.utc),
    )


def _tools(client, session):
    """Tool Reviews as a collection of its own, with three videos of different years in the playlist's order."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    response = client.post("/api/creators", json={"sourceKey": "tube", "url": ROOT, "sections": [
        {"ref": "videos", "target": "main"}, {"ref": "PLtools", "target": "own"},
    ]})
    assert response.status_code == 201, response.text
    tools_id = session.scalar(select(Collection.id).where(Collection.slug == "PLtools"))
    found = [_video("b", 2025), _video("a", 2019), _video("c", 2022)]
    run_write_transaction(lambda w: add_listed_episodes(w, collection_id=tools_id, found=found))
    session.expire_all()
    return session.get(Collection, tools_id)


def test_a_collection_of_one_list_is_one_season_numbered_in_the_lists_order(client, session):
    from backend.api.endpoints.episodes.service import get_episode_views_by_collection_page
    from backend.db.models import Episode

    tools = _tools(client, session)

    assert (tools.episode_identifier, tools.episode_order) == ("numbered", "oldest_first")
    assert [season.name for season in tools.seasons] == ["Tool Reviews"]
    episodes = session.scalars(select(Episode).where(Episode.collection_id == tools.id).order_by(Episode.index)).all()
    assert [(episode.source_slug, episode.episode_identifier) for episode in episodes] == [
        ("b", "ep.1"), ("a", "ep.2"), ("c", "ep.3"),
    ]
    page = get_episode_views_by_collection_page(session, tools.slug, cursor=None, limit=2)
    following = get_episode_views_by_collection_page(session, tools.slug, cursor=page.next_cursor, limit=2)
    assert [item.slug for item in [*page.items, *following.items]] == ["b", "a", "c"]


def test_a_collection_of_one_list_that_is_given_another_takes_both_as_seasons_and_only_them(client, session):
    from backend.api.endpoints.collections.seasons.service import seasons_view
    from backend.db.models import Collection, Episode

    tools = _tools(client, session)
    tools_id = tools.id

    added = client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [
        {"ref": "PLcabin", "target": "main", "collectionSlug": "PLtools"},
    ]})

    assert added.status_code == 200, added.text
    session.expire_all()
    tools = session.get(Collection, tools_id)
    # Its own list is a season too, and it numbers by season now.
    assert {(link.ref, link.enabled, link.as_season) for link in tools.lists} == {
        ("PLtools", True, True), ("PLcabin", True, True),
    }
    assert tools.episode_identifier == "seasonal"
    own = next(link for link in tools.lists if link.ref == "PLtools")
    assert own.season.name == "Tool Reviews"
    episodes = session.scalars(select(Episode).where(Episode.collection_id == tools_id).order_by(Episode.index)).all()
    number = own.season.season_number
    assert [episode.episode_identifier for episode in episodes] == [f"ep.S{number:02d}E{n:02d}" for n in (1, 2, 3)]
    # The creator's other lists are not the collection's to take.
    view = seasons_view(session, tools.slug)
    assert sorted(playlist.title for playlist in view.playlists) == ["Building the Cabin", "Tool Reviews"]


MIGRATION = "backend.db.background_migrations.versions.b64eb88d81ac_one_list_collections_one_season"


def test_the_migration_makes_an_older_collection_of_one_list_with_another_list_hold_both_as_seasons(client, session):
    """Before, the collection kept its own list out of its seasons, with its videos in seasons per year, and knew every
    list of the creator."""
    import importlib

    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CollectionList, Episode, Season

    tools = _tools(client, session)
    tools_id = tools.id
    assert client.post("/api/creators/workshop/accounts/1/sections", json={"sections": [
        {"ref": "PLcabin", "target": "main", "collectionSlug": "PLtools"},
    ]}).status_code == 200

    def as_before(w):
        collection = w.get(Collection, tools_id)
        own = next(link for link in collection.lists if link.ref == "PLtools")
        album = own.season
        own.as_season, own.season = False, None
        years = {}
        for episode in w.scalars(select(Episode).where(Episode.collection_id == tools_id)):
            year = episode.published_date.year
            if year not in years:
                years[year] = Season(collection_id=tools_id, index=year, slug=str(year), name=str(year), season_number=year)
                w.add(years[year])
                w.flush()
            episode.season_id = years[year].id
        w.flush()
        w.delete(album)
        collection.lists.append(CollectionList(
            ref="PLmembers", url="https://tube.example/playlist?list=PLmembers", title="Members' Cuts", enabled=False,
            status="known", as_season=True, site_position=9,
        ))

    run_write_transaction(as_before)

    importlib.import_module(MIGRATION)._settle_gatherer(tools_id)

    session.expire_all()
    tools = session.get(Collection, tools_id)
    assert {link.ref for link in tools.lists} == {"PLtools", "PLcabin"}
    own = next(link for link in tools.lists if link.ref == "PLtools")
    assert own.as_season and own.season.name == "Tool Reviews"
    assert {season.name for season in tools.seasons} == {"Tool Reviews"}
    assert {episode.season_id for episode in session.scalars(select(Episode).where(Episode.collection_id == tools_id))} == {own.season_id}
