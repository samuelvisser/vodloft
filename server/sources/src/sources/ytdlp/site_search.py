"""Asking a Site's own public search API, for the Sites whose search needs no key and no yt-dlp."""
from __future__ import annotations

import html
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from .. import ytdlp_runner as runner
from sources.ytdlp_options import keep_call_options

_TIMEOUT_SECONDS = 15
_BROWSER = "Mozilla/5.0"
_TAG = re.compile(r"<[^>]+>")


def ask(site_name: str, url: str, *, params: dict | None = None, body: dict | None = None) -> Any:
    """The JSON the Site answers with: a GET, or a POST of ``body``. Raises YtDlpError when the Site does not answer."""
    try:
        response = requests.request(
            "POST" if body is not None else "GET", url, params=params, json=body, timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _BROWSER, "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        raise runner.YtDlpError(f"{site_name} could not be searched: it answered {exc.response.status_code}") from None
    except (requests.RequestException, ValueError) as exc:
        raise runner.YtDlpError(f"{site_name} could not be searched: {type(exc).__name__}") from None


def text(value) -> str | None:
    """A description as plain text: some Sites send theirs as HTML, such as with ``<br />``."""
    if not isinstance(value, str):
        return None
    plain = html.unescape(_TAG.sub(" ", value.replace("<br />", "\n").replace("<br>", "\n"))).strip()
    return plain or None


def at_once(*calls: Callable[[], Any]) -> list[Any]:
    """The answers of several requests to the Site, asked at the same time."""
    with ThreadPoolExecutor(max_workers=len(calls), **keep_call_options()) as pool:
        return [future.result() for future in [pool.submit(call) for call in calls]]
