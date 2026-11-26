"""A feed of a channel collection's channel, such as YouTube's Shorts, can be a season of its own, as a list can."""
from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from sources import Names, SectionKind, SectionRole, SectionType
from test_link_seasons import (  # noqa: F401
    PLAYLISTS, _collection, _give_files, _index, _list, _seasons, _update, seasons_view_of, source, session,
)
from test_ytdlp_collections import _video

VIDEOS = SectionType("videos", SectionKind.FEED, Names("video", "videos"))
SHORTS = SectionType("shorts", SectionKind.FEED, Names("short", "shorts"), role=SectionRole.SHORT, episode_tag="short")


@pytest.fixture
def feeds_source(source, monkeypatch):
    from backend.services import sites

    monkeypatch.setattr(type(source), "sites", (replace(source.sites[0], section_types=(VIDEOS, SHORTS, PLAYLISTS)),))
    sites._site_of.cache_clear()
    return source


def _short(slug: str, year: int, month: int = 1):
    return replace(_video(slug, year, month), tag="short")


def _filled(session):
    return [(name, episodes) for name, _number, episodes in _seasons(session) if episodes]


def test_a_feed_can_be_a_season_of_its_own(feeds_source, session):
    from backend.db.models import Collection

    source = feeds_source
    source.videos = [_video("a", 2024), _short("s1", 2024, 3), _short("s2", 2025)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)
    assert _filled(session) == [("Collection", ["a", "s1", "s2"])]

    _update(session, feed_seasons={"shorts": None})
    # The shorts have a season of their own, named after the feed; the channel's other videos stay.
    assert _filled(session) == [("Collection", ["a"]), ("Shorts", ["s1", "s2"])]
    assert [feed.as_season for feed in seasons_view_of(session).feeds] == [False, True]

    # A new short goes straight to the feed's season.
    source.videos = [*source.videos, _short("s3", 2025, 6)]
    _index(session, session.get(Collection, collection.id), source)
    assert _filled(session) == [("Collection", ["a"]), ("Shorts", ["s1", "s2", "s3"])]

    # Part of the collection again, its videos go back, and its season is deleted.
    _update(session, feed_seasons={})
    assert _filled(session) == [("Collection", ["a", "s1", "s2", "s3"])]
    assert session.get(Collection, collection.id).feed_seasons == {}


def test_a_feed_can_share_a_season_with_a_list(feeds_source, session):
    source = feeds_source
    source.videos = [_video("a", 2024), _video("b", 2024, 2), _short("s1", 2024, 3)]
    source.lists = [_list("PLtour", "The Tour")]
    source.items = {"PLtour": ("b",)}
    collection = _collection(session, loose="one_season")
    _index(session, collection, source)
    tour = next(playlist for playlist in seasons_view_of(session).playlists if playlist.ref == "PLtour")

    _update(session, feed_seasons={"shorts": tour.season_id})
    assert ("The Tour", ["b", "s1"]) in _filled(session)
    view = seasons_view_of(session)
    assert next(season for season in view.seasons if season.id == tour.season_id).list_titles == ["Shorts", "The Tour"]

    # On its own again, it gets a season of its own.
    _update(session, feed_seasons={"shorts": None})
    assert {"The Tour": ["b"], "Shorts": ["s1"]}.items() <= dict(_filled(session)).items()


def test_a_video_of_a_feed_that_is_also_in_a_list_goes_to_the_list_unless_the_collection_repeats_it(feeds_source, session):
    source = feeds_source
    source.videos = [_video("a", 2024), _short("s1", 2024, 3), _short("s2", 2024, 4)]
    source.lists = [_list("PLbest", "Best Shorts")]
    source.items = {"PLbest": ("s1",)}
    collection = _collection(session, loose="one_season")
    _index(session, collection, source)

    _update(session, feed_seasons={"shorts": None})
    assert dict(_filled(session)) == {"Videos": ["a"], "Best Shorts": ["s1"], "Shorts": ["s2"]}

    _update(session, feed_seasons={"shorts": None}, repeat_videos="each_season")
    assert dict(_filled(session)) == {"Videos": ["a"], "Best Shorts": ["s1"], "Shorts": ["s1", "s2"]}


