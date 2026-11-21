"""An answer that takes a while, sent as it goes: a line of JSON per step, then the result or what went wrong."""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import asdict

from fastapi.responses import StreamingResponse
from progress_plan import PlanSnapshot

from backend.services.errors import ServiceError
from backend.services.source_requests import SourceRequestError
from config.network import NO_INTERNET_CONNECTION_MESSAGE, is_no_internet_error

logger = logging.getLogger(__name__)

STEPS_RESPONSE = {200: {"content": {"application/x-ndjson": {}}}}


def stream_steps(work: Callable[[Callable[..., None]], dict], failed: str) -> StreamingResponse:
    """Run ``work`` in a thread and send each line it sends as it goes, such as ``{"plan": ...}`` from ``plan_lines``,
    then the result it returns as the last line, or ``{"error": "..."}``: what the Site or VODLoft said, or ``failed``
    for anything else."""
    lines: queue.Queue[dict | None] = queue.Queue()

    def send(**line) -> None:
        lines.put(line)

    def run() -> None:
        try:
            send(**work(send))
        except Exception as exc:
            if is_no_internet_error(exc):
                send(error=NO_INTERNET_CONNECTION_MESSAGE)
            elif isinstance(exc, (ServiceError, SourceRequestError)):
                send(error=str(exc))
            else:
                logger.exception(failed)
                send(error=failed)
        lines.put(None)

    def stream() -> Iterator[str]:
        while (line := lines.get()) is not None:
            yield json.dumps(line) + "\n"

    threading.Thread(target=run, name="steps", daemon=True).start()
    return StreamingResponse(stream(), media_type="application/x-ndjson")


def plan_lines(send: Callable[..., None]) -> Callable[[PlanSnapshot], None]:
    """Sends a plan each time it changes as a ``{"plan": {"main_activity", "stages"}}`` line, the way tasks report
    theirs, so the UI shows its steps the way it shows a task's."""
    def sink(snapshot: PlanSnapshot) -> None:
        send(plan={"main_activity": snapshot.main_activity, "stages": [asdict(stage) for stage in snapshot.stages]})
    return sink
