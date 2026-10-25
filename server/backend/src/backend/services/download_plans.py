"""Translate application policy and domain facts into an immutable library plan.

The downloader owns all transfer, optional processing, publication and cleanup.
This adapter alone knows Local Media Profiles, output templates and ORM models.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.models import Episode, Movie, MovieExtra, Video
from backend.db.models.media_download import MediaDownloadBase
from backend.services.download_metadata import build_episode_metadata, build_movie_metadata, build_video_metadata, select_thumbnail_url
from backend.services.download_options import effective_download_mode, effective_metadata_mode, effective_thumbnail_mode
from backend.services.movies import update_movie_extra_source_metadata
from backend.types.dailywire_user_info import WlDwMembershipLevel
from backend.types.local_media_profile_types import LocalMediaProfileType, PreferredFormat
from backend.utils.output_template import resolve_episode_output_path, resolve_movie_output_path, resolve_video_output_path
from config import get_settings
from config.network import is_no_internet_error
from config.settings.submodels import MetadataMode, ThumbnailMode
from downloader import DownloadCancelled, DownloadError, MediaUnavailableError
from downloader.lifecycle import DownloadTracker
from downloader.metadata import render_nfo
from downloader.plan import DownloadPlan, SidecarSpec, build_download_plan
from downloader.source import resolve_download_source
from downloader.ytdlp import resolve_ytdlp_source
from sources import Feature, PlaybackKind, get_source


def prepare_download_plan(session: Session, media_download_id: int, tracker: DownloadTracker) -> DownloadPlan:
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise DownloadCancelled("The download was deleted before preparation")
    media = download.media
    profile = download.local_media_profile
    episode = media if isinstance(media, Episode) else None
    movie = media if isinstance(media, Movie) else media.movie if isinstance(media, MovieExtra) else None
    video = media if isinstance(media, Video) else None
    is_extra = isinstance(media, MovieExtra)
    if episode is None and movie is None and video is None:
        raise DownloadError("Unsupported media type")
    expected_type = (
        LocalMediaProfileType.SHOW.value if episode is not None
        else LocalMediaProfileType.VIDEO.value if video is not None
        else LocalMediaProfileType.MOVIE.value
    )
    if profile.type != expected_type:
        raise DownloadError("The Local Media Profile does not match the media type")
    preferred = profile.preferred_format
    audio_only = preferred == PreferredFormat.FORMAT_AUDIO_ONLY.value
    if movie is not None and preferred in (PreferredFormat.FORMAT_AUDIO_ONLY.value, PreferredFormat.FORMAT_HLS.value):
        raise DownloadError("Movies and extras require a normal video Local Media Profile")
    if video is not None and preferred == PreferredFormat.FORMAT_HLS.value:
        raise DownloadError("Videos cannot be kept as an HLS bundle")

    # Snapshot configuration before network I/O; later setting edits apply only
    # to later attempts. ORM reads are released before every remote call.
    settings = get_settings().download_settings
    download_mode = effective_download_mode(profile).value
    thumbnail_mode = effective_thumbnail_mode(profile)
    metadata_mode = effective_metadata_mode(profile)
    remux, ffmpeg_path, temporary_root = settings.remux_video_to_mp4, settings.ffmpeg_path, str(settings.temporary_download_root)
    output_template = profile.output_template
    title, slug, media_id = media.title, media.slug, media.id
    thumbnail_url = select_thumbnail_url(media)
    media_source = get_source(media.source_key)
    if (episode is not None and media_source.has(Feature.EPISODE_LISTS)) or video is not None:
        # A listed episode is a video on a page, just like a single video.
        page_url = media.sharing_url
        session.rollback()
        tracker.preparing("resolve_playback")
        playback = media_source.video_playback(slug=slug, url=page_url)
        tracker.ensure_active()
        if playback.kind is PlaybackKind.YTDLP:
            source = resolve_ytdlp_source(playback.url, command=playback.command, preferred_format=preferred, audio_only=audio_only, ffmpeg_path=ffmpeg_path)
        else:
            tracker.preparing("inspect_stream")
            source = resolve_download_source(playback.url, preferred_format=preferred, audio_only=audio_only, remux_video_to_mp4=remux, cancellation=tracker.is_canceled)
    elif episode is not None:
        video_url, audio_url = episode.video_url, episode.audio_url
        member_only = episode.show.membership_level != WlDwMembershipLevel.FREE.value
        session.rollback()
        refreshed = False
        while True:
            tracker.ensure_active()
            video_fallback_for_audio = audio_only and not audio_url and bool(video_url)
            url = audio_url if audio_only and audio_url else video_url
            if not url:
                if refreshed:
                    media_kind = (
                        "media" if not audio_url and not video_url
                        else "audio" if audio_only
                        else "video"
                    )
                    raise MediaUnavailableError(
                        f"{media_source.name} provides no playable {media_kind} for '{title}'"
                    )
                tracker.preparing("resolve_playback")
                detail = media_source.episode_media(slug=slug, members_only=member_only)
                tracker.ensure_active()
                current = session.get(Episode, media_id)
                if current is None:
                    raise DownloadCancelled("Episode was deleted during preparation")
                video_url, audio_url = detail.video_url, detail.audio_url
                current.video_url, current.audio_url = video_url, audio_url
                session.commit()
                refreshed = True
                continue
            tracker.preparing("inspect_stream")
            try:
                source = resolve_download_source(
                    url,
                    preferred_format=preferred,
                    audio_only=audio_only,
                    remux_video_to_mp4=remux,
                    video_fallback_for_audio=video_fallback_for_audio,
                    cancellation=tracker.is_canceled,
                )
                break
            except MediaUnavailableError as exc:
                if is_no_internet_error(exc):
                    raise
                if refreshed:
                    media_kind = (
                        "media" if not audio_url and not video_url
                        else "audio" if audio_only
                        else "video"
                    )
                    raise MediaUnavailableError(
                        f"{media_source.name} provides no playable {media_kind} for '{title}'"
                    ) from exc
                # A stored URL can go stale. Refresh both candidates once, which
                # also gives an audio request a chance to switch between the
                # direct audio source and the video fallback.
                video_url = audio_url = None
    else:
        assert movie is not None
        movie_slug, duration = movie.slug, movie.duration
        is_official_trailer = is_extra and movie.official_trailer_id == media_id
        session.rollback()
        tracker.preparing("resolve_playback")
        playback = media_source.movie_playback(
            movie_slug=movie_slug, title=title, duration=duration,
            is_extra=is_extra, extra_slug=slug if is_extra else None,
            is_official_trailer=is_official_trailer,
        )
        tracker.ensure_active()
        if playback.metadata is not None and is_extra:
            current = session.get(MovieExtra, media_id)
            if current is None:
                raise DownloadCancelled("Movie extra was deleted during preparation")
            update_movie_extra_source_metadata(current.source, playback.metadata)
            if playback.metadata.model_fields_set & {"thumbnail_landscape_path", "thumbnail_portrait_path", "thumbnail_square_path", "background_image_path"}:
                thumbnail_url = select_thumbnail_url(playback.metadata)
            session.commit()
        tracker.preparing("inspect_stream")
        source = resolve_download_source(playback.url, preferred_format=preferred, audio_only=False, remux_video_to_mp4=remux, cancellation=tracker.is_canceled)

    tracker.ensure_active()
    tracker.preparing("plan_outputs")
    session.expire_all()
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise DownloadCancelled("Download was deleted while preparing output paths")
    media = download.media
    if isinstance(media, Episode):
        destination = resolve_episode_output_path(output_template, episode=media, local_media_profile=download.local_media_profile, media_download=download, extension=source.extension)
        metadata = build_episode_metadata(media, media.show)
    elif isinstance(media, Video):
        destination = resolve_video_output_path(output_template, video=media, extension=source.extension)
        metadata = build_video_metadata(media, source_name=media_source.name)
    else:
        movie = media.movie if isinstance(media, MovieExtra) else media
        destination = resolve_movie_output_path(output_template, movie=movie, media_item=media, extension=source.extension)
        metadata = build_movie_metadata(movie, media)
    session.rollback()

    assets: list[SidecarSpec] = []
    artwork_id = None
    if thumbnail_url and thumbnail_mode is not ThumbnailMode.NO_THUMBNAIL:
        publish_artwork = thumbnail_mode in (ThumbnailMode.SIDECAR, ThumbnailMode.EMBED_AND_SIDECAR)
        embed_artwork = thumbnail_mode in (ThumbnailMode.EMBED, ThumbnailMode.EMBED_AND_SIDECAR) and not source.hls_bundle
        if publish_artwork or embed_artwork:
            assets.append(SidecarSpec("artwork", "thumbnail", url=thumbnail_url, extension="jpg", publish=publish_artwork, allowed_extensions=("jpg", "jpeg", "png", "webp")))
        if embed_artwork:
            artwork_id = "artwork"
    tags = ()
    if metadata_mode in (MetadataMode.EMBED, MetadataMode.EMBED_AND_NFO) and not source.hls_bundle:
        tags = tuple(metadata.ffmpeg_tags().items())
    if metadata_mode in (MetadataMode.NFO, MetadataMode.EMBED_AND_NFO):
        assets.append(SidecarSpec("nfo", "nfo", content=render_nfo(metadata), extension="nfo", target_suffix=".nfo"))
    return build_download_plan(
        source=source, requested_destination=destination, download_mode=download_mode,
        temporary_root=temporary_root, ffmpeg_path=ffmpeg_path, assets=tuple(assets),
        metadata_tags=tags, artwork_asset_id=artwork_id, attempt_id=tracker.attempt_id,
    )
