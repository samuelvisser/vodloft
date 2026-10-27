from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from ..contract import (
    Feature, LinkKind, Playback, PlaybackKind, ResolvedLink, SearchResults, SeasonRef, ShowDetails, Source,
    CookiesStatus, SourceProblem, VideoDetails,
)
from .. import ytdlp_runner as runner
from . import account
from .client import ORIGIN, NpoClient, NpoError, NpoNotFoundError

logger = logging.getLogger(__name__)

_SEARCH_LIMIT = 20
_EXPIRY_WARNING = timedelta(days=3)


def series_url(slug: str) -> str:
    return f"{ORIGIN}/start/serie/{slug}/afleveringen"


def program_url(slug: str) -> str:
    return f"{ORIGIN}/start/afspelen/{slug}"


def parse_link(url: str) -> tuple[LinkKind, str] | None:
    """What an npo.nl link points to: a series, or a programme to play.

    Series pages are /start/serie/<series>, with /afleveringen and a season
    after it. A programme plays at /start/afspelen/<programme>, or at
    /start/serie/<series>/<season>/<programme>/afspelen.
    """
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(parts) < 3 or parts[0] != "start":
        return None
    if parts[1] == "afspelen":
        return LinkKind.VIDEO, parts[2]
    if parts[1] != "serie":
        return None
    if parts[-1] == "afspelen" and len(parts) >= 5:
        return LinkKind.VIDEO, parts[-2]
    return LinkKind.SHOW, parts[2]


def _image(item: dict) -> str | None:
    images = [image for image in item.get("images") or [] if isinstance(image, dict) and image.get("url")]
    for image in images:
        if image.get("role") == "default":
            return image["url"]
    return images[0]["url"] if images else None


def _synopsis(item: dict) -> str | None:
    synopsis = item.get("synopsis")
    if isinstance(synopsis, dict):
        synopsis = synopsis.get("long") or synopsis.get("short") or synopsis.get("brief")
    return synopsis.strip() if isinstance(synopsis, str) and synopsis.strip() else None


def _broadcasters(item: dict) -> str | None:
    names = []
    for broadcaster in item.get("broadcasters") or []:
        name = broadcaster.get("name") if isinstance(broadcaster, dict) else broadcaster
        if isinstance(name, str) and name:
            names.append(name)
    return ", ".join(names) or None


def _timestamp(item: dict) -> datetime | None:
    for key in ("firstBroadcastDate", "publishedDateTime"):
        value = item.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _number(value) -> int | None:
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def stream_protected(stream_link: dict) -> bool:
    """NPO serves a clear stream from /package/clear/ and says nothing about DRM.
    A protected one names its DRM and comes from /package/drmcbcs/ or /package/drmcenc/."""
    stream = stream_link.get("stream")
    if not isinstance(stream, dict):
        return False
    url = str(stream.get("streamURL") or "")
    return bool(stream.get("drm")) or "/package/drm" in urlsplit(url).path


def _instant(value) -> float | None:
    """NPO gives availability windows in seconds, and sometimes in milliseconds."""
    if not isinstance(value, (int, float)):
        return None
    return value / 1000 if value > 100_000_000_000 else float(value)


def needs_subscription(program: dict, now: datetime | None = None) -> bool:
    """Whether NPO only gives the programme to NPO Plus subscribers right now.

    Each restriction says for which window the programme is available to whom,
    ``free`` or ``premium``. A programme with a free window open right now is free.
    """
    moment = (now or datetime.now(timezone.utc)).timestamp()
    current = []
    for restriction in program.get("restrictions") or []:
        if not isinstance(restriction, dict):
            continue
        available = restriction.get("available") if isinstance(restriction.get("available"), dict) else {}
        start, end = _instant(available.get("from")), _instant(available.get("till"))
        if (start is None or start <= moment) and (end is None or moment < end):
            current.append(restriction.get("subscriptionType"))
    return "premium" in current and "free" not in current


