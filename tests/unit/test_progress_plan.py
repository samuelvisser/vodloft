"""The shared plan of steps that downloads and other tasks report their progress by."""
from __future__ import annotations

import pytest


def test_a_plan_counts_its_steps_by_weight_and_says_when_it_cannot_measure():
    from progress_plan import PlanTracker, StageSpec

    reports = []
    plan = PlanTracker(
        [StageSpec(id="number", code="number", weight=1.0, label="Numbering"),
         StageSpec(id="rename", code="rename", weight=3.0, label="Renaming")],
        sink=reports.append,
    )
    plan.start("number")
    assert (plan.snapshot().measurable, plan.snapshot().fraction, plan.snapshot().main.label) == (False, 0.0, "Numbering")

    plan.complete("number")
    plan.start("rename")
    plan.progress("rename", 0.5)
    snapshot = plan.snapshot()
    assert snapshot.measurable and snapshot.fraction == pytest.approx(0.625)

    # A step that ends without its work, such as a failed one, keeps how far it got and counts for none of it.
    plan.fail("rename")
    plan.complete("rename")
    assert plan.snapshot().stages[1].state == "failed"
    assert plan.snapshot().fraction == pytest.approx(0.25)
    assert len(reports) == 6


def test_a_plan_refuses_a_step_twice_and_bad_weights():
    from progress_plan import PlanTracker, StageSpec

    with pytest.raises(ValueError):
        StageSpec(id="a", code="a", weight=-1)
    plan = PlanTracker([StageSpec(id="a", code="a")])
    with pytest.raises(ValueError):
        plan.add(StageSpec(id="a", code="a"))
    plan.start("a")
    with pytest.raises(ValueError):
        plan.start("a")


def test_waiting_moves_a_steps_deadline_on_by_the_time_it_waited():
    from progress_plan import Stage, started, waiting

    stage = started(Stage(id="a", code="a", weight=1), 100.0, deadline_seconds=60)
    stage = waiting(stage, "site_throttled", None, 110.0)
    assert stage.state == "waiting" and stage.wait.reason == "site_throttled"
    stage = waiting(stage, None, None, 130.0)
    assert (stage.state, stage.deadline_at, len(stage.waits)) == ("running", 180.0, 1)


def test_downloads_report_their_attempt_as_a_plan():
    from downloader.lifecycle import StageSnapshot
    from progress_plan import Stage

    assert issubclass(StageSnapshot, Stage)


def test_the_package_never_imports_vodloft():
    import ast
    from pathlib import Path

    import progress_plan

    vodloft = {"backend", "task_manager", "downloader", "controller", "sources", "config", "importer"}
    for path in Path(progress_plan.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else []
            )
            assert not {name.split(".")[0] for name in names} & vodloft, path


def test_a_step_that_counts_says_how_many_of_how_many_it_did():
    from progress_plan import PlanTracker, StageSpec

    plan = PlanTracker([StageSpec(id="rewrite", code="rewrite_metadata", unit="episodes")])
    plan.start("rewrite")
    plan.progress("rewrite", 0.1, done=11, total=110)
    stage = plan.snapshot().main
    assert (stage.unit, stage.done, stage.total, stage.fraction) == ("episodes", 11, 110, 0.1)
    # A step that does not count leaves its count as it was.
    plan.progress("rewrite", 0.2)
    assert (plan.snapshot().main.done, plan.snapshot().main.fraction) == (11, 0.2)


def test_a_step_runs_for_a_block_or_beside_other_work_while_a_future_does():
    from concurrent.futures import Future

    from progress_plan import PlanTracker, StageSpec

    plan = PlanTracker([StageSpec(id=key, code=key) for key in ("block", "broken", "main", "extra")])
    with plan.running("block"):
        assert plan.snapshot().main.state == "running"
    with pytest.raises(ValueError), plan.running("broken"):
        raise ValueError("gone")
    main, extra = Future(), Future()
    followed = plan.follow("main", main)
    skipped = plan.follow("extra", extra, failed="skipped")
    assert {stage.id: stage.state for stage in plan.snapshot().stages}["main"] == "running"
    main.set_result({"title": "Palaces"})
    extra.set_exception(LookupError("no such page"))

    # The followed work's outcome, once its step has ended.
    assert followed.result() == {"title": "Palaces"}
    assert isinstance(skipped.exception(), LookupError)

    assert {stage.id: stage.state for stage in plan.snapshot().stages} == {
        "block": "completed", "broken": "failed", "main": "completed", "extra": "skipped",
    }
