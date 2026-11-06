from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from backend.services.video_cache import VideoCacheError, get_cached_mp4_path, prepare_cached_mp4
from .source_stream import episode_stream, proxy_response
from .source_live import live_audio_response, live_master_response, live_part_response, live_playlist_response
from .source_tracks import (
    EpisodeRef,
    join_in_background,
    joined_mp4,
    joined_mp4_response,
    joins_mp4,
    master_playlist_response,
    note_file_streamed,
    stream_height,
    track_part_response,
    track_playlist_response,
    track_redirect_response,
)
from .service import (
    can_stream_from_source,
    get_source_stream_url,
    get_episode_for_feed,
    get_local_download_for_episode,
    get_rss_stream_profile_by_token,
    remember_live_episode_handoff,
    render_rss_feed,
)
from backend.app import db_session
from backend.types.episode_types import EpisodePublishStatus
from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS, PreferredFormat
from backend.types.stream_profile_types import (
    RSS_AUDIO_PRIMARY_OUTPUT_MODES,
    RSS_HLS_OUTPUT_MODES,
    RSS_MP4_OUTPUT_MODES,
)
from backend.services.collection_cookies import uses_cookies
from backend.services.sites import collection_site
from downloader import hls_asset_root
from sources import Feature, StreamMethod, get_source
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


router = APIRouter(prefix="/feeds", tags=["Feeds"])

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _temporary_stream_redirect(url: str, *, head_only: bool = False) -> Response:
    headers = {"Location": url, **_NO_CACHE_HEADERS}
    if head_only:
        return Response(status_code=302, headers=headers)
    return RedirectResponse(url, status_code=302, headers=_NO_CACHE_HEADERS)


def _rss_response(xml: bytes, *, head_only: bool = False) -> Response:
    return Response(
        content=b"" if head_only else xml,
        media_type="application/rss+xml; charset=utf-8",
        headers={
            **_NO_CACHE_HEADERS,
            "Content-Length": str(len(xml)),
        },
    )


def _cached_mp4_head_response(file_path: Path | None, *, filename: str) -> Response:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
        **_NO_CACHE_HEADERS,
    }
    if file_path is not None:
        headers["Content-Length"] = str(file_path.stat().st_size)

    response = Response(content=b"", media_type="video/mp4", headers=headers)
    if file_path is None and "content-length" in response.headers:
        # Response adds Content-Length: 0 for the empty body; an uncached file has no known size.
        del response.headers["content-length"]
    return response


def _episode_ref(episode) -> EpisodeRef:
    return EpisodeRef(uuid=episode.uuid, url=episode.sharing_url, use_cookies=uses_cookies(episode.collection))


def _profile_stream_height(profile, site) -> int | None:
    return stream_height(site, PREFERRED_FORMAT_HEIGHTS.get(profile.preferred_format))


def _site_video_mp4(source, profile, episode, request: Request) -> Response:
    """The episode's MP4 from a Site whose episodes are listed, such as YouTube: joined from its tracks
    when the feed's resolution needs that and it is ready, and otherwise the Site's own MP4 with sound."""
    site = collection_site(profile.collection)
    height = _profile_stream_height(profile, site)
    head_only = request.method == "HEAD"
    filename = f"{episode.slug}.mp4"
    if joins_mp4(site, height):
        joined = joined_mp4(episode.uuid, height)
        if joined is not None:
            return joined_mp4_response(joined, filename=filename)
        join_in_background(source, _episode_ref(episode), height)
        note_file_streamed(episode.uuid)
    if profile.proxy_source_stream or not site.stream_proxy_choice:
        return proxy_response(
            source, episode, audio=False, media_type="video/mp4", filename=filename,
            range_header=request.headers.get("range"), head_only=head_only,
        )
    stream = episode_stream(source, episode, audio=False)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"No {source.name} video stream for this episode")
    return _temporary_stream_redirect(stream.url, head_only=head_only)


