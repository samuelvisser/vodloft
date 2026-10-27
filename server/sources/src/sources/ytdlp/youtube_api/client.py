"""The calls VODLoft makes to the YouTube Data API v3.

Every call counts its units against a share of the daily quota before it is
made, and Google's errors become the few kinds the yt-dlp Source acts on. The
key travels in a header, so it never appears in a URL or an error message.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

import requests

from ... import pacing
from . import key as key_store, quota
from .quota import Share

logger = logging.getLogger(__name__)

API_URL = "https://www.googleapis.com/youtube/v3"
CREDENTIALS_URL = "https://console.cloud.google.com/apis/credentials"
ENABLE_API_URL = "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
MAX_RESULTS = 50
_TIMEOUT_SECONDS = 30
_RETRY_PAUSES_SECONDS = (1.0, 4.0)
_TEST_CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
"""Google for Developers, a channel that will be there for a long time."""


class YouTubeApiError(RuntimeError):
    """The API could not answer; the caller falls back to yt-dlp for this call."""

    fix_url: str | None = None


class ApiKeyError(YouTubeApiError):
    """Google does not accept the key, or the key may not call the YouTube Data API."""

    def __init__(self, message: str, fix_url: str | None = CREDENTIALS_URL):
        super().__init__(message)
        self.fix_url = fix_url


class ApiNotEnabledError(ApiKeyError):
    def __init__(self, fix_url: str | None = None):
        super().__init__(
            "The YouTube Data API is not enabled for this key's Google Cloud project. Enable it, wait a minute, "
            "and test the key again.",
            fix_url or ENABLE_API_URL,
        )


class QuotaExceededError(YouTubeApiError):
    """The share of the daily quota for this call is used, or Google says the whole quota is."""


class NotFoundError(YouTubeApiError):
    pass


class TemporaryApiError(YouTubeApiError):
    pass


def _reasons(body: dict) -> tuple[set[str], dict]:
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    reasons = {str(item.get("reason")) for item in error.get("errors") or [] if isinstance(item, dict)}
    metadata: dict = {}
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            reasons.add(str(detail["reason"]))
            metadata.update(detail.get("metadata") or {})
    return reasons, metadata


def _error(response: requests.Response) -> YouTubeApiError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    reasons, metadata = _reasons(body if isinstance(body, dict) else {})
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "RATE_LIMIT_EXCEEDED"}:
        quota.mark_exhausted()
        return QuotaExceededError("Google says today's YouTube API quota is used up")
    if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
        return ApiNotEnabledError(metadata.get("activationUrl"))
    if reasons & {"keyInvalid", "API_KEY_INVALID", "keyExpired", "API_KEY_EXPIRED"}:
        return ApiKeyError("Google does not accept this API key. Check that you copied the whole key, or create a new one.")
    if reasons & {
        "API_KEY_SERVICE_BLOCKED", "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED",
        "API_KEY_ANDROID_APP_BLOCKED", "API_KEY_IOS_APP_BLOCKED", "ipRefererBlocked", "forbidden",
    } and response.status_code == 403:
        return ApiKeyError(
            "This key is restricted in a way that keeps VODLoft out. Restrict it to the YouTube Data API v3 only, "
            "without website, IP address or app restrictions.",
        )
    if response.status_code == 404 or reasons & {"channelNotFound", "playlistNotFound", "videoNotFound", "notFound"}:
        return NotFoundError("YouTube does not know this channel, playlist or video")
    if response.status_code >= 500 or response.status_code == 429:
        return TemporaryApiError(f"The YouTube API is not answering right now (HTTP {response.status_code})")
    message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
    return YouTubeApiError(str(message or f"The YouTube API answered HTTP {response.status_code}"))


class YouTubeApiClient:
    def __init__(self, api_key: str, *, stored: bool = True, session: requests.Session | None = None):
        """``stored`` is False for a key that is only being tested, whose problems are not the stored key's."""
        self._key = api_key
        self._stored = stored
        self._session = session or requests.Session()

    def _get(self, endpoint: str, params: dict, *, share: Share, units: int = 1, force: bool = False) -> dict:
        last_error: YouTubeApiError | None = None
        for attempt in range(len(_RETRY_PAUSES_SECONDS) + 1):
            if not quota.try_spend(share, units, force=force):
                raise QuotaExceededError(f"The YouTube API {share.value} share of today's quota is used up")
            try:
                response = self._session.get(
                    f"{API_URL}/{endpoint}", params=params, headers={"X-Goog-Api-Key": self._key},
                    timeout=_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_error = TemporaryApiError(key_store.redact(f"Could not reach the YouTube API: {exc}", self._key))
            else:
                if response.ok:
                    if self._stored and key_store.problem() is not None:
                        key_store.clear_problem()
                    return response.json()
                last_error = _error(response)
                if self._stored and isinstance(last_error, ApiKeyError):
                    key_store.record_problem(str(last_error), last_error.fix_url)
                if not isinstance(last_error, TemporaryApiError):
                    raise last_error
            if attempt < len(_RETRY_PAUSES_SECONDS):
                logger.info("Retrying YouTube API %s: %s", endpoint, last_error)
                pacing.pause(_RETRY_PAUSES_SECONDS[attempt])
        assert last_error is not None
        raise last_error

    def test(self) -> None:
        """One small call that shows whether Google accepts the key. It always runs, whatever the shares say."""
        self._get("channels", {"part": "id", "id": _TEST_CHANNEL_ID}, share=Share.RESERVE, force=True)

    def channels(self, *, share: Share, ids: Iterable[str] = (), handle: str | None = None,
                 username: str | None = None, part: str = "snippet,contentDetails,statistics,brandingSettings") -> list[dict]:
        params: dict = {"part": part, "maxResults": MAX_RESULTS}
        if handle:
            params["forHandle"] = handle
        elif username:
            params["forUsername"] = username
        else:
            params["id"] = ",".join(ids)
        return self._get("channels", params, share=share).get("items") or []

    def playlists(self, ids: Iterable[str], *, share: Share) -> list[dict]:
        params = {"part": "snippet,contentDetails", "id": ",".join(ids), "maxResults": MAX_RESULTS}
        return self._get("playlists", params, share=share).get("items") or []

    def playlist_items(self, playlist_id: str, *, share: Share, page_token: str | None = None) -> dict:
        """One page of a playlist: its ``items`` and the ``nextPageToken`` when there are more."""
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": MAX_RESULTS}
        if page_token:
            params["pageToken"] = page_token
        return self._get("playlistItems", params, share=share)

    def videos(self, ids: Iterable[str], *, share: Share) -> list[dict]:
        """Up to 50 videos. A private or deleted video is missing from the answer."""
        params = {
            "part": "snippet,contentDetails,liveStreamingDetails,status", "id": ",".join(ids),
            "maxResults": MAX_RESULTS,
        }
        return self._get("videos", params, share=share).get("items") or []

    def search(self, query: str, *, share: Share = Share.SEARCH) -> list[dict]:
        params = {"part": "snippet", "q": query, "type": "channel,playlist,video", "maxResults": MAX_RESULTS}
        return self._get("search", params, share=share, units=100).get("items") or []
