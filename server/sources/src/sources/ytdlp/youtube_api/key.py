"""The API key and the last problem Google reported with it.

The key is a secret like the cookies file next to it, so it is stored the
same way and never shown, logged or put in a URL.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ... import ytdlp_runner as runner

_lock = threading.Lock()


@dataclass(frozen=True)
class KeyProblem:
    message: str
    fix_url: str | None
    at: datetime


def _key_path() -> Path:
    return runner.ytdlp_directory() / "youtube-api-key.txt"


def _problem_path() -> Path:
    return runner.ytdlp_directory() / "youtube-api-problem.json"


def load() -> str | None:
    try:
        return _key_path().read_text().strip() or None
    except OSError:
        return None


def save(key: str) -> None:
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key)
    os.chmod(path, 0o600)
    clear_problem()


def remove() -> None:
    _key_path().unlink(missing_ok=True)
    clear_problem()


def hint(key: str) -> str:
    """The last few characters, so the user can tell which key is in use."""
    return key[-3:]


def redact(text: str, key: str | None = None) -> str:
    """The text with the key replaced, for anything that might reach a log or a task message."""
    key = key or load()
    return text.replace(key, "•••") if key else text


def problem() -> KeyProblem | None:
    try:
        data = json.loads(_problem_path().read_text())
        return KeyProblem(data["message"], data.get("fix_url"), datetime.fromisoformat(data["at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_problem(message: str, fix_url: str | None) -> None:
    with _lock:
        path = _problem_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"message": message, "fix_url": fix_url, "at": datetime.now(timezone.utc).isoformat()}))


def clear_problem() -> None:
    with _lock:
        _problem_path().unlink(missing_ok=True)
