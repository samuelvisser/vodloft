"""A video in several seasons: a collection that repeats videos, as a Music collection does, gives a video in several of
its lists that are seasons an episode in each, with files of its own; one that does not keeps it in the first."""
from __future__ import annotations

import pytest

from sqlalchemy import select

from test_link_seasons import (  # noqa: F401
    CreatorSource, _collection, _index, _list, _seasons, links_source, session, source,
)
from test_ytdlp_collections import _video


def _albums(source):
    source.videos = [_video("a", 2024, 1), _video("b", 2024, 2), _video("c", 2024, 3), _video("s", 2024, 4)]
    source.lists = [_list("PLfirst", "First Album"), _list("PLbest", "Best Of")]
    source.items = {"PLfirst": ("a", "b"), "PLbest": ("b", "c")}


def _episodes(session, slug):
    from backend.db.models import Episode

    session.expire_all()
    return session.scalars(select(Episode).where(Episode.source_slug == slug).order_by(Episode.id)).all()


def test_a_music_collection_has_a_track_on_each_album_it_is_on(source, session):
    _albums(source)
    collection = _collection(session, music=True)
    assert collection.repeat_videos == "each_season"

    _index(session, collection, source)

    assert _seasons(session) == [
        ("Singles", 1, ["s"]), ("First Album", 2, ["a", "b"]), ("Best Of", 3, ["b", "c"]),
    ]
    first, best = _episodes(session, "b")
    # Each is an episode of its own: its own slug, number and files.
    assert first.slug != best.slug
    assert (first.season.name, best.season.name) == ("First Album", "Best Of")
    assert first.episode_identifier.startswith("ep.S02E") and best.episode_identifier.startswith("ep.S03E")
    assert best.title == first.title and best.sharing_url == first.sharing_url

    # Indexing again changes nothing.
    _index(session, collection, source)
    assert len(_episodes(session, "b")) == 2


def test_a_series_keeps_a_video_in_the_first_season_only(source, session):
    _albums(source)
    collection = _collection(session)
    assert collection.repeat_videos == "one_season"

    _index(session, collection, source)

    assert _seasons(session) == [
        ("Videos", 1, ["s"]), ("First Album", 2, ["a", "b"]), ("Best Of", 3, ["c"]),
    ]


def test_a_video_that_leaves_one_album_stays_on_the_other(source, session):
    _albums(source)
    collection = _collection(session, music=True)
    _index(session, collection, source)

    source.items["PLbest"] = ("c",)
    _index(session, collection, source)

    assert [episode.season.name for episode in _episodes(session, "b")] == ["First Album"]
    assert ("Best Of", 3, ["c"]) in _seasons(session)


@pytest.mark.parametrize("by_user", [True, False], ids=["the user's change", "found by a check"])
def test_a_downloaded_extra_leaves_with_its_files_when_the_user_made_it_one_and_waits_for_home_otherwise(
    source, session, by_user,
):
    from backend.db.models import Collection
    from backend.db.core import run_write_transaction
    from backend.services.link_seasons import active_lists, extra_episodes, held_back, place_in_link_seasons
    from backend.services.season_state import load_state

    source.videos = [_video("a", 2024, 1), _video("b", 2024, 2)]
    source.lists = [_list("PLfirst", "First Album"), _list("PLbest", "Best Of")]
    source.items = {"PLfirst": ("a", "b"), "PLbest": ("a", "b")}
    collection = _collection(session, music=True)
    _index(session, collection, source)
    # Files for both episodes of a: the one on the album that does not come first is the one it loses. (With files
    # only there, that one would stay instead, and the episode without files would go.)
    first_season = active_lists(load_state(session, session.get(Collection, collection.id)))[0].season_id
    a_first, a_later = sorted(_episodes(session, "a"), key=lambda episode: episode.season_id != first_season)
    _give_files_to(session, a_first.id)
    _give_files_to(session, a_later.id)

    def one_season(w):
        found = w.get(Collection, collection.id)
        found.repeat_videos = "one_season"
        place_in_link_seasons(w, found, by_user=by_user)

    run_write_transaction(one_season)

    # The one without files left at once.
    assert len(_episodes(session, "b")) == 1
    kept, extra = sorted(_episodes(session, "a"), key=lambda episode: episode.id != a_later.id)[::-1]
    assert (kept.season_id, kept.removed_from_source) == (first_season, False)
    assert extra.id == a_later.id
    assert extra_episodes(load_state(session, session.get(Collection, collection.id))) == {extra.id}
    if by_user:
        # The user was told its files go: the task that deletes them removes it, and Home asks nothing.
        assert not extra.removed_from_source and extra.downloads[0].removal_answered_at is not None
        assert not held_back(extra)
    else:
        # Nobody chose this: it stays, marked removed, until Home asked whether to keep it.
        assert extra.removed_from_source and extra.downloads[0].removal_answered_at is None
        assert held_back(extra)


