"""Creators looked up a moment ago, so adding one uses what the lookup found instead of asking the Site again.

A lookup can take a minute. The creator lookup and the lookup of the creator behind a collection's link keep what they
found here, under an id they answer with; adding the creator or the collection passes that id back. What is kept is
only a shortcut: an unknown, expired or mismatched id, such as after a restart or in another worker process, looks the
creator up again.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict

from sources import CreatorDetails

_KEEP_SECONDS = 30 * 60
_MOST = 64

_lock = threading.Lock()
_found: OrderedDict[str, tuple[float, tuple, CreatorDetails]] = OrderedDict()


def keep(subject: tuple, details: CreatorDetails) -> str:
    """Keep what a lookup of ``subject``, such as the Source and link it was asked for, found. Returns its id."""
    lookup_id = secrets.token_urlsafe(16)
    with _lock:
        now = time.monotonic()
        for key in [key for key, (expires, _subject, _details) in _found.items() if expires <= now]:
            del _found[key]
        _found[lookup_id] = (now + _KEEP_SECONDS, subject, details)
        while len(_found) > _MOST:
            _found.popitem(last=False)
    return lookup_id


def found(lookup_id: str | None, subject: tuple) -> CreatorDetails | None:
    """What the lookup with this id found, when it was a lookup of ``subject`` and has not expired."""
    if not lookup_id:
        return None
    with _lock:
        kept = _found.get(lookup_id)
    if kept is None:
        return None
    expires, kept_subject, details = kept
    return details if kept_subject == subject and expires > time.monotonic() else None