class NpoSource(Source):
    """NPO Start, the Dutch public broadcaster's catalogue."""

    id = "npo"
    name = "NPO Start"
    domains = ("npo.nl",)
    features = frozenset({Feature.SHOWS, Feature.EPISODE_LISTS, Feature.VIDEOS, Feature.SEARCH, Feature.COOKIES})
    subscription_name = "NPO Plus"
    cookies_help = (
        "Optional. Sign in with your NPO account to download programmes that need NPO Plus. Sign in on "
        "npo.nl in your browser, export a cookies.txt file for npo.nl, and choose it here. VODLoft never "
        "sees your password. Programmes protected by DRM still can't be downloaded."
    )

    def __init__(self, client: NpoClient | None = None):
        self._client = client or NpoClient()

    def _protected(self, program: dict) -> bool | None:
        """Whether the programme is protected by DRM, or None when NPO will not say right now,
        such as for a programme that is not out yet or needs a subscription."""
        if needs_subscription(program) and not self.subscription_active:
            # NPO gives no stream to an anonymous player for it, so asking would only fail.
            return None
        product_id = program.get("productId")
        if not product_id or not program.get("slug"):
            return None
        try:
            return stream_protected(self._client.stream_link(product_id, program_url(program["slug"])))
        except NpoError as exc:
            logger.info("NPO Start gave no stream for %s: %s", program.get("slug"), exc)
            return None

    def _video(self, program: dict, *, season: SeasonRef | None = None, drm_protected: bool = False) -> VideoDetails:
        series = program.get("series") if isinstance(program.get("series"), dict) else {}
        duration = program.get("durationInSeconds")
        return VideoDetails(
            slug=program["slug"],
            url=program_url(program["slug"]),
            title=program.get("title") or series.get("title") or program["slug"],
            description=_synopsis(program),
            duration=float(duration) if isinstance(duration, (int, float)) else None,
            image_url=_image(program),
            author_name=series.get("title") or self.name,
            author_url=series_url(series["slug"]) if series.get("slug") else None,
            published_at=_timestamp(program),
            drm_protected=drm_protected,
            needs_subscription=needs_subscription(program),
            season=season,
            episode_number=_number(program.get("programKey")),
        )

    def _show(self, series: dict) -> ShowDetails:
        return ShowDetails(
            slug=series["slug"],
            url=series_url(series["slug"]),
            title=series.get("title") or series["slug"],
            description=_synopsis(series),
            image_url=_image(series),
            author_name=_broadcasters(series) or self.name,
        )

    def _series(self, slug: str) -> dict:
        series = self._client.series_detail(slug)
        if not series.get("slug"):
            raise NpoNotFoundError("NPO Start does not know this series")
        return series

    def resolve(self, url: str) -> ResolvedLink | None:
        parsed = parse_link(url)
        if parsed is None:
            return None
        kind, slug = parsed
        try:
            if kind is LinkKind.SHOW:
                show = self._show(self._series(slug))
                return ResolvedLink(
                    kind=LinkKind.SHOW, slug=show.slug, url=show.url, title=show.title,
                    description=show.description, image_url=show.image_url, author_name=show.author_name,
                )
            program = self._client.program_detail(slug)
        except NpoNotFoundError:
            return None
        if not program.get("slug"):
            return None
        return self._program_link(program, drm_protected=bool(self._protected(program)))

    def _program_link(self, program: dict, *, drm_protected: bool = False) -> ResolvedLink:
        video = self._video(program, drm_protected=drm_protected)
        series = program.get("series") if isinstance(program.get("series"), dict) else {}
        in_series = bool(series.get("slug"))
        return ResolvedLink(
            kind=LinkKind.EPISODE if in_series else LinkKind.VIDEO,
            slug=video.slug, url=video.url, title=video.title, description=video.description,
            image_url=video.image_url, author_name=video.author_name,
            show_slug=series.get("slug") if in_series else None,
            show_url=series_url(series["slug"]) if in_series else None,
            drm_protected=drm_protected,
            needs_subscription=video.needs_subscription,
        )

    def search(self, query: str) -> SearchResults:
        query = query.strip()
        if not query:
            return SearchResults([])
        results = [
            ResolvedLink(
                kind=LinkKind.SHOW, slug=item["slug"], url=series_url(item["slug"]),
                title=item.get("title") or item["slug"], image_url=_image(item),
            )
            for item in self._client.search(query, "series")[:_SEARCH_LIMIT] if item.get("slug")
        ]
        results += [
            self._program_link(item)
            for item in self._client.search(query, "broadcasts")[:_SEARCH_LIMIT] if item.get("slug")
        ]
        return SearchResults(results)

    def show_details(self, url: str) -> ShowDetails:
        parsed = parse_link(url)
        if parsed is None or parsed[0] is not LinkKind.SHOW:
            raise NpoError("This is not a link to a series on NPO Start")
        series = self._series(parsed[1])
        seasons = tuple(ref for _guid, ref in self._seasons(series))
        return replace(self._show(series), seasons=seasons)

    def _seasons(self, series: dict) -> list[tuple[str, SeasonRef]]:
        """Each season's guid and how VODLoft names it, oldest first."""
        seasons = []
        for position, season in enumerate(self._client.series_seasons(series["slug"], series.get("type")), start=1):
            if not season.get("guid"):
                continue
            seasons.append((season["guid"], SeasonRef(
                slug=season.get("slug") or f"seizoen-{position}",
                number=_number(season.get("seasonKey")) or position,
                title=season.get("label") or None,
            )))
        return seasons

    def video_details(self, url: str) -> VideoDetails:
        parsed = parse_link(url)
        if parsed is None or parsed[0] is not LinkKind.VIDEO:
            raise NpoError("This is not a link to a programme on NPO Start")
        program = self._client.program_detail(parsed[1])
        return self._video(program, drm_protected=bool(self._protected(program)))

    def _season_drm(self, programs: list[dict]) -> dict[str, bool]:
        """DRM per programme of a season, from as few stream lookups as it takes.

        NPO protects whole seasons, so when the first and last programme agree the
        rest is taken to match. Otherwise each programme is looked up. A clear
        programme that turns out to be protected is marked when it is downloaded.
        """
        if not self.subscription_active:
            programs = [program for program in programs if not needs_subscription(program)]
        if not programs:
            return {}
        ends = [programs[0], programs[-1]] if len(programs) > 1 else [programs[0]]
        states = [self._protected(program) for program in ends]
        if all(state is not None for state in states) and len(set(states)) == 1:
            return {program["slug"]: bool(states[0]) for program in programs}
        return {program["slug"]: bool(self._protected(program)) for program in programs}

    def list_episodes(self, url: str, *, known: frozenset[str]) -> Iterator[VideoDetails]:
        parsed = parse_link(url)
        if parsed is None or parsed[0] is not LinkKind.SHOW:
            raise NpoError("This is not a link to a series on NPO Start")
        series = self._series(parsed[1])
        for guid, ref in self._seasons(series):
            try:
                programs = self._client.programs_by_season(guid)
            except NpoError as exc:
                logger.info("Skipping season %s of %s for now: %s", ref.number, series["slug"], exc)
                continue
            new = [program for program in programs if program.get("slug") and program["slug"] not in known]
            drm = self._season_drm(new)
            for program in new:
                yield self._video(program, season=ref, drm_protected=drm.get(program["slug"], False))

    def video_playback(self, *, slug: str, url: str) -> Playback:
        parsed = parse_link(url)
        program = self._client.program_detail(parsed[1] if parsed else slug)
        premium = needs_subscription(program)
        if premium and not self.subscription_active:
            return Playback(url=program_url(program.get("slug") or slug), needs_subscription=True)
        if not program.get("productId"):
            raise NpoError("NPO Start has no stream for this programme")
        try:
            stream_link = self._client.stream_link(program["productId"], program_url(program["slug"]))
        except NpoError:
            if premium:
                # The sign-in no longer gives this account NPO Plus.
                return Playback(url=program_url(program["slug"]), needs_subscription=True)
            raise
        stream = stream_link.get("stream") if isinstance(stream_link.get("stream"), dict) else {}
        stream_url = stream.get("streamURL")
        if not isinstance(stream_url, str) or not stream_url.startswith("https://"):
            raise NpoError("NPO Start has no stream for this programme right now")
        if stream_protected(stream_link):
            return Playback(url=stream_url, drm_protected=True)
        # The stream keeps its audio in a rendition of its own, which yt-dlp joins to the video.
        return Playback(url=stream_url, kind=PlaybackKind.YTDLP, command=runner.command())

    @property
    def download_streams(self) -> int | None:
        # NPO Plus plays two streams at once; one is left for watching.
        return 1 if self.subscription_active else None

    @property
    def subscription_active(self) -> bool:
        status = account.status(self._client)
        return status is not None and status.subscription

    def problems(self) -> list[SourceProblem]:
        status = account.status(self._client)
        if status is None:
            return []
        if not status.signed_in:
            return [SourceProblem(
                "NPO sign-in expired",
                "The NPO cookies file no longer signs in, so programmes that need NPO Plus wait. Sign in on npo.nl "
                "and choose a new cookies file under Settings › Sources › NPO Start. Free programmes keep downloading.",
                fix_url=f"{ORIGIN}/start",
            )]
        if not status.subscription:
            return [SourceProblem(
                "No NPO Plus on this NPO account",
                "You are signed in to NPO, but the account has no NPO Plus, so programmes that need it wait. "
                "Free programmes keep downloading.",
                fix_url=f"{ORIGIN}/start",
            )]
        if status.expires_at is not None and status.expires_at - datetime.now(timezone.utc) < _EXPIRY_WARNING:
            return [SourceProblem(
                "NPO sign-in expires soon",
                f"The NPO cookies file stops working on {status.expires_at:%d %B}. Sign in on npo.nl and choose a "
                "new cookies file under Settings › Sources › NPO Start.",
                fix_url=f"{ORIGIN}/start",
            )]
        return []

    def has_cookies(self) -> bool:
        return account.has_cookies()

    def cookies_status(self) -> CookiesStatus | None:
        status = account.status(self._client)
        if status is None:
            return None
        if not status.verified:
            return CookiesStatus("Not checked yet", ok=False, detail="npo.nl could not be reached to check the sign-in.")
        if not status.signed_in:
            return CookiesStatus("Signed out", ok=False, detail="This cookies file no longer signs in to NPO.")
        until = f" The sign-in lasts until {status.expires_at:%d %B %Y}." if status.expires_at else ""
        if not status.subscription:
            return CookiesStatus("No NPO Plus", ok=False, detail=f"Signed in, but this NPO account has no NPO Plus.{until}")
        return CookiesStatus("NPO Plus", ok=True, detail=f"Signed in with NPO Plus.{until}")

    def save_cookies(self, content: bytes) -> None:
        account.save_cookies(content)

    def remove_cookies(self) -> None:
        account.remove_cookies()
