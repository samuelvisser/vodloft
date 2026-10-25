"""Running yt-dlp, and keeping it up to date.

VODLoft ships the yt-dlp Python package. Sites change faster than VODLoft
releases, so "Update now" and the weekly update fetch yt-dlp's own release
into the config directory, and that copy wins over the shipped one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from config import get_settings

RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
UPDATE_INTERVAL = timedelta(days=7)
_LOOKUP_TIMEOUT_SECONDS = 120
_update_lock = threading.Lock()


class YtDlpError(RuntimeError):
    """yt-dlp could not do what was asked; the message is yt-dlp's own."""


def ytdlp_directory() -> Path:
    return get_settings().database_path.parent / "yt-dlp"


def updated_program_path() -> Path:
    return ytdlp_directory() / "yt-dlp"


def cookies_path() -> Path:
    return ytdlp_directory() / "cookies.txt"


def _state_path() -> Path:
    return ytdlp_directory() / "update.json"


def program() -> tuple[str, ...]:
    """The command that starts yt-dlp: the updated release when there is one."""
    updated = updated_program_path()
    if updated.is_file():
        return (sys.executable, str(updated))
    return (sys.executable, "-m", "yt_dlp")


def command() -> tuple[str, ...]:
    """yt-dlp with the options every run uses."""
    options = ["--ignore-config", "--no-warnings", "--color", "never"]
    # YouTube needs a JavaScript runtime. VODLoft installs Deno next to Python,
    # which is not always on the PATH of the process that runs yt-dlp.
    deno = Path(sys.executable).with_name("deno")
    if deno.is_file():
        options += ["--js-runtimes", f"deno:{deno}"]
    cookies = cookies_path()
    if cookies.is_file():
        options += ["--cookies", str(cookies)]
    return (*program(), *options)


def error_message(output: str) -> str:
    """yt-dlp's last ERROR line, without the prefix, or its last line."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR:")]
    if errors:
        return errors[-1].removeprefix("ERROR:").strip()
    return lines[-1] if lines else "yt-dlp failed without a message"


def run_json(*args: str) -> dict:
    """Run yt-dlp with ``-J`` and return the info it prints."""
    try:
        result = subprocess.run(
            [*command(), "--no-progress", "-J", *args], capture_output=True, text=True,
            timeout=_LOOKUP_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise YtDlpError("yt-dlp took too long to look up this link") from exc
    if result.returncode != 0:
        raise YtDlpError(error_message(result.stderr))
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise YtDlpError("yt-dlp returned no information for this link") from exc
    if not isinstance(info, dict):
        raise YtDlpError("yt-dlp returned no information for this link")
    return info


def version(prog: tuple[str, ...] | None = None) -> str | None:
    try:
        result = subprocess.run(
            [*(prog or program()), "--version"], capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _read_state() -> dict:
    try:
        state = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _write_state(**values) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**_read_state(), **values}))


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def last_update() -> tuple[datetime | None, str | None]:
    """When the last update succeeded, and why the one after it failed."""
    state = _read_state()
    return _parse_time(state.get("last_update_at")), state.get("last_update_error")


def update_due(now: datetime | None = None) -> bool:
    last = _parse_time(_read_state().get("last_update_at"))
    return last is None or (now or datetime.now(timezone.utc)) - last >= UPDATE_INTERVAL


def update() -> str:
    """Fetch the latest yt-dlp release and use it from now on. Returns its version."""
    with _update_lock:
        target = updated_program_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        download: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".yt-dlp-", delete=False) as handle:
                download = Path(handle.name)
                with requests.get(RELEASE_URL, stream=True, timeout=60) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(1024 * 1024):
                        handle.write(chunk)
            new_version = version((sys.executable, str(download)))
            if new_version is None:
                raise YtDlpError("The downloaded yt-dlp release does not run")
            os.replace(download, target)
        except Exception as exc:
            if download is not None:
                download.unlink(missing_ok=True)
            _write_state(last_update_error=str(exc))
            raise
        _write_state(last_update_at=datetime.now(timezone.utc).isoformat(), last_update_error=None)
        return new_version


def save_cookies(content: bytes) -> None:
    """Store a Netscape cookies file that every yt-dlp run uses."""
    text = content.decode("utf-8", errors="replace")
    if not any(line.strip() and (not line.startswith("#") or line.startswith("#HttpOnly_")) and len(line.split("\t")) >= 7 for line in text.splitlines()):
        raise ValueError("This is not a cookies.txt file in the Netscape format")
    path = cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, 0o600)


def remove_cookies() -> None:
    cookies_path().unlink(missing_ok=True)
