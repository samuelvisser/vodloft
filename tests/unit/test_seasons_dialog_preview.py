"""The Seasons dialog's preview, for every change the dialog can make: the seasons it shows are the seasons the
collection has once the change is saved, its lists are listed again, and the user moved what the Move dialog offers."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from test_link_seasons import _collection, _give_files, _index, _list, _seasons, _update, links_source, source  # noqa: F401
from test_ytdlp_collections import _video, session  # noqa: F401


def _body(session, change):
    """The dialog as it opens, with ``change`` made to it."""
    from backend.api.endpoints.collections.seasons.service import seasons_view
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate

    view = seasons_view(session, "creator")
    session.rollback()
    data = dict(
        seasons=[{"id": x.id, "name": x.name} for x in view.seasons], custom_season_order=view.custom_season_order,
        link_seasons=view.link_seasons, loose_videos=view.loose_videos, list_layout=view.list_layout,
        repeat_videos=view.repeat_videos, outside_videos=view.outside_videos,
        playlists=[
            {"id": p.id, "enabled": p.enabled, "season_id": p.season_id, "as_season": p.as_season} for p in view.playlists
        ],
    )
    change(view, data)
    return CollectionSeasonsAPIUpdate(**data)


def _playlist(view, title):
    return next(p for p in view.playlists if p.title == title)


def _set_playlist(data, view, title, **fields):
    playlist_id = _playlist(view, title).id
    for playlist in data["playlists"]:
        if playlist["id"] == playlist_id:
            playlist.update(fields)


def _preview_matches_saving(session, source, collection, change, monkeypatch, *, listed=True):
    """Preview ``change``, check it saved nothing, then save it, list the collection again and move what waits for
    the Move dialog: the preview showed the seasons that leaves."""
    from backend.api.endpoints.collections.seasons import service
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.link_seasons import moved_episodes
    from backend.services.reconcile import ReconcileScope, reconcile
    from task_manager.tasks.helpers.listed_collections import index_listed_collection
    from task_manager.tasks.workers.remove_left_episodes.service import run_remove_left_episodes

    monkeypatch.setattr(service, "queue_season_folder_moves", lambda s, c, ids: None)
    before = _seasons(session)
    body = _body(session, change)
    preview = run_write_transaction(lambda s: service.preview_seasons(s, "creator", body))
    assert _seasons(session) == before

    run_write_transaction(lambda s: service.update_seasons(s, "creator", body))
    session.expire_all()
    if listed:
        # The listing the save asks for is the user's change, as the Seasons dialog's save queues it.
        index_listed_collection(session, collection_id=collection.id, source=source, by_user=True)
        session.expire_all()
    # The task the save queued deletes the files of the downloaded videos that left, and then the videos.
    session.rollback()
    run_remove_left_episodes(session, collection_id=collection.id)
    session.expire_all()
    if moved_episodes(session, session.get(Collection, collection.id)):
        session.rollback()
        run_write_transaction(lambda w: reconcile(w, ReconcileScope.of_collection(w.get(Collection, collection.id)), renumber={}))
    assert [(x.name, x.season_number, x.episode_count) for x in preview.seasons] == [
        (name, number, len(episodes)) for name, number, episodes in _seasons(session)
    ]


def _season_id(view, name):
    return next(x.id for x in view.seasons if x.name == name)


CHANNEL_CHANGES = {
    "one season for videos in no list": lambda v, d: d.update(loose_videos="one_season"),
    "a season per year for videos in no list": lambda v, d: d.update(loose_videos="by_year"),
    "lists laid out by year": lambda v, d: d.update(list_layout="by_year"),
    "a list switched off": lambda v, d: (d.update(link_seasons="selected"), _set_playlist(d, v, "One", enabled=False)),
    "lists off": lambda v, d: d.update(link_seasons="off"),
    "lists off and one season": lambda v, d: d.update(link_seasons="off", loose_videos="one_season"),
    "a list joins another's season": lambda v, d: _set_playlist(d, v, "Two", season_id=_playlist(v, "One").season_id),
    "a list no season of its own": lambda v, d: _set_playlist(d, v, "One", as_season=False),
    "a list's season deleted": lambda v, d: d.update(removed_seasons=[_season_id(v, "One")]),
    "the season of videos in no list deleted": lambda v, d: d.update(removed_seasons=[x.id for x in v.seasons if x.loose]),
    "a video in each of its seasons": lambda v, d: d.update(repeat_videos="each_season"),
    "the channel season holds everything": lambda v, d: d.update(channel_season="everything"),
    "the user's own order": lambda v, d: (d.update(custom_season_order=True), d["seasons"].reverse()),
}


@pytest.mark.parametrize("loose", ["one_season", "by_year"])
@pytest.mark.parametrize("files", [False, True], ids=["no files", "downloaded"])
@pytest.mark.parametrize("change", list(CHANNEL_CHANGES))
def test_a_channel_collection(source, session, change, files, loose, monkeypatch):
    source.videos = [
        _video("a", 2023), _video("b", 2023, 6), _video("c", 2024), _video("d", 2024, 6), _video("e", 2025), _video("f", 2025, 6),
    ]
    source.lists = [_list("PLone", "One"), _list("PLtwo", "Two")]
    source.items = {"PLone": ("a", "c", "f"), "PLtwo": ("c", "d")}
    collection = _collection(session, mode="selected", loose=loose)
    _index(session, collection, source)
    if files:
        _give_files(session, "a", "b", "c", "e")

    _preview_matches_saving(session, source, collection, CHANNEL_CHANGES[change], monkeypatch)


@pytest.mark.parametrize("files", [False, True], ids=["no files", "downloaded"])
def test_a_video_back_in_one_season_only(source, session, files, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.db.core import run_write_transaction

    source.videos = [_video("a", 2023), _video("c", 2024), _video("d", 2024, 6)]
    source.lists = [_list("PLone", "One"), _list("PLtwo", "Two")]
    source.items = {"PLone": ("a", "c"), "PLtwo": ("c", "d")}
    collection = _collection(session, mode="selected")
    _index(session, collection, source)
    body = _body(session, lambda v, d: d.update(repeat_videos="each_season"))
    run_write_transaction(lambda s: service.update_seasons(s, "creator", body))
    session.expire_all()
    assert _seasons(session) == [("One", 1, ["a", "c"]), ("Two", 2, ["c", "d"])]
    if files:
        _give_files(session, "c")

    _preview_matches_saving(
        session, source, collection, lambda v, d: d.update(repeat_videos="one_season"), monkeypatch, listed=False,
    )


@pytest.mark.parametrize("to", ["one_season", "by_year"])
@pytest.mark.parametrize("files", [False, True], ids=["no files", "downloaded"])
def test_a_collection_of_one_playlist(source, session, to, files, monkeypatch):
    source.videos = [_video("a", 2020), _video("b", 2021), _video("c", 2021, 6), _video("d", 2022), _video("e", 2026)]
    collection = _collection(
        session, mode="off", loose="by_year" if to == "one_season" else "one_season",
        url="https://seasons.example/playlist?list=PLall",
    )
    collection.kind = "list"
    session.commit()
    _index(session, collection, source)
    if files:
        _give_files(session, "a", "b", "c", "d")

    _preview_matches_saving(session, source, collection, lambda v, d: d.update(loose_videos=to), monkeypatch, listed=False)


LINKS_CHANGES = {
    "holds only what its lists have": lambda v, d: d.update(outside_videos="only"),
    "adds the videos of its lists": lambda v, d: d.update(outside_videos="add"),
    "a link the user added removed": lambda v, d: d.update(outside_videos="only", removed_links=[_playlist(v, "Mine").id]),
    "a list switched off": lambda v, d: (
        d.update(outside_videos="only", link_seasons="selected"), _set_playlist(d, v, "One", enabled=False),
    ),
}


@pytest.mark.parametrize("files", [False, True], ids=["no files", "downloaded"])
@pytest.mark.parametrize("change", list(LINKS_CHANGES))
def test_a_collection_with_links_the_user_adds(links_source, session, change, files, monkeypatch):
    from backend.api.endpoints.collections.seasons.service import AddedLink
    from backend.db.models import Collection, Episode

    source = links_source
    source.videos = [_video("a", 2024), _video("b", 2025), _video("c", 2025, 6)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",), "PLmine": ("b", "x")}
    source.outside = {"a": _video("a", 2024), "b": _video("b", 2025), "x": _video("x", 2023)}
    collection = _collection(session, mode="all")
    _index(session, collection, source)
    if change in ("a link the user added removed", "a list switched off"):
        mine = AddedLink("PLmine", "https://seasons.example/playlist?list=PLmine", "Mine", None, "seasons")
        _update(session, added=[mine], outside_videos="only")
        _index(session, session.get(Collection, collection.id), source)
    if files:
        _give_files(session, *session.scalars(select(Episode.source_slug).where(Episode.source_slug.in_(("a", "b", "c")))))

    _preview_matches_saving(session, source, collection, LINKS_CHANGES[change], monkeypatch)
