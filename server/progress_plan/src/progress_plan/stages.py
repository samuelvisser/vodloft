from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, replace
from math import isfinite
from threading import RLock
from time import time
from typing import Callable, Iterable, Literal, TypeVar

StageState = Literal["pending", "running", "waiting", "completed", "skipped", "failed", "canceled"]
DONE: tuple[StageState, ...] = ("completed", "skipped")
"""The states of a step whose work is all done."""
_ENDED: tuple[StageState, ...] = ("completed", "skipped", "failed", "canceled")


@dataclass(frozen=True)
class WaitInterval:
    """A time a step waited, for a reason such as a Site that asked to slow down, and until when, when known."""
    reason: str
    started_at: float
    finished_at: float | None = None
    until: float | None = None


@dataclass(frozen=True, kw_only=True)
class StageSpec:
    """One step of a plan, decided before the work starts."""
    id: str
    code: str
    """What the step does, such as ``download_media``, by which a UI names it when it has no ``label``."""
    weight: float = 1.0
    """The step's share of the work, against the weights of the other steps."""
    label: str | None = None
    """What the step does in words, such as "Numbering the episodes"."""
    unit: str | None = None
    """What the step counts as it goes, in the plural, such as "episodes", for a step that says how many it did."""
    depends_on: tuple[str, ...] = ()
    deadline_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.weight) or self.weight < 0:
            raise ValueError("Stage work weights must be finite and nonnegative")
        if self.deadline_seconds is not None and (not isfinite(self.deadline_seconds) or self.deadline_seconds <= 0):
            raise ValueError("Stage deadlines must be finite and positive")


@dataclass(frozen=True, kw_only=True)
class Stage:
    """Where one step of a plan is."""
    id: str
    code: str
    weight: float
    label: str | None = None
    state: StageState = "pending"
    started_at: float | None = None
    finished_at: float | None = None
    fraction: float | None = None
    """How far the running step is, from 0 to 1, or None while it cannot measure itself."""
    unit: str | None = None
    """What the step counts, in the plural, when it counts: then ``done`` of ``total`` are done."""
    done: int | None = None
    total: int | None = None
    wait: WaitInterval | None = None
    waits: tuple[WaitInterval, ...] = ()
    last_activity_at: float | None = None
    deadline_at: float | None = None


S = TypeVar("S", bound=Stage)


def started(stage: S, now: float, *, deadline_seconds: float | None = None) -> S:
    """The step, running from ``now``."""
    return replace(
        stage, state="running", started_at=stage.started_at or now, last_activity_at=now,
        deadline_at=now + deadline_seconds if deadline_seconds else None,
    )


def finished(stage: S, state: StageState, now: float) -> S:
    """The step, ended in ``state``: a done step is whole, a stopped one keeps how far it got."""
    waits = stage.waits
    if stage.wait is not None:
        waits += (replace(stage.wait, finished_at=now),)
    return replace(
        stage, state=state, fraction=1.0 if state in DONE else stage.fraction, finished_at=now, last_activity_at=now,
        wait=None, waits=waits,
    )


def waiting(stage: S, reason: str | None, until: float | None, now: float) -> S:
    """The step, waiting for ``reason`` from ``now``, or running again when there is none. Its deadline moves on by
    the time it waited."""
    previous = stage.wait
    waits = stage.waits
    if previous is not None:
        waits += (replace(previous, finished_at=now),)
    current = WaitInterval(reason, now, until=until) if reason else None
    return replace(
        stage, wait=current, waits=waits, state="waiting" if current else "running", last_activity_at=now,
        deadline_at=(stage.deadline_at + now - previous.started_at) if previous and stage.deadline_at else stage.deadline_at,
    )


def measured(stage: S, fraction: float | None, now: float, **facts) -> S:
    """The step, ``fraction`` of the way, or unmeasured with None, with any facts of its own, such as its bytes."""
    return replace(stage, fraction=fraction, last_activity_at=now, **facts)


def completion_fraction(stages: Iterable[Stage]) -> float:
    """How much of the work is done, from 0 to 1, by the steps' weights.

    Weights are units of work, not a prediction of time. A step counts whole once it is done, as far as its fraction
    while it runs, and not at all while it cannot measure itself."""
    total = done = 0.0
    for stage in stages:
        weight = max(0.0, float(stage.weight))
        total += weight
        if stage.state in DONE:
            fraction = 1.0
        elif stage.state in ("running", "waiting") and stage.fraction is not None:
            fraction = max(0.0, min(1.0, float(stage.fraction)))
        else:
            fraction = 0.0
        done += weight * fraction
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, done / total))


