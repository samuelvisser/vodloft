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
    assert (review.new_seasons, review.deleted_seasons) == (["Collection"], ["2024", "2025"])
    assert (review.leaving.count, review.deleted_files.count) == (0, 0)
    assert [(name, slugs) for name, _, slugs in _seasons(session)] == [("2024", ["a"]), ("2025", ["b"])]


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

    # Such as a listing of the collection, which may change what moves.
    monkeypatch.setattr(service, "collection_work", lambda s, c: CollectionWork(c.title, downloads=False))
    waiting = _review(session, loose_videos="one_season")
    assert waiting.busy is not None and "still working on" in waiting.busy
    assert waiting.moves is None

    # Downloads go on: the new videos queue behind them.
    monkeypatch.setattr(service, "collection_work", lambda s, c: CollectionWork(c.title, downloads=True))
    ready = _review(session, loose_videos="one_season")
    assert ready.busy is None and [part.count for part in ready.moves.parts] == [2]