def _not_streamed(profile, media: str) -> HTTPException:
    site = collection_site(profile.collection)
    reason = "this feed does not stream episodes" if site.streams else f"{site.name} cannot stream episodes"
    return HTTPException(status_code=404, detail=f"No local {media} is available and {reason}")


def _commit_feed_state_if_changed(s) -> None:
    if s.dirty:
        s.commit()


def _resolved_download_path(s, download) -> Path | None:
    if download is None:
        return None
    return resolve_media_download_file(
        s,
        download,
        release_read_transaction=True,
    )


@router.api_route("/rss/{token}/{collection_slug}.xml", methods=["GET", "HEAD"])
def rss_feed(token: str, collection_slug: str, request: Request):
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        xml = render_rss_feed(s, request, profile)
        _commit_feed_state_if_changed(s)
    return _rss_response(xml, head_only=request.method == "HEAD")


@router.api_route("/rss/{token}/episodes/{episode_slug}", methods=["GET", "HEAD"])
def rss_feed_episode_media(token: str, episode_slug: str, request: Request):
    """Keep previously published generic media URLs usable after the stable split."""
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        get_episode_for_feed(s, profile, episode_slug)
        _commit_feed_state_if_changed(s)
        audio_primary = (
            profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
            or profile.video_output_mode in RSS_AUDIO_PRIMARY_OUTPUT_MODES
        )

    suffix = "audio.m4a" if audio_primary else "video.mp4"
    target = f"{str(request.url).rstrip('/')}/{suffix}"
    headers = {"Location": target, **_NO_CACHE_HEADERS}
    if request.method == "HEAD":
        return Response(status_code=307, headers=headers)
    return RedirectResponse(target, status_code=307, headers=_NO_CACHE_HEADERS)


@router.api_route(
    "/rss/{token}/episodes/{episode_slug}/audio.m4a",
    methods=["GET", "HEAD"],
)
def rss_feed_episode_audio(token: str, episode_slug: str, request: Request):
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        episode = get_episode_for_feed(s, profile, episode_slug)
        _commit_feed_state_if_changed(s)

        download = get_local_download_for_episode(
            s,
            profile,
            episode,
            kind="audio",
        )
        file_path = _resolved_download_path(s, download)
        if file_path is not None:
            return FileResponse(
                file_path,
                filename=file_path.name,
                content_disposition_type="inline",
                media_type="audio/mp4",
                headers=_NO_CACHE_HEADERS,
            )

        if not can_stream_from_source(profile, episode):
            raise _not_streamed(profile, "audio")

        source = get_source(episode.source_key)
        if source.has(Feature.PAGE_STREAMS) and episode.publish_status == EpisodePublishStatus.LIVE.value:
            return live_audio_response(source, _episode_ref(episode), head_only=request.method == "HEAD")
        if source.has(Feature.PAGE_STREAMS):
            return proxy_response(
                source, episode, audio=True, media_type="audio/mp4", filename=f"{episode.slug}.m4a",
                range_header=request.headers.get("range"), head_only=request.method == "HEAD",
            )

        return _temporary_stream_redirect(
            get_source_stream_url(
                profile,
                episode,
                media_kind="audio",
            ),
            head_only=request.method == "HEAD",
        )


