from __future__ import annotations

import threading

import pytest


def test_a_key_takes_turns_and_its_lock_goes_once_no_one_uses_it():
    from backend.utils.keyed_locks import KeyedLocks

    locks: KeyedLocks[str] = KeyedLocks()
    held = threading.Event()
    release = threading.Event()

    def first() -> None:
        with locks.hold("a"):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=first)
    thread.start()
    held.wait(5)
    waited: list[int] = []

    def wait() -> None:
        waited.append(1)
        release.set()

    with locks.hold("a", while_waiting=wait, poll_seconds=0.01):
        assert waited
    thread.join(5)
    assert locks._locks == {}


def test_waiting_stops_when_the_caller_gives_up():
    from backend.utils.keyed_locks import KeyedLocks

    locks: KeyedLocks[int] = KeyedLocks()

    def give_up() -> None:
        raise TimeoutError

    with locks.hold(1):
        with pytest.raises(TimeoutError):
            with locks.hold(1, while_waiting=give_up, poll_seconds=0.01):
                pass
    assert locks._locks == {}
