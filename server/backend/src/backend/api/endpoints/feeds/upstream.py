"""Passing a Site's own streams on to a feed: the links VODLoft keeps, and the ranges it asks for.

A Site's stream links stop working after a few hours. VODLoft looks them up when an episode is
played, keeps them until shortly before they expire, and asks the Site for big ranges at a time.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

import requests
from fastapi import HTTPException

from backend.utils.keyed_locks import KeyedLocks
from config.network import is_no_internet_error
from sources import MediaStream, Source


logger = logging.getLogger(__name__)

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}
# Ask for big ranges, as yt-dlp does: YouTube slows down a single request for a whole file.
UPSTREAM_CHUNK_BYTES = 10 * 1024 * 1024
READ_BYTES = 64 * 1024
UPSTREAM_TIMEOUT_SECONDS = 30
# The Site now and then refuses a link it has just handed out, and accepts it moments later.
_REFUSED_STATUSES = frozenset({403, 429, 500, 502, 503})
_ASK_AGAIN_AFTER_SECONDS = (1.0, 2.0)
# Look a link up again this long before it expires, so a long episode keeps playing.
_EXPIRY_MARGIN_SECONDS = 30 * 60
# How long a link is kept when its Source does not say when it expires.
_UNKNOWN_EXPIRY_SECONDS = 60 * 60

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _Kept(Generic[V]):
    value: V
    until: float


class LinkCache(Generic[K, V]):
    """Links looked up once per key and kept for as long as ``kept_for`` says, one lookup at a time per key."""

    def __init__(self, kept_for: Callable[[V], float]):
        self._kept_for = kept_for
        self._kept: dict[K, _Kept[V]] = {}
        self._locks: KeyedLocks[K] = KeyedLocks()

    def get(self, key: K, look_up: Callable[[], V], *, fresh: bool = False) -> V:
        """The kept value, or a new lookup when there is none, it ran out, or ``fresh`` asks for one."""
        with self._locks.hold(key):
            kept = self._kept.get(key)
            if kept is not None and not fresh and kept.until > time.time():
                return kept.value
            value = look_up()
            self._kept[key] = _Kept(value, time.time() + self._kept_for(value))
            # Drop what ran out, so the cache does not grow with every episode ever played.
            now = time.time()
            for other in [other for other, item in self._kept.items() if item.until <= now]:
                self._kept.pop(other, None)
            return value


def seconds_until_expiry(expiries: Iterable[float | None]) -> float:
    """How long links are kept: until shortly before the first of them expires."""
    known = [expiry for expiry in expiries if expiry is not None]
    if not known:
        return _UNKNOWN_EXPIRY_SECONDS
    return max(0.0, min(known) - _EXPIRY_MARGIN_SECONDS - time.time())


def look_up_at_site(source: Source, what: str, url: str, look_up: Callable[[], V]) -> V:
    """A lookup at the Site; any failure but a lost connection answers the feed with 502."""
    try:
        return look_up()
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        logger.warning("Could not look up the %s %s of %s: %s", source.name, what, url, exc)
        raise HTTPException(status_code=502, detail=f"{source.name} {what} is currently unavailable") from exc


def _chunk_end(start: int, end: int | None) -> int:
    last = start + UPSTREAM_CHUNK_BYTES - 1
    return last if end is None else min(last, end)


def ranged_get(stream: MediaStream, start: int, end: int | None) -> requests.Response:
    """Up to one chunk of the stream from ``start``, and no further than ``end``."""
    last = _chunk_end(start, end)
    return requests.get(
        stream.url, headers={**stream.headers, "Range": f"bytes={start}-{last}"},
        stream=True, timeout=UPSTREAM_TIMEOUT_SECONDS,
    )


def ask_again(stream: MediaStream, start: int, end: int | None, refused: requests.Response) -> requests.Response:
    """The answer to the same request, asked again a few times while the Site refuses a link that is not old."""
    response = refused
    for wait in _ASK_AGAIN_AFTER_SECONDS:
        if response.status_code not in _REFUSED_STATUSES:
            break
        response.close()
        time.sleep(wait)
        response = ranged_get(stream, start, end)
    return response


def first_range(
        stream: MediaStream, start: int, end: int | None, look_up_again: Callable[[], MediaStream],
) -> tuple[MediaStream, requests.Response]:
    """The answer to the first request of a response, and the stream that gave it.

    A link the Site refuses with 403 expired early or no longer plays to this address, so it is looked
    up once more. A new link the Site still refuses is asked for again, as it tends to work moments later.
    """
    response = ranged_get(stream, start, end)
    if response.status_code == 403:
        response.close()
        stream = look_up_again()
        response = ranged_get(stream, start, end)
    return stream, ask_again(stream, start, end, response)


def total_size(response: requests.Response) -> int | None:
    total = response.headers.get("Content-Range", "").rpartition("/")[2]
    return int(total) if total.isdigit() else None


def stream_bytes(stream: MediaStream, start: int, end: int | None) -> Iterator[bytes]:
    """The stream's bytes from ``start`` to ``end``, asked of the Site a chunk at a time."""
    position = start
    while end is None or position <= end:
        asked = _chunk_end(position, end) - position + 1
        response = ask_again(stream, position, end, ranged_get(stream, position, end))
        try:
            if response.status_code not in (200, 206):
                if response.status_code != 416:
                    logger.warning("A stream stopped with %s at byte %s", response.status_code, position)
                return
            received = 0
            for chunk in response.iter_content(READ_BYTES):
                received += len(chunk)
                yield chunk
            position += received
            # A short answer is the end of the file.
            if response.status_code == 200 or received < asked:
                return
        finally:
            response.close()
