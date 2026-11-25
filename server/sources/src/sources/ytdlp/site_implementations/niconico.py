"""How yt-dlp signs in on Niconico: with the account's email address or phone number and password on its sign-in
page, as a browser does. Niconico's session cookie runs out, so VODLoft keeps them to sign in again before it does.
And how VODLoft searches Niconico: through its official search API, which finds videos."""
from __future__ import annotations

import html
import re
from collections.abc import Mapping
from datetime import datetime

from ...contract import LinkKind, ResolvedLink, SearchResults, SignInRejected
from ...site_accounts import SignedIn
from .. import site_search
from ..search_facts import date, facts, length, plural
from . import web_sign_in
from .other_sites import OtherSitesImplementation

_ACCOUNTS = "https://account.nicovideo.jp"
_SESSION_COOKIE = "user_session"
_NOTICE = re.compile(r"""class=["'][^"']*notice__text[^"']*["'][^>]*>(.*?)</""", re.S)
_SEARCH = "https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
_VIDEOS = 20
# Niconico asks every caller of its search API to name itself.
_CONTEXT = "VODLoft"


def _started(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class NiconicoImplementation(OtherSitesImplementation):
    key = "niconico"

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        email, password = web_sign_in.credentials(values)
        session = web_sign_in.browser()
        web_sign_in.answer(self.site.name, lambda: session.get(f"{_ACCOUNTS}/login", timeout=web_sign_in.TIMEOUT_SECONDS))
        response = web_sign_in.answer(self.site.name, lambda: session.post(
            f"{_ACCOUNTS}/login/redirector", data={"mail_tel": email, "password": password},
            headers={"Referer": f"{_ACCOUNTS}/login"}, timeout=web_sign_in.TIMEOUT_SECONDS,
        ))
        if any(cookie.name == _SESSION_COOKIE for cookie in session.cookies):
            return web_sign_in.signed_in(session, ("nicovideo.jp",), email, password)
        if "oneTimePw" in response.text:
            raise SignInRejected(
                "Your Niconico account asks for a one-time code when it signs in, which VODLoft can't fill in. "
                "Sign in with a cookies file instead.",
            )
        notice = _NOTICE.search(response.text)
        message = html.unescape(re.sub(r"<[^>]+>", "", notice.group(1))).strip() if notice else ""
        raise SignInRejected(message or "Niconico does not accept this email address or phone number and password.", web_sign_in.PASSWORD)

    def renew_sign_in(self, signed_in: SignedIn) -> SignedIn:
        return self.sign_in(signed_in.secrets)

    def search(self, query: str) -> SearchResults:
        """The videos whose title or tags match, the most watched first: the API has no order by how well they
        match."""
        found = site_search.ask(self.site.name, _SEARCH, params={
            "q": query, "targets": "title,tags", "_sort": "-viewCounter", "_limit": _VIDEOS, "_context": _CONTEXT,
            "fields": "contentId,title,description,viewCounter,lengthSeconds,startTime,thumbnailUrl",
        })
        return SearchResults([self._video(item) for item in found.get("data") or [] if item.get("contentId")])

    def _video(self, item: dict) -> ResolvedLink:
        content_id = item["contentId"]
        return ResolvedLink(
            kind=LinkKind.VIDEO, slug=f"niconico-{content_id}", url=f"https://www.nicovideo.jp/watch/{content_id}",
            title=item.get("title") or content_id, description=site_search.text(item.get("description")),
            image_url=item.get("thumbnailUrl"), site=self.site.name, kind_label="Video",
            facts=facts(length(item.get("lengthSeconds")), date(_started(item.get("startTime"))),
                        plural(item.get("viewCounter"), "view")),
        )
