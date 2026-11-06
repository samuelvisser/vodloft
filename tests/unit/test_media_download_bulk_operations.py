from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_bulk_retry_media_download_operation_attaches_retries_in_one_target():
    from backend.operations.media_downloads import BulkRetryMediaDownloadsOperation

    definition = BulkRetryMediaDownloadsOperation([8, 3, 8])

    assert definition.kind == "media_download.bulk_retry"
    assert definition.resource_type == "media_download"
    assert definition.resource_id is None
    assert definition.title == "Downloads"
    assert definition.context() == {"downloads_requested": 2}
    assert definition.media_download_ids == (8, 3)
    [target] = definition.targets()
    assert target.task_key == "media_download_attach_retries"
    assert target.slot_key == "attach_retries"
    assert target.task_kwargs == {"media_download_ids": [8, 3]}


def test_bulk_cancel_media_download_operation_keeps_per_download_targets():
    from backend.operations.media_downloads import BulkCancelMediaDownloadsOperation

    definition = BulkCancelMediaDownloadsOperation([8, 3, 8])
    targets = definition.targets()

    assert definition.kind == "media_download.bulk_cancel"
    assert definition.resource_type == "media_download"
    assert definition.resource_id is None
    assert definition.context() == {"downloads_requested": 2}
    assert [target.slot_key for target in targets] == ["media_download:8", "media_download:3"]
    assert all(target.task_key == "media_download_bulk_action_worker" for target in targets)
    assert all(target.resource_type == "media_download" for target in targets)
    assert all(target.resource_id is None for target in targets)
    assert [target.task_kwargs for target in targets] == [
        {"media_download_id": 8, "action": "cancel"},
        {"media_download_id": 3, "action": "cancel"},
    ]


def test_bulk_delete_unavailable_media_download_operation_keeps_per_download_targets():
    from backend.operations.media_downloads import (
        BulkDeleteUnavailableMediaDownloadsOperation,
    )

    definition = BulkDeleteUnavailableMediaDownloadsOperation([8, 3, 8])
    targets = definition.targets()

    assert definition.kind == "media_download.bulk_delete_unavailable"
    assert definition.resource_type == "media_download"
    assert definition.resource_id is None
    assert definition.context() == {"downloads_requested": 2}
    assert [target.slot_key for target in targets] == ["media_download:8", "media_download:3"]
    assert all(target.task_key == "media_download_bulk_action_worker" for target in targets)
    assert all(target.resource_type == "media_download" for target in targets)
    assert all(target.resource_id is None for target in targets)
    assert [target.task_kwargs for target in targets] == [
        {"media_download_id": 8, "action": "delete_unavailable"},
        {"media_download_id": 3, "action": "delete_unavailable"},
    ]


@pytest.mark.parametrize(
    ("kind", "operation_type"),
    [
        ("local_media_profile.redownload_media", "local_media_profile"),
        ("movie.redownload_media", "movie"),
    ],
)
def test_scoped_redownload_operations_have_no_coordinator_target(
    kind: str,
    operation_type: str,
):
    if operation_type == "local_media_profile":
        from backend.operations.local_media_profiles import (
            LocalMediaProfileRedownloadOperation,
        )

        resource = SimpleNamespace(id=11, slug="profile", name="Profile")
        definition = LocalMediaProfileRedownloadOperation(
            resource,
            media_download_ids=[4, 5, 4],
        )
    else:
        from backend.operations.movies import MovieRedownloadOperation

        resource = SimpleNamespace(id=12, slug="movie", title="Movie")
        definition = MovieRedownloadOperation(
            resource,
            media_download_ids=[4, 5, 4],
        )

    assert definition.kind == kind
    assert definition.media_download_ids == (4, 5)
    assert definition.targets() == ()
    assert definition.context()["downloads_requested"] == 2


def test_weighted_progress_uses_average_known_size_for_unknown_items():
    from task_manager.tasks.helpers.progress import weighted_progress_percent

    # Unknown-size legacy rows should still count, without being treated as a
    # near-zero one-byte item beside a large known download.
    assert weighted_progress_percent([
        (100, 100),
        (0, None),
    ]) == 50
