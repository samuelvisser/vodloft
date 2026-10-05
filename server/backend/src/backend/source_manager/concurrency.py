"""Shared upstream limits across acquisition, discovery and synchronization."""
from contextlib import contextmanager
import threading

_lock = threading.Lock()
_sources = {}
_domains = {}
_connections = {}


def slots(source_id, domain_id, connection_id):
    with _lock:
        return (
            _sources.setdefault(source_id, threading.BoundedSemaphore(3)),
            _domains.setdefault(domain_id, threading.BoundedSemaphore(2)),
            _connections.setdefault((source_id, connection_id), threading.BoundedSemaphore(1)),
        )


def try_acquire(source_id, domain_id, connection_id):
    acquired = []
    for slot in slots(source_id, domain_id, connection_id):
        if not slot.acquire(blocking=False):
            for held in reversed(acquired):
                held.release()
            return None
        acquired.append(slot)
    return acquired


def release(acquired):
    for slot in reversed(acquired):
        slot.release()


@contextmanager
def upstream_slots(source_id, domain_id, connection_id):
    acquired = []
    try:
        for slot in slots(source_id, domain_id, connection_id):
            slot.acquire()
            acquired.append(slot)
        yield
    finally:
        release(acquired)
