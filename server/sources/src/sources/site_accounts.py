"""The account sign-in a Source keeps for a Site, such as yt-dlp's on Nebula or Twitch, one file per Site.

A sign-in ends in the cookies the Site's own website would keep, so every program that signs in with a cookies
file signs in with it too. The Site's cookies file stays as the user gave it: a lookup or download gets one file
with both, in which the sign-in's cookies win. A sign-in also keeps what its Source needs to renew it, such as a
refresh token. These are secrets like the cookies files beside them, so they are stored the same way and never
shown, logged or put in a URL.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

from . import cookies


@dataclass(frozen=True)
class SignedIn:
    """One account sign-in on a Site."""

    cookies: tuple[str, ...]
    """The cookies it signs in with, as lines of a Netscape cookies file (``cookie_line``)."""
    account: str | None = None
    """The name or email address of the account, when the Site tells it."""
    secrets: dict[str, str] = field(default_factory=dict)
    """What the Source needs to renew the sign-in, such as a refresh token."""
    renew_at: float | None = None
    """When the Source renews the sign-in, as a Unix time; None for one that lasts until the user signs out."""
    problem: str | None = None
    """What went wrong the last time the Source renewed it."""

    @property
    def due(self) -> bool:
        return self.renew_at is not None and time.time() >= self.renew_at


def cookie_line(domain: str, name: str, value: str, expires: float | None = None) -> str:
    """A cookie for the domain and its subdomains, as a line of a Netscape cookies file. Without ``expires`` it
    lasts until the sign-in is renewed or removed."""
    return "\t".join((f".{domain}", "TRUE", "/", "TRUE", str(int(expires or 0)), name, value))


def _directory() -> Path:
    return cookies.cookies_directory().parent / "site-accounts"


def _path(site_key: str) -> Path:
    return _directory() / f"{quote(site_key, safe='')}.json"


def _cookies_path(site_key: str) -> Path:
    return _directory() / f"{quote(site_key, safe='')}.txt"


def load(site_key: str) -> SignedIn | None:
    """The Site's sign-in, or None when there is none."""
    try:
        data = json.loads(_path(site_key).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("cookies"):
        return None
    return SignedIn(
        cookies=tuple(str(line) for line in data["cookies"]),
        account=data.get("account") or None,
        secrets={str(key): str(value) for key, value in (data.get("secrets") or {}).items()},
        renew_at=data.get("renew_at"),
        problem=data.get("problem") or None,
    )


def save(site_key: str, signed_in: SignedIn) -> None:
    record = asdict(signed_in)
    record["cookies"] = list(signed_in.cookies)
    cookies.store(_path(site_key), json.dumps(record))


def record_problem(site_key: str, problem: str | None) -> None:
    """What went wrong renewing the Site's sign-in, or None once it works again."""
    signed_in = load(site_key)
    if signed_in is not None and signed_in.problem != problem:
        save(site_key, SignedIn(**{**asdict(signed_in), "cookies": signed_in.cookies, "problem": problem}))


def remove(site_key: str) -> None:
    _path(site_key).unlink(missing_ok=True)
    _cookies_path(site_key).unlink(missing_ok=True)


def _name(line: str) -> str:
    return line.split("\t")[5]


def cookies_file(site_key: str, own: Path | None) -> Path | None:
    """The one cookies file of the Site's sign-in and its own cookies file ``own``: ``own`` when the Site has no
    sign-in, and None when it has neither. A cookie of the sign-in replaces one of the same name in ``own``.

    yt-dlp writes the cookies it got back into the file it signed in with, so the file is made again whenever it
    differs from the sign-in and ``own``."""
    signed_in = load(site_key)
    if signed_in is None:
        return own
    names = {_name(line) for line in signed_in.cookies}
    kept: list[str] = []
    if own is not None:
        try:
            kept = [line for line in cookies.cookie_lines(own.read_text(errors="replace")) if _name(line) not in names]
        except OSError:
            kept = []
    text = cookies.cookies_file([*kept, *signed_in.cookies])
    path = _cookies_path(site_key)
    try:
        if path.read_text() == text:
            return path
    except OSError:
        pass
    # Written beside the file and moved over it, so a run that reads it meanwhile never sees half a file.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    cookies.store(temporary, text)
    os.replace(temporary, path)
    return path
