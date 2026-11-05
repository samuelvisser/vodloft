from __future__ import annotations

import asyncio
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest

from task_manager.tasks.helpers import custom_index_readiness

pytestmark = pytest.mark.enable_socket


def _hold_pair_lock_in_process(
    lock_root: str,
    collection_id: int,
    local_media_profile_id: int,
    attempting,
    acquired,
    release,
) -> None:
    from task_manager.tasks.helpers import custom_index_readiness as lock_helper

    lock_helper.get_settings = lambda: SimpleNamespace(
        download_settings=SimpleNamespace(lock_root=lock_root)
    )

    async def hold_lock() -> None:
        attempting.set()
        async with lock_helper.custom_index_pair_lock(collection_id, local_media_profile_id):
            acquired.set()
            await asyncio.to_thread(release.wait)

    asyncio.run(hold_lock())


def _use_lock_root(monkeypatch, lock_root: Path) -> None:
    monkeypatch.setattr(
        custom_index_readiness,
        "get_settings",
        lambda: SimpleNamespace(download_settings=SimpleNamespace(lock_root=lock_root)),
    )


def test_shared_locks_allow_concurrent_readers_and_exclude_writer(monkeypatch, tmp_path):
    _use_lock_root(monkeypatch, tmp_path)

    async def exercise_lock_modes() -> None:
        readers_ready = asyncio.Event()
        release_readers = asyncio.Event()
        writer_acquired = asyncio.Event()
        active_readers = 0

        async def reader() -> None:
            nonlocal active_readers
            async with custom_index_readiness.custom_index_pair_lock(1, 2, shared=True):
                active_readers += 1
                if active_readers == 2:
                    readers_ready.set()
                await release_readers.wait()
                active_readers -= 1

        async def writer() -> None:
            async with custom_index_readiness.custom_index_pair_lock(1, 2):
                writer_acquired.set()

        reader_tasks = [asyncio.create_task(reader()) for _ in range(2)]
        writer_task = None
        try:
            await asyncio.wait_for(readers_ready.wait(), timeout=5)
            writer_task = asyncio.create_task(writer())
            await asyncio.sleep(0.2)
            assert not writer_acquired.is_set()
        finally:
            release_readers.set()
            await asyncio.gather(*reader_tasks)
        assert writer_task is not None
        await asyncio.wait_for(writer_task, timeout=5)
        assert writer_acquired.is_set()

    asyncio.run(exercise_lock_modes())


def test_distinct_pairs_can_be_locked_concurrently(monkeypatch, tmp_path):
    _use_lock_root(monkeypatch, tmp_path)

    async def exercise_distinct_pairs() -> None:
        both_acquired = asyncio.Event()
        release = asyncio.Event()
        acquired = 0

        async def hold_pair(collection_id: int) -> None:
            nonlocal acquired
            async with custom_index_readiness.custom_index_pair_lock(collection_id, 2):
                acquired += 1
                if acquired == 2:
                    both_acquired.set()
                await release.wait()

        tasks = [asyncio.create_task(hold_pair(collection_id)) for collection_id in (1, 3)]
        try:
            await asyncio.wait_for(both_acquired.wait(), timeout=5)
        finally:
            release.set()
            await asyncio.gather(*tasks)

    asyncio.run(exercise_distinct_pairs())


def test_cancelled_waiter_does_not_prevent_later_acquisition(monkeypatch, tmp_path):
    _use_lock_root(monkeypatch, tmp_path)

    async def exercise_cancellation() -> None:
        async with custom_index_readiness.custom_index_pair_lock(1, 2):
            async def acquire_after_current_holder() -> None:
                async with custom_index_readiness.custom_index_pair_lock(1, 2):
                    pytest.fail("The waiter acquired the lock before its current holder released it")

            waiter = asyncio.create_task(acquire_after_current_holder())
            await asyncio.sleep(0.2)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter

        async with asyncio.timeout(5):
            async with custom_index_readiness.custom_index_pair_lock(1, 2):
                pass

    asyncio.run(exercise_cancellation())


def test_releasing_lock_allows_another_process_to_acquire(monkeypatch, tmp_path):
    _use_lock_root(monkeypatch, tmp_path)
    context = multiprocessing.get_context("spawn")
    attempting = context.Event()
    acquired = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_pair_lock_in_process,
        args=(str(tmp_path), 1, 2, attempting, acquired, release),
    )

    async def exercise_process_lock() -> None:
        async with custom_index_readiness.custom_index_pair_lock(1, 2):
            process.start()
            assert attempting.wait(timeout=10)
            assert not acquired.wait(timeout=0.25)

        assert acquired.wait(timeout=10)

    try:
        asyncio.run(exercise_process_lock())
    finally:
        release.set()
        if process.pid is not None:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert process.exitcode == 0