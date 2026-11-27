"""Why downloads move: the Seasons dialog's changes that put them in another season, which its review shows as they
were and become, before the save moves them."""
from __future__ import annotations

from test_link_seasons import _collection, _give_files, _index, _seasons, source  # noqa: F401
from test_ytdlp_collections import _video, session  # noqa: F401


def _body(session, **settings):
    """The collection's Seasons dialog as it is, but for ``settings``."""
    from backend.api.endpoints.collections.seasons.service import seasons_view
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate

    view = seasons_view(session, "creator")
    session.rollback()
    return CollectionSeasonsAPIUpdate(**{
        "seasons": [{"id": x.id, "name": x.name} for x in view.seasons], "custom_season_order": False,
        "link_seasons": view.link_seasons, "loose_videos": view.loose_videos,
        "outside_videos": view.outside_videos,
        "playlists": [{"id": p.id, "enabled": p.enabled, "as_season": p.as_season, "season_id": p.season_id} for p in view.playlists],
        **settings,
    })


def _save(session, **settings):
    from backend.api.endpoints.collections.seasons import service
    from backend.db.core import run_write_transaction

    body = _body(session, **settings)
    run_write_transaction(lambda s: service.update_seasons(s, "creator", body))
    session.expire_all()


def _review(session, **settings):
    """The review of saving ``settings``, in a session that refuses to write: it saves nothing."""
    from backend.api.endpoints.collections.seasons.service import review_seasons
    from backend.db.core import get_session

    body = _body(session, **settings)
    reading = get_session()
    try:
        return review_seasons(reading, "creator", body)
    finally:
        reading.close()


def _causes(session):
    from backend.db.models import Collection
    from backend.services.move_causes import move_causes

    session.expire_all()
    return [(c.setting, c.before, c.after) for c in move_causes(session.query(Collection).one())]


def _waiting(source, session):
    """A collection whose videos in no playlist get a season per year, both downloaded."""
    source.videos = [_video("a", 2024), _video("b", 2025)]
    collection = _collection(session, loose="by_year")
    _index(session, collection, source)
    assert [(name, slugs) for name, _, slugs in _seasons(session)] == [("2024", ["a"]), ("2025", ["b"])]
    _give_files(session, "a", "b")
    return collection


def test_the_review_shows_what_the_change_moves_and_saves_nothing(source, session):
    _waiting(source, session)

    review = _review(session, loose_videos="one_season")

    assert review.busy is None
    assert [(c.setting, c.before, c.after) for c in review.causes] == [("loose_videos", "by_year", "one_season")]
    assert [(part.to_season, part.count, part.files_moved) for part in review.moves.parts] == [("Collection", 2, 2)]
    # Each file with the path it has now and the one its Local Media Profile gives it in the new season.
    assert sorted((f.from_path, f.to_path.split("/")[-2:]) for f in review.moves.parts[0].files) == [
        ("/downloads/a.mp4", ["Collection", "Video a.mp4"]), ("/downloads/b.mp4", ["Collection", "Video b.mp4"]),
    ]
    assert (review.new_seasons, review.deleted_seasons) == (["Collection"], ["2024", "2025"])
    assert (review.leaving.count, review.deleted_files.count) == (0, 0)
    # The change moves them: none waited before.
    assert review.already_waiting.count == 0
    assert [(name, slugs) for name, _, slugs in _seasons(session)] == [("2024", ["a"]), ("2025", ["b"])]


