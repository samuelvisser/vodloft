"""How yt-dlp signs in on Nebula: with the account's email and password, which Nebula trades for a token that lasts
until the user signs out. And how VODLoft searches Nebula: through Nebula's public content API, which needs no
sign-in."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from ...contract import LinkKind, ResolvedLink, SearchResults, SignInRejected
from ...site_accounts import SignedIn, cookie_line
from .. import site_search
from ..search_facts import date, facts, length
from . import web_sign_in
from .other_sites import OtherSitesImplementation

_LOGIN_URL = "https://nebula.tv/auth/login/"
# yt-dlp reads the token from the cookie Nebula's website keeps it in.
_TOKEN_COOKIE = "nebula_auth.apiToken"
_API = "https://content.api.nebula.app"
_CHANNELS = 5
_VIDEOS = 20


def _image(images: dict, *names: str) -> str | None:
    return next(((images.get(name) or {}).get("src") for name in names if (images.get(name) or {}).get("src")), None)


def _published(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class NebulaImplementation(OtherSitesImplementation):
    key = "nebula"

    def sign_in(self, values: Mapping[str, str]) -> SignedIn:
        email, password = web_sign_in.credentials(values)
        session = web_sign_in.browser()
        response = web_sign_in.answer(self.site.name, lambda: session.post(
            _LOGIN_URL, json={"email": email, "password": password}, timeout=web_sign_in.TIMEOUT_SECONDS,
        ))
        if response.status_code in (400, 401, 403):
            raise SignInRejected("Nebula does not accept this email address and password.", web_sign_in.PASSWORD)
        if not response.ok:
            raise SignInRejected(f"Nebula answered {response.status_code}. Try again later.")
        token = str((response.json() or {}).get("key") or "")
        if not token:
            raise SignInRejected("Nebula signed in, but gave no token. Try again later.")
        return SignedIn(cookies=(cookie_line("nebula.tv", _TOKEN_COOKIE, token),), account=email)

    def search(self, query: str) -> SearchResults:
        """The best matching channels, then videos."""
        channels, videos = site_search.at_once(
            lambda: site_search.ask(self.site.name, f"{_API}/video_channels/search/", params={"q": query}),
            lambda: site_search.ask(self.site.name, f"{_API}/video_episodes/search/", params={"q": query}),
        )
        found = [self._channel(item) for item in (channels.get("results") or [])[:_CHANNELS] if item.get("slug")]
        found += [self._video(item) for item in (videos.get("results") or [])[:_VIDEOS] if item.get("slug")]
        return SearchResults(found)

    def _channel(self, item: dict) -> ResolvedLink:
        slug = item["slug"]
        return ResolvedLink(
            kind=LinkKind.COLLECTION, slug=slug, url=f"https://nebula.tv/{slug}", title=item.get("title") or slug,
            description=item.get("description") or None, image_url=_image(item.get("images") or {}, "avatar"),
            site=self.site.name, kind_label="Channel", facts=facts(item.get("genre_category_title") or None),
        )

    def _video(self, item: dict) -> ResolvedLink:
        slug = item["slug"]
        return ResolvedLink(
            kind=LinkKind.VIDEO, slug=f"nebula-{slug}", url=item.get("share_url") or f"https://nebula.tv/videos/{slug}",
            title=item.get("title") or slug, description=item.get("short_description") or None,
            image_url=_image(item.get("images") or {}, "thumbnail"), author_name=item.get("channel_title"),
            site=self.site.name, kind_label="Video",
            facts=facts(length(item.get("duration")), date(_published(item.get("published_at")))),
        )
