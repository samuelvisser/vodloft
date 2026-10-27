"""The catalogue questions the yt-dlp Source asks the YouTube Data API.

A channel's videos come from its uploads playlist, 50 IDs a page, and their
details from ``videos.list``, 50 videos a call. Every call is paid from the
first share that still has room, so adding a show uses the units kept free
first and the checks share after that.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from ...contract import ShowDetails
from . import mapping, quota
from .client import MAX_RESULTS, NotFoundError, QuotaExceededError, YouTubeApiClient
from .mapping import YouTubeRef
from .quota import Share

T = TypeVar("T")


class Catalogue:
    def __init__(self, client: YouTubeApiClient, shares: tuple[Share, ...]):
        self._client = client
        self._shares = shares
        self._shorts: dict[str, frozenset[str]] = {}

    def _call(self, call: Callable[[Share], T]) -> T:
        for share in self._shares[:-1]:
            try:
                return call(share)
            except QuotaExceededError:
                if quota.status().exhausted:
                    raise
        return call(self._shares[-1])

    def channel(self, ref: YouTubeRef) -> dict:
        """A channel from its handle, ID or legacy user name."""
        items = self._call(lambda share: self._client.channels(
            share=share, part="snippet",
            handle=ref.value if ref.kind == "handle" else None,
            username=ref.value if ref.kind == "username" else None,
            ids=(ref.value,) if ref.kind == "channel" else (),
        ))
        if not items:
            raise NotFoundError("YouTube does not know this channel")
        return items[0]

    def playlist(self, playlist_id: str) -> dict:
        items = self._call(lambda share: self._client.playlists((playlist_id,), share=share))
        if not items:
            raise NotFoundError("YouTube does not know this playlist")
        return items[0]

    def show(self, ref: YouTubeRef, url: str) -> ShowDetails:
        if ref.kind == "playlist":
            return mapping.playlist_show(self.playlist(ref.value), url)
        return mapping.channel_show(self.channel(ref), url)

    def playlist_id(self, ref: YouTubeRef) -> str:
        """The playlist that lists the show's videos."""
        if ref.kind == "playlist":
            return ref.value
        channel_id = ref.value if ref.kind == "channel" else self.channel(ref)["id"]
        return ref.uploads_playlist(channel_id)

    def video_ids(self, playlist_id: str) -> list[str]:
        """Every video ID in the playlist, in its order, which is newest first for uploads."""
        ids: list[str] = []
        token: str | None = None
        while True:
            page = self._call(lambda share: self._client.playlist_items(playlist_id, share=share, page_token=token))
            ids += [
                item["contentDetails"]["videoId"] for item in page.get("items") or []
                if (item.get("contentDetails") or {}).get("videoId")
            ]
            token = page.get("nextPageToken")
            if not token:
                return list(dict.fromkeys(ids))

    def videos(self, ids: list[str]) -> list[dict]:
        """Details of up to 50 videos. A private or deleted one is missing from the answer."""
        assert len(ids) <= MAX_RESULTS
        return self._call(lambda share: self._client.videos(ids, share=share))

    def short_ids(self, channel_id: str) -> frozenset[str]:
        """The channel's Shorts, from the Shorts playlist YouTube keeps for it."""
        if channel_id not in self._shorts:
            try:
                ids = self.video_ids(YouTubeRef("channel", channel_id, "shorts").uploads_playlist(channel_id))
            except NotFoundError:
                # A channel without Shorts has no Shorts playlist.
                ids = []
            self._shorts[channel_id] = frozenset(ids)
        return self._shorts[channel_id]

    def shorts_among(self, items: Iterable[dict]) -> set[str]:
        """Which of these videos are Shorts. Only channels with a video short enough to be one are asked."""
        shorts: set[str] = set()
        for item in items:
            channel_id = (item.get("snippet") or {}).get("channelId")
            if channel_id and mapping.may_be_short(item) and item["id"] in self.short_ids(channel_id):
                shorts.add(item["id"])
        return shorts
