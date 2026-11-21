"""An answer that takes a while, sent as it goes: a line of JSON per step, then the result or what went wrong."""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator

from fastapi.responses import StreamingResponse

from backend.services.errors import ServiceError
from backend.services.source_requests import SourceRequestError
from config.network import NO_INTERNET_CONNECTION_MESSAGE, is_no_internet_error

logger = logging.getLogger(__name__)

STEPS_RESPONSE = {200: {"content": {"application/x-ndjson": {}}}}


def stream_steps(work: Callable[[Callable[..., None]], dict], failed: str) -> StreamingResponse:
    """Run ``work`` in a thread and send each ``{"step": "...", ...}`` line it sends, then the result it returns as one
    more line, or ``{"error": "..."}``: what the Site or VODLoft said, or ``failed`` for anything else."""
    lines: queue.Queue[dict] = queue.Queue()

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

    def stream() -> Iterator[str]:
        while True:
            line = lines.get()
            yield json.dumps(line) + "\n"
            if "step" not in line:
                return

    threading.Thread(target=run, name="steps", daemon=True).start()
    return StreamingResponse(stream(), media_type="application/x-ndjson")
