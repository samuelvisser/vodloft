"""The addresses IPTV apps use: a playlist of channels, their programme guide, what a channel plays now and
played before, and a playlist of every episode on its own.

Like an RSS feed, they answer without signing in: the secret token in the address is the key.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from backend.app import db_session
from backend.db.models import Episode
from backend.services.errors import NotFoundError
from backend.services.iptv import catch_up_programme, channels_for_token, listed_channels, media_name, playing_now
from backend.services.stream_episodes import get_stream_profile_by_token
from backend.types.stream_profile_types import StreamProfileType
from backend.utils.feed_urls import request_base_url
from .service import OFF_AIR_SEGMENT, render_episode_playlist, render_guide, render_off_air, render_playlist

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


def _redirect(target: str) -> Response:
    return Response(status_code=302, headers={"Location": target, **_NO_CACHE_HEADERS})


def _episode_media(request: Request, s, token: str, profile, episode: Episode) -> Response:
    """A redirect to the episode's media address of the channel."""
    media = media_name(s, profile, episode)
    return _redirect(f"{request_base_url(request)}/feeds/iptv/{token}/episodes/{episode.slug}/{media}")


@router.api_route("/off-air.ts", methods=["GET", "HEAD"])
def iptv_off_air_segment():
    return FileResponse(OFF_AIR_SEGMENT, media_type="video/mp2t", headers={"Cache-Control": "public, max-age=86400"})


@router.api_route("/{token}/playlist.m3u", methods=["GET", "HEAD"])
def iptv_playlist(token: str, request: Request):
    base_url = request_base_url(request)
    with db_session() as s:
        channels = listed_channels(s, channels_for_token(s, token), datetime.now(timezone.utc))
        playlist = render_playlist(channels, base_url=base_url, guide_url=f"{base_url}/iptv/{token}/guide.xml")
    return _response(playlist.encode(), "audio/x-mpegurl; charset=utf-8", head_only=request.method == "HEAD")


@router.api_route("/{token}/guide.xml", methods=["GET", "HEAD"])
def iptv_guide(token: str, request: Request):
    now = datetime.now(timezone.utc)
    with db_session() as s:
        guide = render_guide(s, listed_channels(s, channels_for_token(s, token), now), now)
    return _response(guide, "application/xml; charset=utf-8", head_only=request.method == "HEAD")


@router.api_route("/{token}/vod.m3u", methods=["GET", "HEAD"])
def iptv_episode_playlist(token: str, request: Request):
    """Every episode of the channels that list their episodes on their own."""
    with db_session() as s:
        channels = [channel for channel in channels_for_token(s, token) if channel.list_episodes]
        if not channels:
            raise NotFoundError("Episode playlist")
        playlist = render_episode_playlist(s, channels, base_url=request_base_url(request))
    return _response(playlist.encode(), "audio/x-mpegurl; charset=utf-8", head_only=request.method == "HEAD")


@router.api_route("/{token}/channel.m3u8", methods=["GET", "HEAD"])
def iptv_channel(token: str, request: Request):
    """What the channel plays now, as a redirect to that episode's media address or to the off-air screen."""
    with db_session() as s:
        profile = get_stream_profile_by_token(s, token, StreamProfileType.IPTV)
        programme = playing_now(s, profile, datetime.now(timezone.utc))
        if programme is None:
            raise HTTPException(status_code=404, detail="The channel has nothing on now")
        if programme.episode is None:
            return _redirect(f"{request_base_url(request)}/iptv/{token}/off-air.m3u8")
        return _episode_media(request, s, token, profile, programme.episode)


@router.api_route("/{token}/catchup.m3u8", methods=["GET", "HEAD"])
def iptv_catch_up(
    token: str,
    request: Request,
    utc: int = Query(description="The start of the guide slot to play again, in seconds since 1970 (UTC)"),
):
    """The episode the guide had on at ``utc``, as a redirect to its media address."""
    now = datetime.now(timezone.utc)
    with db_session() as s:
        profile = get_stream_profile_by_token(s, token, StreamProfileType.IPTV)
        programme = catch_up_programme(s, profile, datetime.fromtimestamp(utc, timezone.utc), now)
        if programme is None:
            raise HTTPException(status_code=404, detail="The channel had no episode on then that can be played again")
        return _episode_media(request, s, token, profile, programme.episode)


@router.api_route("/{token}/off-air.m3u8", methods=["GET", "HEAD"])
def iptv_off_air(token: str, request: Request):
    """The off-air screen, until the channel has something on again."""
    now = datetime.now(timezone.utc)
    with db_session() as s:
        profile = get_stream_profile_by_token(s, token, StreamProfileType.IPTV)
        programme = playing_now(s, profile, now)
    playlist = render_off_air(
        now,
        segment_url=f"{request_base_url(request)}/iptv/off-air.ts",
        ended=programme is None or programme.episode is not None,
    )
    return _response(
        playlist.encode(), "application/vnd.apple.mpegurl", head_only=request.method == "HEAD",
    )