def test_the_review_says_which_downloads_already_waited_to_move(source, session):
    """Downloads that waited to move before the dialog opened move along with a save, and the review says so."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection

    _waiting(source, session)

    def one_season(s):
        s.query(Collection).one().loose_videos = "one_season"

    # Changed outside the dialog, so its downloads wait to move.
    run_write_transaction(one_season)
    session.expire_all()

    review = _review(session)
    assert review.causes == []
    assert [(part.count, part.files_moved) for part in review.moves.parts] == [(2, 2)]
    assert (review.already_waiting.count, len(review.already_waiting.examples)) == (2, 2)


def test_saving_moves_the_downloads_the_review_showed(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service

    renumbered = []
    monkeypatch.setattr(service, "queue_renumber", lambda s, collection, renumber: renumbered.append(renumber))
    _waiting(source, session)

    _save(session, loose_videos="one_season", renumber=False)

    assert [(name, slugs) for name, _, slugs in _seasons(session)] == [("Collection", ["a", "b"])]
    # Their files move to their new names; the user chose to keep the episodes' numbers.
    assert renumbered == [False]
    assert _causes(session) == []


def test_a_change_that_moves_nothing_downloaded_moves_no_files(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service

    renumbered = []
    monkeypatch.setattr(service, "queue_renumber", lambda s, collection, renumber: renumbered.append(renumber))
    source.videos = [_video("a", 2024), _video("b", 2025)]
    collection = _collection(session, loose="by_year")
    _index(session, collection, source)

    assert _review(session, loose_videos="one_season").moves.parts == []
    _save(session, loose_videos="one_season")

    assert renumbered == []
    assert _causes(session) == []


def test_the_review_waits_while_vodloft_works_on_the_collection_but_not_for_downloads(source, session, monkeypatch):
    from backend.api.endpoints.collections.seasons import service
    from backend.services.episode_identification import CollectionWork

    _waiting(source, session)
    asked = {}

    def work(s, c, **kwargs):
        asked.update(kwargs)
        return CollectionWork(c.title, downloads=False)

    # Such as deleting the collection's downloads, which changes what moves.
    monkeypatch.setattr(service, "collection_work", work)
    waiting = _review(session, loose_videos="one_season")
    assert waiting.busy is not None and "still working on" in waiting.busy
    assert waiting.moves is None
    # Downloads go on, as the new videos queue behind them; numbering again and listing the collection again are
    # work saving replaces.
    assert asked["downloads"] is False
    assert {"collection.renumber", "collection.sync", "collection.index"} <= set(asked["besides"])

    monkeypatch.setattr(service, "collection_work", lambda s, c, **kwargs: None)
    ready = _review(session, loose_videos="one_season")
    assert ready.busy is None and [part.count for part in ready.moves.parts] == [2]


def test_a_downloaded_episode_stays_over_an_undownloaded_copy(source, session, monkeypatch):
    """The channel season held everything, so a video in a playlist had an episode in both. When the channel season
    stops holding it, the downloaded episode is the one that stays: it moves to the playlist's season, and the copy
    that has nothing downloaded goes."""
    from backend.api.endpoints.collections.seasons import service
    from backend.db.models import Episode
    from sqlalchemy import select
    from test_link_seasons import _list
    from test_repeat_videos import _give_files_to

    monkeypatch.setattr(service, "queue_renumber", lambda s, collection, renumber: None)
    source.videos = [_video("a", 2024), _video("b", 2025)]
    source.lists = [_list("PLone", "One")]
    source.items = {"PLone": ("a",)}
    collection = _collection(session, loose="everything")
    _index(session, collection, source)
    channel = next(name for name, _, slugs in _seasons(session) if slugs == ["a", "b"])
    assert ("One", ["a"]) in [(name, slugs) for name, _, slugs in _seasons(session)]
    downloaded = session.scalars(select(Episode.id).where(
        Episode.source_slug == "a", Episode.season.has(name=channel))).one()
    _give_files_to(session, downloaded)

    review = _review(session, loose_videos="by_year")
    assert review.deleted_files.count == 0
    assert [(part.to_season, part.count) for part in review.moves.parts] == [("One", 1)]

    _save(session, loose_videos="by_year")
    assert ("One", ["a"]) in [(name, slugs) for name, _, slugs in _seasons(session)]
    assert session.scalars(select(Episode.id).where(Episode.source_slug == "a")).all() == [downloaded]



def test_a_download_that_finishes_under_its_old_name_is_renamed_into_its_new_place(source, session, monkeypatch):
    """A download that was running when the save moved its episode finishes under the name the episode had when it
    started; it gets its new name and metadata after, as the files that were there already did."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Episode
    from backend.db.models.media_download import EpisodeMediaDownload
    from task_manager.scheduler.db.TaskOperation import TaskOperation
    from backend.services.download_options import effective_filename_mode
    from backend.services.season_moves import follow_new_place
    from backend.utils.output_template import resolve_episode_output_path
    from task_manager.scheduler import operations

    monkeypatch.setattr(operations, "queue_operation_target_dispatch", lambda *args, **kwargs: None)
    _waiting(source, session)
    download = session.query(EpisodeMediaDownload).join(Episode, Episode.id == EpisodeMediaDownload.media_item_id).filter(
        Episode.source_slug == "a").one()

    assert run_write_transaction(lambda w: follow_new_place(w, w.get(EpisodeMediaDownload, download.id)))
    operation = session.query(TaskOperation).filter(TaskOperation.kind == "collection.rename_files").one()
    assert [(target.task_kwargs["episode_ids"], target.task_kwargs["rewrite_metadata"]) for target in operation.targets] == [
        ([download.media_item_id], True)]

    # Under the name it has now, nothing follows.
    def renamed(w):
        found = w.get(EpisodeMediaDownload, download.id)
        profile = found.local_media_profile
        found.file_path = str(resolve_episode_output_path(
            profile.output_template, episode=found.media, local_media_profile=profile, media_download=found,
            filename_mode=effective_filename_mode(profile), extension="mp4",
        ))
    run_write_transaction(renamed)
    assert not run_write_transaction(lambda w: follow_new_place(w, w.get(EpisodeMediaDownload, download.id)))


