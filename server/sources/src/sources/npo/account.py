"""The npo.nl session VODLoft signs in with: a cookies file exported from a signed-in browser.

VODLoft never sees the NPO password. The cookies only go along when NPO's
player is asked for a stream, so the catalogue is still read as an anonymous
visitor.
"""
from __future__ import annotations

from http.cookiejar import MozillaCookieJar
from pathlib import Path

from config.settings.base import get_config_path

from .. import cookies as cookie_files

_DOMAIN = "npo.nl"


def cookies_path() -> Path:
    return get_config_path().parent / "npo" / "cookies.txt"


def has_cookies() -> bool:
    return cookies_path().is_file()


def save_cookies(content: bytes) -> None:
    """Store the cookies file. Raises ValueError when it holds no npo.nl cookies."""
    text = cookie_files.cookies_text(content)
    if not any(_npo_cookie(line) for line in text.splitlines()):
        raise ValueError("This cookies file has no npo.nl cookies. Export it while signed in on npo.nl.")
    cookie_files.store(cookies_path(), text)


def remove_cookies() -> None:
    cookies_path().unlink(missing_ok=True)


def load_cookies() -> MozillaCookieJar | None:
    return cookie_files.load(cookies_path())


def _npo_cookie(line: str) -> bool:
    fields = line.split("\t")
    if len(fields) < 7:
        return False
    domain = fields[0].removeprefix("#HttpOnly_").lstrip(".").lower()
    return domain == _DOMAIN or domain.endswith(f".{_DOMAIN}")