def test_a_downloaded_video_moves_to_its_feeds_season_with_the_save(feeds_source, session):
    from backend.services.link_seasons import moved_episodes

    source = feeds_source
    source.videos = [_video("a", 2024), _short("s1", 2024, 3), _short("s2", 2024, 4)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)
    _give_files(session, "s1")

    # The Seasons dialog's review showed the move, so saving moves it, files and all.
    _update(session, feed_seasons={"shorts": None})
    assert dict(_filled(session)) == {"Collection": ["a"], "Shorts": ["s1", "s2"]}
    assert moved_episodes(session, collection) == []


def test_only_a_feed_the_collection_takes_can_be_a_season(feeds_source, session):
    source = feeds_source
    source.videos = [_video("a", 2024), _short("s1", 2024, 3)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)

    _update(session, feeds=["videos"], feed_seasons={"shorts": None})
    from backend.db.models import Collection

    assert session.get(Collection, collection.id).feed_seasons == {}


def _bulk(ids, **changes):
    from backend.api.models.collection import CollectionBulkChangeIn

    return CollectionBulkChangeIn.model_validate({"ids": ids, "changes": changes})


def test_the_library_bulk_edit_makes_a_feed_a_season_after_its_review(feeds_source, session):
    from backend.api.endpoints.collections.bulk import change_collections, review_collections, summarize_collections
    from backend.api.models.profile_bulk import BulkSelectionIn
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.link_seasons import moved_episodes

    source = feeds_source
    source.videos = [_video("a", 2024), _short("s1", 2024, 3), _short("s2", 2024, 4)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)
    _give_files(session, "s1")
    session.commit()

    # Every feed of the chosen collections, by its Site and ref, with what it is in each.
    summary = summarize_collections(session, BulkSelectionIn(ids=[collection.id]))
    session.rollback()
    shorts = next(feed for feed in summary.feeds if feed.names.plural == "shorts")
    assert [(item.value, item.count) for item in shorts.summary.values] == [("part", 1)]
    assert summary.fields["linkSeasons"].offered == 1
    assert summary.list_names is not None

    # The review says what saving does, as the Seasons dialog's review does.
    review = review_collections(session, _bulk([collection.id], feeds={shorts.key: "season"}))
    session.rollback()
    [item] = review.collections
    assert item.skipped is None and item.review.new_seasons == ["Shorts"]
    assert item.review.moves.parts[0].count == 1  # the downloaded short moves to the new season

    # A change that leaves the collection as it is has nothing to review.
    assert review_collections(session, _bulk([collection.id], feeds={shorts.key: "part"})).collections == []
    session.rollback()

    result = run_write_transaction(lambda s: change_collections(s, _bulk([collection.id], feeds={shorts.key: "season"})))
    assert (result.done, result.skipped) == (1, [])
    assert dict(_filled(session)) == {"Collection": ["a"], "Shorts": ["s1", "s2"]}
    assert moved_episodes(session, session.get(Collection, collection.id)) == []

    # Off, the collection no longer takes the feed.
    result = run_write_transaction(lambda s: change_collections(s, _bulk([collection.id], feeds={shorts.key: "off"})))
    assert (result.done, result.skipped) == (1, [])
    session.expire_all()
    assert session.get(Collection, collection.id).feeds == ["videos"]


def test_the_library_bulk_edit_skips_a_collection_its_seasons_change_would_leave_empty(feeds_source, session):
    from backend.api.endpoints.collections.bulk import change_collections, summarize_collections
    from backend.api.models.profile_bulk import BulkSelectionIn
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection

    source = feeds_source
    source.videos = [_video("a", 2024)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)
    keys = [feed.key for feed in summarize_collections(session, BulkSelectionIn(ids=[collection.id])).feeds]
    session.rollback()

    # Every feed off without lists leaves nothing: the collection keeps its settings, the genre too.
    result = run_write_transaction(lambda s: change_collections(
        s, _bulk([collection.id], feeds={key: "off" for key in keys}, genre="Talk"),
    ))
    assert result.done == 0 and len(result.skipped) == 1
    session.expire_all()
    stored = session.get(Collection, collection.id)
    assert (stored.feeds, stored.genre) == (None, None)
