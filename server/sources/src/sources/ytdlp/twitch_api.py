"""Twitch's own API (Helix), with the client ID and secret of an application the user registered at dev.twitch.tv.

Twitch gives every registered application an app access token for its client ID and secret, which reads public data
such as its search. VODLoft asks for one when it needs it and keeps it until Twitch says it expired. The ID and secret
are secrets like a cookies file, so they never reach a log or an error message.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

from ..contract import ApiKeyRejected, LinkKind, ResolvedLink
from .search_facts import facts

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_API = "https://api.twitch.tv/helix"
_TIMEOUT_SECONDS = 15
_CHANNELS = 20
CONSOLE = "https://dev.twitch.tv/console/apps"

_lock = threading.Lock()
_tokens: dict[str, tuple[str, float]] = {}
"""App access tokens by client ID, each with when it expires."""


class TwitchApiError(RuntimeError):
    pass


def _token(client_id: str, secret: str, *, fresh: bool = False) -> str:
    with _lock:
        known = _tokens.get(client_id)
        if known is not None and not fresh and known[1] > time.monotonic():
            return known[0]
    try:
        response = requests.post(_TOKEN_URL, data={
            "client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
        }, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise TwitchApiError(f"Could not reach Twitch: {type(exc).__name__}") from None
    if response.status_code in (400, 401, 403):
        raise ApiKeyRejected(
            "Twitch does not accept this client ID and secret. Check them on your application at dev.twitch.tv; a "
            "new secret replaces the old one.", CONSOLE,
        )
    if not response.ok:
        raise TwitchApiError(f"Twitch answered {response.status_code}")
    data = response.json()
    token = str(data.get("access_token") or "")
    if not token:
        raise TwitchApiError("Twitch gave no access token")
    # A little before Twitch's own expiry, so a token never runs out during a call.
    expires = time.monotonic() + max(int(data.get("expires_in") or 0) - 300, 60)
    with _lock:
        _tokens[client_id] = (token, expires)
    return token


def _get(values: dict[str, str], path: str, params: dict) -> dict:
    client_id, secret = values.get("client_id", ""), values.get("client_secret", "")
    if not client_id or not secret:
        raise ApiKeyRejected("Fill in both the client ID and the client secret", field="client_id" if not client_id else "client_secret")
    for fresh in (False, True):
        token = _token(client_id, secret, fresh=fresh)
        try:
            response = requests.get(
                f"{_API}/{path}", params=params, timeout=_TIMEOUT_SECONDS,
                headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"},
            )
        except requests.RequestException as exc:
            raise TwitchApiError(f"Could not reach Twitch: {type(exc).__name__}") from None
        # An expired or revoked token is asked for again once.
        if response.status_code == 401 and not fresh:
            continue
        if response.status_code in (401, 403):
            raise ApiKeyRejected("Twitch no longer accepts this client ID and secret", CONSOLE)
        if not response.ok:
            raise TwitchApiError(f"Twitch answered {response.status_code}")
        return response.json()
    raise TwitchApiError("Twitch did not accept a fresh access token")


def test(values: dict[str, str]) -> None:
    """One call that only works with a valid client ID and secret."""
    _get(values, "search/channels", {"query": "twitch", "first": 1})


def search_channels(values: dict[str, str], query: str) -> list[ResolvedLink]:
    """The channels whose name matches, the ones streaming now first among equals, as Twitch orders them."""
    found = _get(values, "search/channels", {"query": query, "first": _CHANNELS})
    results = []
    for channel in found.get("data") or []:
        login = str(channel.get("broadcaster_login") or "")
        if not login:
            continue
        root = f"https://www.twitch.tv/{login}"
        results.append(ResolvedLink(
            kind=LinkKind.COLLECTION, slug=login, url=f"{root}/videos?filter=all",
            title=str(channel.get("display_name") or login), description=channel.get("title") or None,
            image_url=channel.get("thumbnail_url") or None, site="Twitch", kind_label="Channel",
            facts=facts("Live now" if channel.get("is_live") else None, channel.get("game_name") or None),
        ))
    return results
