"""The values of a Site's own API that the user registered VODLoft with, such as Twitch's client ID and secret, one
file per Site.

They are secrets like the cookies files beside them, so they are stored the same way and never shown, logged or put
in a URL; the API only shows their last few characters.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

from .contract import SiteApi, SiteApiStatus
from . import cookies

_HINT_LENGTH = 4


def _path(site_key: str) -> Path:
    return cookies.cookies_directory().parent / "site-api" / f"{quote(site_key, safe='')}.json"


def _stored(site_key: str) -> dict:
    try:
        data = json.loads(_path(site_key).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(site_key: str) -> dict[str, str] | None:
    """The Site's API values by their field's key, or None when they are not set."""
    values = _stored(site_key).get("values")
    if not isinstance(values, dict) or not values:
        return None
    return {str(key): str(value) for key, value in values.items()}


def save(site_key: str, values: Mapping[str, str]) -> None:
    cookies.store(_path(site_key), json.dumps({"values": dict(values)}))


def remove(site_key: str) -> None:
    _path(site_key).unlink(missing_ok=True)


def record_problem(site_key: str, problem: str | None) -> None:
    """What the Site last said about the values, or None once they work again."""
    data = _stored(site_key)
    if not data or data.get("problem") == problem:
        return
    data["problem"] = problem
    cookies.store(_path(site_key), json.dumps(data))


def status(site_key: str, api: SiteApi) -> SiteApiStatus:
    values = load(site_key) or {}
    hints = {
        field.key: (f"…{values[field.key][-_HINT_LENGTH:]}" if field.secret else values[field.key])
        for field in api.fields if values.get(field.key)
    }
    problem = _stored(site_key).get("problem") if hints else None
    return SiteApiStatus(hints=hints, problem=str(problem) if problem else None)
