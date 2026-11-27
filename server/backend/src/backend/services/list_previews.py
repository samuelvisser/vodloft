"""Lists the Seasons dialog lists ahead of its review, so it can say exactly what saving moves without saving anything.

When the user switches on a list VODLoft has not listed yet, or adds a link, the dialog asks for it to be listed right
away, in the background, while the user goes on with the dialog. The review waits for a listing that is still running
instead of starting it again, and a list switched off again keeps its listing: what was listed stays known until the
dialog closes, so trying settings out lists nothing twice. Saving takes the listed videos along.

The listings of one open dialog are kept by the token the dialog makes when it opens, and forgotten when it closes or
after an hour without being asked for."""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import Enum

from progress_plan import PlanSnapshot, PlanTracker, StageSpec

from backend.services.source_options import ytdlp_call_options
from sources import get_source

logger = logging.getLogger(__name__)

# Listings kept for a dialog that stops asking, such as a closed browser tab.
_KEPT_FOR = 3600
# Lists looked up at once: each is one slow lookup at its Site.
_AT_ONCE = 4


class ListingState(str, Enum):
    LISTING = "listing"
    LISTED = "listed"
    FAILED = "failed"


@dataclass(frozen=True)
class ListToList:
    """A list the dialog wants listed: one of the collection's, by ``list_id``, or a link the user adds, by the
    ``link`` the user gave."""

    source_key: str
    url: str
    ytdlp_options: tuple[str, ...] = ()
    list_id: int | None = None
    link: str | None = None

    @property
    def key(self) -> tuple[int | None, str | None]:
        return self.list_id, self.link


@dataclass(frozen=True)
class Listing:
    """How far the listing of one list is."""

    list_id: int | None
    link: str | None
    state: ListingState
    slugs: tuple[str, ...] = ()
    """The videos it lists, in its order, once listed."""

    @property
    def count(self) -> int:
        return len(self.slugs)


@dataclass
class _Dialog:
    jobs: dict[tuple[int | None, str | None], Future]
    asked: float
    reviews: int = 0
    """How many reviews the dialog asked for: only the latest is still wanted."""
    kept: dict = field(default_factory=dict)
    """What the dialog's previews and reviews read of the collection, kept for the next one."""
    saving: dict | None = None
    """The plan of the save the dialog runs now, or ran last, as ``{"main_activity", "stages"}``."""


_lock = threading.Lock()
_dialogs: dict[tuple[str, str], _Dialog] = {}
_pool: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=_AT_ONCE, thread_name_prefix="list-preview")
    return _pool


def _list(wanted: ListToList) -> tuple[str, ...]:
    with ytdlp_call_options(wanted.source_key, *wanted.ytdlp_options):
        return tuple(item.slug for item in get_source(wanted.source_key).list_items(wanted.url))


def _forget_old(now: float) -> None:
    for key in [key for key, dialog in _dialogs.items() if now - dialog.asked > _KEPT_FOR]:
        _dialogs.pop(key)


def start_listings(collection_slug: str, token: str, wanted: list[ListToList]) -> None:
    """List each of ``wanted`` in the background, unless this dialog listed it already or is listing it now."""
    now = time.monotonic()
    with _lock:
        _forget_old(now)
        dialog = _dialogs.setdefault((collection_slug, token), _Dialog({}, now))
        dialog.asked = now
        for one in wanted:
            if one.key in dialog.jobs:
                continue
            # It runs in a copy of this context, which tells the Source's pacing whose requests they are.
            dialog.jobs[one.key] = _executor().submit(contextvars.copy_context().run, _list, one)


def listings(collection_slug: str, token: str | None) -> list[Listing]:
    """How far each listing of this dialog is."""
    if token is None:
        return []
    with _lock:
        dialog = _dialogs.get((collection_slug, token))
        if dialog is None:
            return []
        dialog.asked = time.monotonic()
        jobs = dict(dialog.jobs)
    found: list[Listing] = []
    for (list_id, link), job in jobs.items():
        if not job.done():
            found.append(Listing(list_id, link, ListingState.LISTING))
        elif (error := job.exception()) is not None:
            logger.info("Could not list %s for the Seasons dialog: %s", link or f"list {list_id}", error)
            found.append(Listing(list_id, link, ListingState.FAILED))
        else:
            found.append(Listing(list_id, link, ListingState.LISTED, slugs=job.result()))
    return found


def newest_review(collection_slug: str, token: str | None) -> Callable[[], bool]:
    """Start a review for this dialog, which replaces the review it asked for before. Returns whether this review is
    still the dialog's newest, so a review the user's next change replaced can stop early instead of running on."""
    if token is None:
        return lambda: True
    with _lock:
        now = time.monotonic()
        _forget_old(now)
        dialog = _dialogs.setdefault((collection_slug, token), _Dialog({}, now))
        dialog.asked = now
        dialog.reviews += 1
        this = dialog.reviews

    def wanted() -> bool:
        with _lock:
            dialog = _dialogs.get((collection_slug, token))
            return dialog is not None and dialog.reviews == this

    return wanted


def kept_for_dialog(collection_slug: str, token: str | None) -> dict | None:
    """Where the dialog's previews and reviews keep what they read of the collection while it is open, so the next one
    need not read it again. None without a dialog to keep it for."""
    if token is None:
        return None
    with _lock:
        now = time.monotonic()
        _forget_old(now)
        dialog = _dialogs.setdefault((collection_slug, token), _Dialog({}, now))
        dialog.asked = now
        return dialog.kept


def saving_plan(collection_slug: str, token: str | None, steps: list[StageSpec]) -> PlanTracker | None:
    """Follow the dialog's save by a plan of ``steps``, which the dialog asks for while it waits (``saving``). None
    without a dialog to show it to."""
    if token is None:
        return None
    with _lock:
        now = time.monotonic()
        _forget_old(now)
        dialog = _dialogs.setdefault((collection_slug, token), _Dialog({}, now))
        dialog.asked = now
        # A save before this one, such as one that was refused, is over.
        dialog.saving = None

    def keep(snapshot: PlanSnapshot) -> None:
        with _lock:
            dialog.saving = {"main_activity": snapshot.main_activity, "stages": [asdict(stage) for stage in snapshot.stages]}

    return PlanTracker(steps, keep)


def saving(collection_slug: str, token: str) -> dict | None:
    """How far the dialog's save is, by its plan; None before it started one."""
    with _lock:
        dialog = _dialogs.get((collection_slug, token))
        return None if dialog is None else dialog.saving


def forget_listings(collection_slug: str, token: str) -> None:
    """The dialog closed: what it listed is not needed any more. A listing still running finishes unseen."""
    with _lock:
        _dialogs.pop((collection_slug, token), None)


__all__ = [
    "Listing", "ListingState", "ListToList", "forget_listings", "kept_for_dialog", "listings", "newest_review", "saving",
    "saving_plan", "start_listings",
]
