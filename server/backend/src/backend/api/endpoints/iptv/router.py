"""The addresses IPTV apps use: a playlist of channels, their programme guide, and what a channel plays now.

Like an RSS feed, they answer without signing in: the secret token in the address is the key.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

from backend.app import db_session
from backend.services.iptv import channel_media_name, channels_for_token, playing_now
from backend.services.stream_episodes import get_stream_profile_by_token
from backend.types.stream_profile_types import StreamProfileType
from backend.utils.feed_urls import request_base_url
from .service import render_guide, render_playlist

router = APIRouter(prefix="/iptv", tags=["IPTV"])

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _response(content: bytes, media_type: str, *, head_only: bool) -> Response:
    return Response(
        content=b"" if head_only else content,
        media_type=media_type,
        headers={**_NO_CACHE_HEADERS, "Content-Length": str(len(content))},
    )


@router.api_route("/{token}/playlist.m3u", methods=["GET", "HEAD"])
def iptv_playlist(token: str, request: Request):
    base_url = request_base_url(request)
    with db_session() as s:
        channels = channels_for_token(s, token)
        playlist = render_playlist(channels, base_url=base_url, guide_url=f"{base_url}/iptv/{token}/guide.xml")
    return _response(playlist.encode(), "audio/x-mpegurl; charset=utf-8", head_only=request.method == "HEAD")


@router.api_route("/{token}/guide.xml", methods=["GET", "HEAD"])
def iptv_guide(token: str, request: Request):
    with db_session() as s:
        guide = render_guide(s, channels_for_token(s, token), datetime.now(timezone.utc))
    return _response(guide, "application/xml; charset=utf-8", head_only=request.method == "HEAD")


@router.api_route("/{token}/channel.m3u8", methods=["GET", "HEAD"])
def iptv_channel(token: str, request: Request):
    """What the channel plays now, as a redirect to that episode's media address."""
    with db_session() as s:
        profile = get_stream_profile_by_token(s, token, StreamProfileType.IPTV)
        programme = playing_now(s, profile, datetime.now(timezone.utc))
        if programme is None:
            raise HTTPException(status_code=404, detail="The channel has no episodes to play")
        media = channel_media_name(s, profile, programme)
        target = f"{request_base_url(request)}/feeds/iptv/{token}/episodes/{programme.episode.slug}/{media}"
    return Response(status_code=302, headers={"Location": target, **_NO_CACHE_HEADERS})
