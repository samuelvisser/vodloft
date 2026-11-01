from __future__ import annotations

import asyncio
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def scope_helpers():
    return import_module("task_manager.tasks.workers.fetch_new_episodes._helpers")


@pytest.fixture
def collections():
    return [
        SimpleNamespace(id=1, slug="first-collection", title="First Show", source_key="dailywire"),
        SimpleNamespace(id=17, slug="second-collection", title="Second Show", source_key="dailywire"),
    ]


@pytest.mark.parametrize("collection_count", [0, 2])
def test_global_scope_selects_all_collections(scope_helpers, collections, collection_count):
    collection_id = None
    session = Mock(spec=Session)
    session.get.return_value = None
    expected = collections[:collection_count]
    session.scalars.return_value.all.return_value = expected

    assert scope_helpers.get_collections(
        session, collection_id=collection_id, collection_slug=None,
    ) == expected
    session.scalars.assert_called_once()
    session.scalar.assert_not_called()
    session.get.assert_not_called()


@pytest.mark.parametrize("collection_id", [0, 1, 17, 999, -1])
def test_explicit_id_never_falls_back_to_all_collections(scope_helpers, collections, collection_id):
    session = Mock(spec=Session)
    collection = next((item for item in collections if item.id == collection_id), None)
    session.get.return_value = collection

    assert scope_helpers.get_collections(
        session, collection_id=collection_id, collection_slug=None,
    ) == ([collection] if collection is not None else [])
    session.get.assert_called_once_with(scope_helpers.Collection, collection_id)
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()


@pytest.mark.parametrize("collection_id", [None, 0, 17])
@pytest.mark.parametrize("collection_slug", ["first-collection", "missing-collection"])
def test_slug_scope_takes_precedence_without_global_fallback(
    scope_helpers, collections, collection_id, collection_slug,
):
    session = Mock(spec=Session)
    collection = next((item for item in collections if item.slug == collection_slug), None)
    session.scalar.return_value = collection

    assert scope_helpers.get_collections(
        session, collection_id=collection_id, collection_slug=collection_slug,
    ) == ([collection] if collection is not None else [])
    session.scalar.assert_called_once()
    statement = session.scalar.call_args.args[0]
    assert statement.whereclause.compare(scope_helpers.Collection.slug == collection_slug)
    session.get.assert_not_called()
    session.scalars.assert_not_called()


def test_global_scan_processes_every_collection(monkeypatch, collections):
    collection_id = None
    service = import_module("task_manager.tasks.workers.fetch_new_episodes.service")
    session = Mock(spec=Session)
    session.scalars.return_value.all.return_value = collections
    by_id = {collection.id: collection for collection in collections}
    session.get.side_effect = lambda _model, identity: by_id.get(identity)

    auth = Mock()
    auth.get_token.return_value = None
    monkeypatch.setattr(service, "DeviceAuthClient", Mock(return_value=auth))
    monkeypatch.setattr(service, "MiddlewareClient", Mock())
    fetch_collection = AsyncMock(side_effect=[2, 1])
    monkeypatch.setattr(service, "_fetch_collection", fetch_collection)

    # Exercise the real selector and service with the global scope;
    # remote episode retrieval is intentionally isolated from this scope test.
    result = asyncio.run(service.run_fetch_new_episodes(session, collection_id=collection_id))

    assert result.collections_scanned == 2
    assert result.episodes_found == 3
    assert [collection.collection_id for collection in result.collections] == [1, 17]
    assert fetch_collection.await_count == 2
    assert [call.kwargs["collection"].id for call in fetch_collection.await_args_list] == [1, 17]
    assert result.as_data()["collections"] == [
        {"collection_id": 1, "collection_slug": "first-collection", "collection_title": "First Show", "episodes_found": 2},
        {"collection_id": 17, "collection_slug": "second-collection", "collection_title": "Second Show", "episodes_found": 1},
    ]
