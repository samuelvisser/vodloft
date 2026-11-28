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

    from backend.services.list_previews import saving

    bulk = _bulk([collection.id], feeds={shorts.key: "season"})
    bulk.saving_token = "review-token-1"
    result = run_write_transaction(lambda s: change_collections(s, bulk))
    assert (result.done, result.skipped) == (1, [])
    # The review followed the save by its steps, each done.
    plan = saving("creator", "review-token-1")
    assert [stage["id"] for stage in plan["stages"]] == ["plan", "files", "save", "after"]
    assert {stage["state"] for stage in plan["stages"]} == {"completed"}
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


def test_saving_lists_the_collection_again_only_when_it_takes_something_new(feeds_source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service

    source = feeds_source
    source.videos = [_video("a", 2024), _video("b", 2024, 2)]
    source.lists = [_list("PLtour", "The Tour")]
    source.items = {"PLtour": ("b",)}
    collection = _collection(session, loose="one_season")
    _index(session, collection, source)
    relisted = []
    monkeypatch.setattr(service, "reindex_collection", lambda s, c, by_user: relisted.append(c.slug))
    tour = next(playlist for playlist in seasons_view_of(session).playlists if playlist.ref == "PLtour")

    def lists(enabled):
        return [{"id": tour.id, "enabled": enabled, "as_season": True}]

    assert tour.enabled
    # Switching a list or a feed off only leaves the collection with less of what it has.
    _update(session, playlists=lists(False))
    _update(session, playlists=lists(False), feeds=["videos"])
    assert relisted == []
    # Switching them on again lists what they have now.
    _update(session, playlists=lists(True), feeds=["videos"])
    assert relisted == ["creator"]
    _update(session, feeds=["videos", "shorts"])
    assert relisted == ["creator", "creator"]


def test_listing_a_collection_reports_its_steps(feeds_source, session):
    from progress_plan import PlanTracker
    from task_manager.tasks.helpers.listed_collections import index_listed_collection, listing_steps

    source = feeds_source
    source.videos = [_video("a", 2024)]
    source.lists = [_list("PLtour", "The Tour"), _list("PLbest", "Best Of")]
    source.items = {"PLtour": ("b",), "PLbest": ("a",)}
    collection = _collection(session, loose="one_season")
    _index(session, collection, source)
    source.videos = [*source.videos, _video("b", 2024, 2), _video("c", 2024, 3)]

    snapshots = []
    steps = listing_steps(session, collection)
    session.rollback()
    plan = PlanTracker(steps, sink=snapshots.append)
    index_listed_collection(session, collection_id=collection.id, source=source, plan=plan)

    stages = {stage.id: stage for stage in plan.snapshot().stages}
    assert [stage.id for stage in steps] == ["videos", "lists", "save"]
    assert {stage.state for stage in stages.values()} == {"completed"}
    # The new videos it found, and each list as it is listed.
    assert stages["videos"].done == 2 and stages["videos"].total is None
    assert (stages["lists"].done, stages["lists"].total) == (2, 2)
    assert stages["videos"].label == "Listing the videos of The Creator"


def test_the_library_bulk_edit_puts_what_is_part_of_a_collection_in_a_season_per_year(feeds_source, session):
    from backend.api.endpoints.collections.bulk import change_collections, review_collections, summarize_collections
    from backend.api.models.profile_bulk import BulkSelectionIn
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection

    source = feeds_source
    source.videos = [_video("a", 2024), _video("b", 2025)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)

    summary = summarize_collections(session, BulkSelectionIn(ids=[collection.id]))
    session.rollback()
    assert [(item.value, item.count) for item in summary.loose_videos.values] == [("one_season", 1)]
    assert summary.season_names.plural == "seasons"
    # One season is what it has already, so there is nothing to review.
    assert review_collections(session, _bulk([collection.id], loose_videos="one_season")).collections == []
    session.rollback()
    with pytest.raises(ValueError):
        _bulk([collection.id], loose_videos="everything")

    result = run_write_transaction(lambda s: change_collections(s, _bulk([collection.id], loose_videos="by_year")))
    assert (result.done, result.skipped) == (1, [])
    session.expire_all()
    assert session.get(Collection, collection.id).loose_videos == "by_year"
    assert dict(_filled(session)) == {"2024": ["a"], "2025": ["b"]}


def test_saving_stops_numbering_again_for_an_earlier_change_and_starts_it_again(feeds_source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.api.endpoints.collections.seasons.service import review_seasons, seasons_view
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.episode_identification import queue_renumber
    from backend.services.removed_downloads import remove_left_episodes
    from backend.services.replaced_work import ReplacedWork, stop_replaced_work
    from task_manager.scheduler.db import TaskOperation

    source = feeds_source
    source.videos = [_video("a", 2024), _video("b", 2025)]
    collection = _collection(session, mode="off", loose="one_season")
    _index(session, collection, source)
    monkeypatch.setattr(service, "reindex_collection", lambda s, c, by_user: None)
    earlier = run_write_transaction(lambda s: queue_renumber(s, s.get(Collection, collection.id), renumber=False).id)
    run_write_transaction(lambda s: remove_left_episodes(s, collection.id))
    removing = session.scalar(select(TaskOperation.id).where(TaskOperation.kind == "collection.remove_left_episodes"))

    # The review does not wait for it, and says saving replaces it.
    view = seasons_view(session, "creator")
    body = CollectionSeasonsAPIUpdate(
        seasons=[{"id": season.id, "name": season.name} for season in view.seasons],
        custom_season_order=view.custom_season_order, link_seasons=view.link_seasons,
        loose_videos="one_season", outside_videos=view.outside_videos,
        feed_seasons={"shorts": None},
    )
    review = review_seasons(session, "creator", body)
    session.rollback()
    assert review.busy is None and review.replaces == [earlier, removing]

    # Saving stops it first, and starts what it was still going to do again, the way it was.
    replaced = stop_replaced_work("creator")
    assert replaced == ReplacedWork(renumber=False, remove_left=True)
    session.expire_all()
    assert session.get(TaskOperation, earlier).status == "CANCELED"
    assert session.get(TaskOperation, removing).status == "CANCELED"
    run_write_transaction(lambda s: service.update_seasons(s, "creator", body, replaced=replaced))
    session.expire_all()
    again = session.scalars(select(TaskOperation).where(
        TaskOperation.kind == "collection.renumber", TaskOperation.status == "QUEUED",
    )).all()
    assert len(again) == 1 and again[0].id != earlier and again[0].context["renumber"] is False
    # Letting go of what left starts again too, and looks up what still leaves when it runs.
    (removing_again,) = session.scalars(select(TaskOperation.id).where(
        TaskOperation.kind == "collection.remove_left_episodes", TaskOperation.status == "QUEUED",
    )).all()
    assert removing_again != removing
    # A later save replaces the one this save started, in turn.
    assert stop_replaced_work("creator") == ReplacedWork(renumber=False, remove_left=True)
    session.expire_all()
    assert session.get(TaskOperation, again[0].id).status == "CANCELED"