@dataclass(frozen=True)
class PlanSnapshot:
    """A plan as it is now: its steps, and the one the work is on."""
    stages: tuple[Stage, ...]
    main_activity: str | None = None

    @property
    def main(self) -> Stage | None:
        return next((stage for stage in self.stages if stage.id == self.main_activity), None)

    @property
    def fraction(self) -> float:
        return completion_fraction(self.stages)

    @property
    def measurable(self) -> bool:
        """Whether the step the work is on can say how far it is, so the whole plan can."""
        main = self.main
        return main is None or main.state not in ("running", "waiting") or main.fraction is not None


class PlanTracker:
    """Follows a plan of steps through a piece of work, and hands each change to ``sink``.

    Work that knows all its steps in advance gives them at once; work that finds more, such as one per file profile,
    adds them as it finds them. Safe to use from several threads."""

    def __init__(self, steps: Iterable[StageSpec] = (), sink: Callable[[PlanSnapshot], None] | None = None) -> None:
        self.sink = sink
        self._lock = RLock()
        self._main = None
        self._stages = {}
        for spec in steps:
            self._add(spec)

    def _add(self, spec: StageSpec) -> None:
        if spec.id in self._stages:
            raise ValueError(f"The plan already has a stage '{spec.id}'")
        self._stages[spec.id] = Stage(
            id=spec.id, code=spec.code, weight=spec.weight, label=spec.label, unit=spec.unit,
        )

    def add(self, *steps: StageSpec) -> None:
        with self._lock:
            for spec in steps:
                self._add(spec)
        self._emit()

    def start(self, step: str, *, label: str | None = None) -> None:
        with self._lock:
            stage = self._stages[step]
            if stage.state != "pending":
                raise ValueError(f"Stage '{step}' has already started")
            stage = started(stage, time())
            self._stages[step] = replace(stage, label=label) if label else stage
            self._main = step
        self._emit()

    def progress(self, step: str, fraction: float | None, *, done: int | None = None, total: int | None = None) -> None:
        """How far the running step is, from 0 to 1, or None when it cannot tell, and for a step that counts, how many
        of how many it did."""
        counted = {"done": done, "total": total} if total is not None else {}
        with self._lock:
            self._stages[step] = measured(
                self._stages[step], None if fraction is None else max(0.0, min(1.0, fraction)), time(), **counted,
            )
        self._emit()

    @contextmanager
    def running(self, step: str) -> Iterator[None]:
        """Runs the step for as long as the block does: done when it ends, failed when it raises."""
        self.start(step)
        try:
            yield
        except BaseException:
            self.fail(step)
            raise
        self.complete(step)

    def follow(self, step: str, future: Future, *, failed: StageState = "failed") -> Future:
        """Runs the step while ``future`` does, for work started at once beside other work: done when it finishes, and
        ``failed``, such as skipped for something that may well not be there, when it raises. Returns a future of the
        same outcome that is only done once the step has ended, so work waiting for it never runs ahead of its plan."""
        self.start(step)
        followed: Future = Future()

        def finish(inner: Future) -> None:
            error = None if inner.cancelled() else inner.exception()
            self._end(step, failed if inner.cancelled() or error is not None else "completed")
            if inner.cancelled():
                followed.cancel()
            elif error is not None:
                followed.set_exception(error)
            else:
                followed.set_result(inner.result())

        future.add_done_callback(finish)
        return followed

    def complete(self, step: str) -> None:
        self._end(step, "completed")

    def skip(self, step: str) -> None:
        self._end(step, "skipped")

    def fail(self, step: str) -> None:
        self._end(step, "failed")

    def _end(self, step: str, state: StageState) -> None:
        with self._lock:
            if self._stages[step].state not in _ENDED:
                self._stages[step] = finished(self._stages[step], state, time())
        self._emit()

    def snapshot(self) -> PlanSnapshot:
        with self._lock:
            return PlanSnapshot(tuple(self._stages.values()), self._main)

    def _emit(self) -> None:
        if self.sink is not None:
            self.sink(self.snapshot())
