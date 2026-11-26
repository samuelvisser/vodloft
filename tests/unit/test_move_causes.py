"""Why downloads wait for the Move action: the Seasons dialog's changes that put them in another season, which the
Move dialog shows as they were and are now."""
from __future__ import annotations

from test_link_seasons import _collection, _give_files, _index, _seasons, source  # noqa: F401
from test_ytdlp_collections import _video, session  # noqa: F401


def _save(session, **settings):
    """Save the collection's Seasons dialog as it is, but for ``settings``."""
    from backend.api.endpoints.collections.seasons.service import seasons_view, update_seasons
    from backend.api.models.collection_seasons import CollectionSeasonsAPIUpdate
    from backend.db.core import run_write_transaction

    view = seasons_view(session, "creator")
    session.rollback()
    body = CollectionSeasonsAPIUpdate(**{
        "seasons": [{"id": x.id, "name": x.name} for x in view.seasons], "custom_season_order": False,
        "link_seasons": view.link_seasons, "loose_videos": view.loose_videos,
        "outside_videos": view.outside_videos,
        "playlists": [{"id": p.id, "enabled": p.enabled, "as_season": p.as_season, "season_id": p.season_id} for p in view.playlists],
        **settings,
    })
    run_write_transaction(lambda s: update_seasons(s, "creator", body))
    session.expire_all()


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


def test_a_change_that_leaves_downloads_waiting_is_what_the_move_dialog_shows(source, session):
    from backend.db.models import Collection
    from backend.db.core import get_session
    from backend.services.reconcile import ReconcileScope, preview_reconcile

    _waiting(source, session)

    _save(session, loose_videos="one_season")

    assert _causes(session) == [("loose_videos", "by_year", "one_season")]
    # Planned in a session that refuses to write: the preview saves nothing.
    reading = get_session()
    preview = preview_reconcile(reading, ReconcileScope.of_collection(reading.query(Collection).one()))
    reading.close()
    assert [(c.setting, c.before, c.after) for c in preview.causes] == [("loose_videos", "by_year", "one_season")]
    assert [(part.to_season, part.count, part.files_moved) for part in preview.parts] == [("Collection", 2, 2)]
    # The move is still to come and so is what caused it.
    assert _causes(session) == [("loose_videos", "by_year", "one_season")]


def test_changes_before_a_move_add_up_and_one_changed_back_drops_out(source, session):
    _waiting(source, session)

    _save(session, loose_videos="one_season")
    _save(session, repeat_videos="each_season")

    assert _causes(session) == [("loose_videos", "by_year", "one_season"), ("repeat_videos", "one_season", "each_season")]

    # Back to a season per year, nothing waits any more.
    _save(session, loose_videos="by_year", repeat_videos="one_season")

    assert _causes(session) == []


def test_moving_the_downloads_forgets_what_made_them_wait(source, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import Collection
    from backend.services.reconcile import ReconcileScope, reconcile

    _waiting(source, session)
    _save(session, loose_videos="one_season")
    session.commit()

    run_write_transaction(lambda s: reconcile(s, ReconcileScope.of_collection(s.query(Collection).one()), renumber={}))

    assert _causes(session) == []


def test_a_change_that_moves_nothing_downloaded_is_not_kept(source, session):
    source.videos = [_video("a", 2024), _video("b", 2025)]
    collection = _collection(session, loose="by_year")
    _index(session, collection, source)

    _save(session, loose_videos="one_season")

    assert _causes(session) == []


def test_the_move_dialog_waits_while_vodloft_lists_the_collection_again(source, session, monkeypatch):
    from backend.db.core import get_session
    from backend.db.models import Collection
    from backend.services import reconcile
    from backend.services.episode_identification import CollectionWork

    _waiting(source, session)
    _save(session, loose_videos="one_season")

    def preview():
        reading = get_session()
        try:
            return reconcile.preview_reconcile(
                reading, reconcile.ReconcileScope.of_collection(reading.query(Collection).one()),
            )
        finally:
            reading.close()

    # Saving started a listing of the collection, which may change what moves: the dialog waits for it.
    monkeypatch.setattr(reconcile, "collection_work", lambda s, c: CollectionWork(c.title, downloads=False))
    waiting = preview()
    assert waiting.busy is not None and "still working on" in waiting.busy
    assert waiting.parts == []

    monkeypatch.setattr(reconcile, "collection_work", lambda s, c: None)
    ready = preview()
    assert ready.busy is None and [part.count for part in ready.parts] == [2]
