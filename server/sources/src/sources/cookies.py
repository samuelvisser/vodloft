"""Cookies files for a signed-in browser session, one per Site.

A Site's cookies file holds only that Site's cookies, and every Source that signs in with
cookies uses it on the Site: yt-dlp on YouTube or Twitch, NPO Start on npo.nl, and yt-dlp
on npo.nl too.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
from urllib.parse import quote

from config.settings.base import get_config_path

from .contract import on_domain

HEADER = "# Netscape HTTP Cookie File\n"
_HTTP_ONLY = "#HttpOnly_"


def cookies_text(content: bytes) -> str:
    """The text of a Netscape cookies file. Raises ValueError for anything else."""
    text = content.decode("utf-8", errors="replace")
    if not cookie_lines(text):
        raise ValueError("This is not a cookies.txt file in the Netscape format")
    return text


def cookie_lines(text: str) -> list[str]:
    """The cookies of a Netscape cookies file, one line each."""
    return [
        line for line in text.splitlines()
        if line.strip() and (not line.startswith("#") or line.startswith(_HTTP_ONLY)) and len(line.split("\t")) >= 7
    ]


def cookie_domain(line: str) -> str:
    """The domain a cookie line is for, without its leading dot."""
    return line.split("\t")[0].removeprefix(_HTTP_ONLY).lstrip(".").lower()


def on_site(line: str, domains: Iterable[str]) -> bool:
    """True when the cookie goes along to one of the domains: it is for the domain, a subdomain of it,
    or a parent domain of it."""
    return shares_domain(cookie_domain(line), domains)


def shares_domain(domain: str, domains: Iterable[str]) -> bool:
    """True when the domain is one of the domains, or a subdomain or parent domain of one."""
    return any(on_domain(domain, other) or on_domain(other, domain) for other in domains)


def cookies_file(lines: Sequence[str]) -> str:
    return HEADER + "".join(f"{line}\n" for line in lines)


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


def cookies_directory() -> Path:
    return get_config_path().parent / "cookies"


def site_cookies_path(site_key: str) -> Path:
    """Where the Site's cookies file is kept. A Site key such as ``generic:example.com`` is quoted."""
    return cookies_directory() / f"{quote(site_key, safe='')}.txt"


def site_cookies(site_key: str | None) -> Path | None:
    """The Site's cookies file, or None when it has none."""
    if not site_key:
        return None
    path = site_cookies_path(site_key)
    return path if path.is_file() else None


def store_site_cookies(site_key: str, lines: Sequence[str]) -> None:
    store(site_cookies_path(site_key), cookies_file(lines))


def remove_site_cookies(site_key: str) -> None:
    site_cookies_path(site_key).unlink(missing_ok=True)