@router.api_route(
    "/rss/{token}/episodes/{episode_slug}/video.mp4",
    methods=["GET", "HEAD"],
)
def rss_feed_episode_video_mp4(token: str, episode_slug: str, request: Request):
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        if (
            profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
            or profile.video_output_mode not in RSS_MP4_OUTPUT_MODES
        ):
            raise HTTPException(status_code=404, detail="MP4 video is not enabled for this feed")

        episode = get_episode_for_feed(s, profile, episode_slug)
        _commit_feed_state_if_changed(s)
        if episode.publish_status == EpisodePublishStatus.LIVE.value:
            raise HTTPException(
                status_code=404,
                detail="Live video is available through the HLS enclosure only",
            )
        download = get_local_download_for_episode(
            s,
            profile,
            episode,
            kind="mp4",
        )
        file_path = _resolved_download_path(s, download)
        if file_path is not None and file_path.suffix.lower() == ".mp4":
            return FileResponse(
                file_path,
                filename=file_path.name,
                content_disposition_type="inline",
                media_type="video/mp4",
                headers=_NO_CACHE_HEADERS,
            )

        if not can_stream_from_source(profile, episode):
            raise _not_streamed(profile, "MP4 video")

        source = get_source(episode.source_key)
        if source.has(Feature.PAGE_STREAMS):
            return _site_video_mp4(source, profile, episode, request)

        episode_uuid = episode.uuid
        filename = f"{episode.slug}.mp4"
        cached_file = get_cached_mp4_path(episode_uuid)
        if request.method == "HEAD":
            return _cached_mp4_head_response(cached_file, filename=filename)

        if cached_file is None:
            source_url = get_source_stream_url(
                profile,
                episode,
                media_kind="video",
            )

    if cached_file is None:
        try:
            cached_file = prepare_cached_mp4(source_url, episode_uuid=episode_uuid)
        except VideoCacheError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    else:
        try:
            cached_file.touch()
        except OSError:
            pass

    return FileResponse(
        cached_file,
        filename=filename,
        content_disposition_type="inline",
        media_type="video/mp4",
        headers=_NO_CACHE_HEADERS,
    )


@router.api_route(
    "/rss/{token}/episodes/{episode_slug}/video.m3u8",
    methods=["GET", "HEAD"],
)
def rss_feed_episode_video_hls(token: str, episode_slug: str, request: Request):
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        if (
            profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
            or profile.video_output_mode not in RSS_HLS_OUTPUT_MODES
        ):
            raise HTTPException(status_code=404, detail="HLS video is not enabled for this feed")

        episode = get_episode_for_feed(s, profile, episode_slug)
        _commit_feed_state_if_changed(s)
        download = get_local_download_for_episode(
            s,
            profile,
            episode,
            kind="hls",
        )
        file_path = _resolved_download_path(s, download)
        if file_path is not None and file_path.suffix.lower() == ".m3u8":
            return FileResponse(
                file_path,
                filename="video.m3u8",
                content_disposition_type="inline",
                media_type="application/x-mpegURL",
                headers=_NO_CACHE_HEADERS,
            )

        if not can_stream_from_source(profile, episode):
            raise _not_streamed(profile, "HLS video")
        site = collection_site(profile.collection)
        if StreamMethod.HLS not in site.stream_methods:
            raise HTTPException(status_code=404, detail=f"{site.name} cannot stream episodes as HLS")
        source = get_source(episode.source_key)
        if source.has(Feature.PAGE_STREAMS) and episode.publish_status == EpisodePublishStatus.LIVE.value:
            if request.method != "HEAD":
                remember_live_episode_handoff(profile, episode)
                _commit_feed_state_if_changed(s)
            return live_master_response(
                source, _episode_ref(episode), height=_profile_stream_height(profile, site) or 0,
                head_only=request.method == "HEAD",
            )
        if source.has(Feature.PAGE_STREAMS):
            return master_playlist_response(
                source, _episode_ref(episode), height=_profile_stream_height(profile, site) or 0,
                head_only=request.method == "HEAD",
            )

        source_url = get_source_stream_url(
            profile,
            episode,
            media_kind="video",
        )
        if request.method != "HEAD":
            remember_live_episode_handoff(profile, episode)
            _commit_feed_state_if_changed(s)

    return _temporary_stream_redirect(
        source_url,
        head_only=request.method == "HEAD",
    )


