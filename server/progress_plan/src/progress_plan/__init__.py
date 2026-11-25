"""A plan of weighted steps that a long piece of work reports its progress by.

Work draws up its plan before it starts: each step with a weight, the share of the work it is. While it runs, each
step is pending, running, waiting, done (completed or skipped) or stopped (failed or canceled), and a running step
reports how far it is with a fraction, or with none when it cannot measure itself, such as one long database write.
The whole plan is as far as its steps' weights together.

Downloads report their attempt this way, and so can any task. The package knows nothing of VODLoft.
"""
from .stages import (
    DONE, PlanSnapshot, PlanTracker, Stage, StageSpec, StageState, WaitInterval, completion_fraction, finished,
    measured, started, waiting,
)

__all__ = [
    "DONE", "PlanSnapshot", "PlanTracker", "Stage", "StageSpec", "StageState", "WaitInterval", "completion_fraction",
    "finished", "measured", "started", "waiting",
]
