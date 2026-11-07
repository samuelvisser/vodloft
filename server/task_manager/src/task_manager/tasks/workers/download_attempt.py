from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from backend.utils.keyed_locks import KeyedLocks


_ATTEMPTS: KeyedLocks[int] = KeyedLocks()


@contextmanager
def serialize_download_attempt(media_download_id: int, *, progress=None) -> Iterator[None]:
    """Prevent replacement workers from touching one output path concurrently.

    Cancellation/restart ownership is handled generically by TaskRun and
    TaskOperation. This per-artifact lock only protects the filesystem boundary:
    a replacement worker waits until the cooperatively canceled predecessor has
    released the path before it starts writing.
    """
    from downloader import DownloadCanceled

    waiting = False

    def wait() -> None:
        nonlocal waiting
        if progress is not None and callable(progress) and progress():
            raise DownloadCanceled("Canceled while waiting for the previous attempt")
        if not waiting and hasattr(progress, "set_wait_state"):
            progress.set_wait_state("previous_attempt", "Waiting for the previous download to stop")
            waiting = True

    if progress is not None and callable(progress) and progress():
        raise DownloadCanceled("Canceled while waiting for the previous attempt")
    with _ATTEMPTS.hold(media_download_id, while_waiting=wait):
        if waiting:
            progress.set_wait_state(None)
        yield
        if waiting:
            progress.set_wait_state(None)