@router.api_route(
    "/rss/{token}/episodes/{episode_slug}/live/{name}",
    methods=["GET", "HEAD"],
)
def rss_feed_episode_live(token: str, episode_slug: str, name: str, request: Request, u: str | None = None, s: str | None = None):
    """One of the live playlists of an episode of a Site whose episodes are listed, or a part of it,
    passed on for a feed that proxies its Site's video."""
    with db_session() as session:
        profile = get_rss_stream_profile_by_token(session, token)
        if (
            profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
            or profile.video_output_mode not in RSS_HLS_OUTPUT_MODES
        ):
            raise HTTPException(status_code=404, detail="HLS video is not enabled for this feed")
        episode = get_episode_for_feed(session, profile, episode_slug)
        _commit_feed_state_if_changed(session)
        if not can_stream_from_source(profile, episode):
            raise _not_streamed(profile, "live video")
        source = get_source(episode.source_key)
        if not source.has(Feature.PAGE_STREAMS):
            raise HTTPException(status_code=404, detail="No such playlist")
        site = collection_site(profile.collection)
        proxy = profile.proxy_source_stream or not site.stream_proxy_choice
        episode_ref = _episode_ref(episode)

    head_only = request.method == "HEAD"
    if name == "part":
        if not proxy or u is None or s is None:
            raise HTTPException(status_code=404, detail="No such part")
        return live_part_response(u, s, range_header=request.headers.get("range"), head_only=head_only)
    return live_playlist_response(source, episode_ref, name, part_base="part" if proxy else None, head_only=head_only)


@router.api_route(
    "/rss/{token}/episodes/{episode_slug}/tracks/{name}",
    methods=["GET", "HEAD"],
)
def rss_feed_episode_track(token: str, episode_slug: str, name: str, request: Request):
    """A playlist of one of the video or audio tracks of a Site's HLS stream that VODLoft writes, or
    that track's bytes: passed on for a feed that proxies its Site's video, and otherwise a redirect
    to the Site with a fresh link."""
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        if (
            profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
            or profile.video_output_mode not in RSS_HLS_OUTPUT_MODES
        ):
            raise HTTPException(status_code=404, detail="HLS video is not enabled for this feed")
        episode = get_episode_for_feed(s, profile, episode_slug)
        _commit_feed_state_if_changed(s)
        if not can_stream_from_source(profile, episode):
            raise _not_streamed(profile, "HLS video")
        source = get_source(episode.source_key)
        if not source.has(Feature.PAGE_STREAMS):
            raise HTTPException(status_code=404, detail="No such track")
        site = collection_site(profile.collection)
        proxy = profile.proxy_source_stream or not site.stream_proxy_choice
        episode_ref = _episode_ref(episode)

    head_only = request.method == "HEAD"
    if name.endswith(".m3u8"):
        return track_playlist_response(source, episode_ref, name, head_only=head_only)
    if not proxy:
        return track_redirect_response(source, episode_ref, name, head_only=head_only)
    return track_part_response(source, episode_ref, name, range_header=request.headers.get("range"), head_only=head_only)


@router.api_route(
    "/rss/{token}/episodes/{episode_slug}/hls/{asset_path:path}",
    methods=["GET", "HEAD"],
)
def rss_feed_episode_hls_asset(
    token: str,
    episode_slug: str,
    asset_path: str,
):
    with db_session() as s:
        profile = get_rss_stream_profile_by_token(s, token)
        if profile.video_output_mode not in RSS_HLS_OUTPUT_MODES:
            raise HTTPException(status_code=404, detail="HLS video is not enabled for this feed")

        episode = get_episode_for_feed(s, profile, episode_slug)
        _commit_feed_state_if_changed(s)
        download = get_local_download_for_episode(
            s,
            profile,
            episode,
            kind="hls",
        )
        master_path = _resolved_download_path(s, download)
        if master_path is None:
            raise HTTPException(status_code=404, detail="Local HLS video is not available")

        root = hls_asset_root(master_path).resolve()
        candidate = (root / asset_path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="HLS asset not found")

    media_type = mimetypes.guess_type(candidate.name)[0]
    if candidate.suffix.lower() == ".m3u8":
        media_type = "application/x-mpegURL"
    elif candidate.suffix.lower() == ".ts":
        media_type = "video/mp2t"

    return FileResponse(
        candidate,
        filename=candidate.name,
        content_disposition_type="inline",
        media_type=media_type,
    )
