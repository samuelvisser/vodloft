from __future__ import annotations


def test_fetch_new_episodes_result_builds_structured_summary():
    from task_manager.tasks.workers.fetch_new_episodes.service import (
        FetchNewEpisodesResult,
        CollectionEpisodeScanResult,
    )

    result = FetchNewEpisodesResult(collections=(
        CollectionEpisodeScanResult(
            collection_id=1,
            collection_slug="first-collection",
            collection_title="First Collection",
            episodes_found=2,
        ),
        CollectionEpisodeScanResult(
            collection_id=2,
            collection_slug="second-collection",
            collection_title="Second Collection",
            episodes_found=1,
        ),
    ))

    assert result.episodes_found == 3
    assert result.collections_scanned == 2
    assert result.summary() == "Episode scan finished for 2 collections: 3 new episodes found"
    assert result.as_data() == {
        "episodes_found": 3,
        "collections_scanned": 2,
        "collections": [
            {
                "collection_id": 1,
                "collection_slug": "first-collection",
                "collection_title": "First Collection",
                "episodes_found": 2,
            },
            {
                "collection_id": 2,
                "collection_slug": "second-collection",
                "collection_title": "Second Collection",
                "episodes_found": 1,
            },
        ],
    }
