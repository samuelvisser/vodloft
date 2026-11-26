"""A video the Source already refused when it looked it up is locked right away, as a refused download locks it,
so VODLoft offers no download of it."""
from __future__ import annotations

from dataclasses import replace

from sources import VideoDetails

from test_quick_check import _collection, _video, session  # noqa: F401


def test_a_listed_video_the_source_refused_is_added_locked(session):
    from backend.db.models import Episode
    from backend.services.media_access import media_locked
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    collection = _collection(session, "UC1")
    refused = replace(_video("v1", 1), access="members", access_refused=True)
    # Only marked as members-only, such as by YouTube's listing: a download finds out whether VODLoft may have it.
    marked = replace(_video("v2", 2), access="members")
    add_listed_episodes(session, collection_id=collection.id, found=[refused, marked])
    session.commit()

    episodes = {e.source_slug: e for e in session.query(Episode).filter(Episode.collection_id == collection.id)}
    assert episodes["v1"].access_refused_at is not None
    assert episodes["v1"].access_check_at is not None
    assert media_locked(episodes["v1"])
    assert episodes["v2"].access == "members"
    assert not media_locked(episodes["v2"])


def test_a_refresh_the_source_refused_locks_the_item(session):
    from backend.db.models import Episode
    from backend.services.media_access import media_locked
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes
    from task_manager.tasks.helpers.refreshed_metadata import apply_refreshed_details

    collection = _collection(session, "UC1")
    add_listed_episodes(session, collection_id=collection.id, found=[_video("v1", 1)])
    session.commit()
    episode = session.query(Episode).filter(Episode.collection_id == collection.id).one()

    assert apply_refreshed_details(episode, VideoDetails(slug="v1", url="u", title="v1", access="members", access_refused=True))
    assert media_locked(episode)
