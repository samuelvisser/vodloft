"""Cookies files that Sources keep for a signed-in browser session."""
from __future__ import annotations

import os
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path


def cookies_text(content: bytes) -> str:
    """The text of a Netscape cookies file. Raises ValueError for anything else."""
    text = content.decode("utf-8", errors="replace")
    if not any(
        line.strip() and (not line.startswith("#") or line.startswith("#HttpOnly_")) and len(line.split("\t")) >= 7
        for line in text.splitlines()
    ):
        raise ValueError("This is not a cookies.txt file in the Netscape format")
    return text


def store(path: Path, text: str) -> None:
    """Write the file so that only VODLoft's own user can read it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, 0o600)


def load(path: Path) -> MozillaCookieJar | None:
    """The cookies in the file, or None when there is no usable file."""
    if not path.is_file():
        return None
    jar = MozillaCookieJar()
    try:
        # Browsers export session cookies without an expiry; they still count.
        jar.load(str(path), ignore_discard=True, ignore_expires=True)
    except (LoadError, OSError):
        return None
    return jar
