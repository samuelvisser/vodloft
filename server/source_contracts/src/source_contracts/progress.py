"""Small stderr event channel for one-shot Source download workers."""

import json
import sys

from . import DownloadEvent


def download_progress_hook():
    last_percent = -1

    def report(data: dict) -> None:
        nonlocal last_percent
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        transferred = data.get("downloaded_bytes")
        if not total or transferred is None:
            return
        percent = max(0, min(100, int(100 * transferred / total)))
        if percent <= last_percent:
            return
        last_percent = percent
        event = DownloadEvent(percent=percent)
        print(json.dumps({"event": event.model_dump()}), file=sys.stderr, flush=True)

    return report


def processing_progress_hook(data: dict) -> None:
    if data.get("status") == "started" and data.get("postprocessor") != "EffectiveMetadata":
        event = DownloadEvent(stage="processing")
        print(json.dumps({"event": event.model_dump()}), file=sys.stderr, flush=True)
