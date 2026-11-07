from types import SimpleNamespace


def test_collection_added_payload_contains_canonical_collection_identity():
    from backend.services.collections import CollectionAdded

    collection = SimpleNamespace(
        id=42,
        slug="test-collection",
        title="Test Show",
    )

    assert CollectionAdded(collection) == {
        "resource_id": 42,
        "id": 42,
        "slug": "test-collection",
        "title": "Test Show",
        "initial_index": True,
    }