def test_files_whose_names_skip_the_season_stay_where_they_are(source, session, monkeypatch):
    """A Local Media Profile whose file names don't name the season keeps its files where they are when their episodes
    change season: nothing waits to move, and the review shows no files moving, only the season change."""
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection, CollectionLocalMediaProfile
    from backend.services import season_moves
    from backend.services.link_seasons import moved_episodes, place_in_link_seasons

    _waiting(source, session)
    session.get(CollectionLocalMediaProfile, 1).output_template = "/downloads/{{ collection_title }}/{{ episode_title }}.ext"
    session.commit()

    def one_season(s):
        s.query(Collection).one().loose_videos = "one_season"

    run_write_transaction(one_season)
    session.expire_all()
    assert moved_episodes(session, session.query(Collection).one()) == []
    session.rollback()

    review = _review(session)
    assert review.moves.parts == [] and review.already_waiting.count == 0
    assert review.deleted_seasons == ["2024", "2025"]

    # The next look at the collection moves them like any other episode, and writes their metadata again.
    rewritten = []
    monkeypatch.setattr(season_moves, "queue_metadata_rewrite", lambda s, collection, ids: rewritten.append(sorted(ids)))
    run_write_transaction(lambda s: place_in_link_seasons(s, s.query(Collection).one()))
    session.expire_all()
    assert [(name, slugs) for name, _, slugs in _seasons(session)] == [("Collection", ["a", "b"])]
    assert len(rewritten) == 1 and len(rewritten[0]) == 2


def test_a_review_the_dialog_replaced_stops(source, session):
    """The dialog asks for a review with each change: a review a newer one replaced stops instead of running on."""
    from backend.services.errors import ServiceError
    from backend.services.list_previews import forget_listings, newest_review
    import pytest

    _waiting(source, session)
    older = newest_review("creator", "dialog")
    newer = newest_review("creator", "dialog")
    try:
        assert (older(), newer()) == (False, True)
        with pytest.raises(ServiceError):
            _review_with(session, older, loose_videos="one_season")
        assert _review_with(session, newer, loose_videos="one_season").moves.parts
    finally:
        forget_listings("creator", "dialog")


def _review_with(session, wanted, **settings):
    from backend.api.endpoints.collections.seasons.service import review_seasons
    from backend.db.core import get_session

    body = _body(session, **settings)
    reading = get_session()
    try:
        return review_seasons(reading, "creator", body, wanted=wanted)
    finally:
        reading.close()


def test_an_open_dialog_keeps_what_its_reviews_read_of_the_files(source, session):
    """The reviews of an open dialog read the downloaded files once, and again only when something they are named
    from changed, such as a new download."""
    from backend.api.endpoints.collections.seasons.service import review_seasons
    from backend.db.core import get_session
    from backend.db.models import Collection

    _waiting(source, session)
    kept: dict = {}

    def review():
        body = _body(session, loose_videos="one_season")
        reading = get_session()
        try:
            return review_seasons(reading, "creator", body, kept=kept)
        finally:
            reading.close()

    assert [part.files_moved for part in review().moves.parts] == [2]
    files = kept["files"]
    assert set(files["downloads"]) and set(files["paths"])
    review()
    assert kept["files"] is files

    source.videos = [*source.videos, _video("c", 2025, 3)]
    _index(session, session.query(Collection).one(), source)
    _give_files(session, "c")
    assert [part.files_moved for part in review().moves.parts] == [3]
    assert kept["files"] is not files
