"""The account sign-ins yt-dlp's Sites offer, and the cookies file a lookup or download signs in with.

A Site's implementation signs in (``OtherSitesImplementation.sign_in``) and says what to keep, which
``site_accounts`` stores. yt-dlp then signs in with the cookies of that sign-in, joined with the Site's own cookies
file. A sign-in that runs out, such as Twitch's, is renewed by its implementation before a run needs it.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from pathlib import Path

from ..contract import Site, SignInRejected
from .. import site_accounts

logger = logging.getLogger(__name__)

_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
"""One per Site, so two runs at once renew a sign-in only once."""


def _renewed(site: Site) -> None:
    from .site_implementations import IMPLEMENTATIONS, OtherSitesImplementation

    with _locks[site.key]:
        signed_in = site_accounts.load(site.key)
        if signed_in is None or not signed_in.due:
            return
        implementation = IMPLEMENTATIONS.get(site.key, OtherSitesImplementation)(site, _no_lookup)
        try:
            site_accounts.save(site.key, implementation.renew_sign_in(signed_in))
        except SignInRejected as exc:
            # The old cookies may still work for a while; the user sees the problem under Authentication.
            logger.warning("Could not renew the sign-in on %s: %s", site.name, exc)
            site_accounts.record_problem(site.key, str(exc))


def _no_lookup(url: str) -> dict:
    raise RuntimeError("Renewing a sign-in looks nothing up")


def cookies_file(site: Site, own: Path | None) -> Path | None:
    """The cookies file yt-dlp signs in with on the Site: its account sign-in, renewed when it is due, with its own
    cookies file ``own``."""
    if site.account_sign_in is None:
        return own
    signed_in = site_accounts.load(site.key)
    if signed_in is not None and signed_in.due:
        _renewed(site)
    return site_accounts.cookies_file(site.key, own)