def test_lists_part_of_the_collection_by_year_give_a_video_one_episode(links_source, session):
    from backend.db.models import Collection, CollectionList

    source = links_source
    _albums(source)
    source.outside = {video.slug: video for video in source.videos}
    collection = _collection(session, music=True)
    collection = session.get(Collection, collection.id)
    # A collection of nothing but its lists, which are part of it, with what is part of it in a season per year.
    collection.outside_videos = "only"
    collection.loose_videos = "by_year"
    collection.new_lists = {"list": "contents"}
    session.commit()

    _index(session, collection, source)

    assert not any(link.as_season for link in session.scalars(select(CollectionList)))
    assert len(_episodes(session, "b")) == 1


def test_lists_that_share_a_season_give_a_video_one_episode_there(source, session):
    from backend.db.models import Collection, CollectionList
    from backend.db.core import run_write_transaction
    from backend.services.link_seasons import place_in_link_seasons

    _albums(source)
    collection = _collection(session, music=True)
    _index(session, collection, source)

    def together(w):
        found = w.get(Collection, collection.id)
        first, best = sorted(found.lists, key=lambda link: link.ref != "PLfirst")
        old = best.season_id
        best.season = first.season
        w.flush()
        place_in_link_seasons(w, found, by_user=True, left=frozenset({old, first.season_id}))

    run_write_transaction(together)

    assert [episode.season.name for episode in _episodes(session, "b")] == ["First Album"]
    # Best Of's other track joined it there, and its own season went.
    assert _seasons(session) == [("Singles", 1, ["s"]), ("First Album", 2, ["a", "b", "c"])]
    assert len(set(session.scalars(select(CollectionList.season_id)))) == 1


def test_the_seasons_dialog_sets_it_in_the_collections_words(source, session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.collections import router

    _albums(source)
    collection = _collection(session, music=True)
    _index(session, collection, source)

    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    client = TestClient(app)

    view = client.get(f"/api/collections/{collection.slug}/season-settings").json()
    assert (view["repeatVideos"], view["repeatedCount"], view["words"]["inSeason"]) == ("each_season", 1, "on")

    body = {
        "seasons": [{"id": season["id"], "name": season["name"]} for season in view["seasons"]],
        "customSeasonOrder": False, "linkSeasons": "on", "repeatVideos": "one_season",
    }
    saved = client.put(f"/api/collections/{collection.slug}/season-settings", json=body)
    assert saved.status_code == 200, saved.text
    assert (saved.json()["repeatVideos"], saved.json()["repeatedCount"]) == ("one_season", 0)
    assert [episode.season.name for episode in _episodes(session, "b")] == ["First Album"]


def _give_files_to(session, episode_id):
    """Downloaded files for one episode of a video."""
    from backend.db.models import CollectionLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload
    from conftest import available_artifact

    if session.get(CollectionLocalMediaProfile, 1) is None:
        session.add(CollectionLocalMediaProfile(
            id=1, slug="videos", name="Videos", preferred_format="format_1080p",
            output_template="/downloads/{{ collection_title }}/{{ episode_title }}.ext",
        ))
        session.flush()
    session.add(EpisodeMediaDownload(
        type="episode", media_item_id=episode_id, local_media_profile_id=1, file_path=f"/downloads/{episode_id}.mp4",
        **available_artifact(),
    ))
    session.commit()
