"""Translate application policy and domain facts into an immutable library plan.

The downloader owns all transfer, optional processing, publication and cleanup.
This adapter alone knows Local Media Profiles, output templates and ORM models.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.services.collection_cookies import uses_cookies
from backend.services.playback import resolve_playback
from backend.services.local_media_profile_sites import format_for_site
from backend.services.sites import collection_site, video_site
from backend.services.no_ascii_names import settle_no_ascii_name
from backend.services.media_access import link_access
from backend.db.core import run_write_transaction
from backend.db.models import DownloadProfile, Episode, Movie, MovieExtra, Video
from backend.db.models.media_download import MediaDownloadBase
from backend.services.download_metadata import build_episode_metadata, build_movie_metadata, build_video_metadata, select_thumbnail
from backend.services.download_options import effective_download_mode, effective_metadata_mode, effective_thumbnail_mode
from backend.services.download_quality import (
    chosen_subtitle_tracks, custom_ytdlp_options, default_subtitle_languages, ytdlp_quality, ytdlp_sponsorblock, ytdlp_subtitles,
)
from backend.types.download_profile_types import AutoSubtitles
from backend.services.source_options import ytdlp_source_options
from backend.services.movies import update_movie_extra_source_metadata
from backend.types.dailywire_user_info import DwMembershipLevel
from backend.types.local_media_profile_types import LocalMediaProfileSubtitleMode, LocalMediaProfileType, PreferredFormat
from backend.utils.output_template import resolve_episode_output_path, resolve_movie_output_path, resolve_video_output_path
from config import get_settings
from config.network import is_no_internet_error
from config.settings.submodels import MetadataMode, ThumbnailMode
from downloader import (
    AccessRequiredError, DownloadCanceled, DownloadError, MediaUnavailableError,
)
from downloader.lifecycle import DownloadTracker
from downloader.metadata import render_nfo
from downloader.plan import DownloadPlan, SidecarSpec, YtdlpSponsorBlock, build_download_plan
from downloader.source import resolve_download_source
from downloader.ytdlp import resolve_ytdlp_source
from sources import Feature, PlaybackKind, SiteSetting, Source, get_source

logger = logging.getLogger(__name__)


def prepare_download_plan(session: Session, media_download_id: int, tracker: DownloadTracker) -> DownloadPlan:
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise DownloadCanceled("The download was deleted before preparation")
    media = download.media
    profile = download.local_media_profile
    episode = media if isinstance(media, Episode) else None
    movie = media if isinstance(media, Movie) else media.movie if isinstance(media, MovieExtra) else None
    video = media if isinstance(media, Video) else None
    is_extra = isinstance(media, MovieExtra)
    if episode is None and movie is None and video is None:
        raise DownloadError("Unsupported media type")
    expected_type = (
        LocalMediaProfileType.COLLECTION.value if episode is not None
        else LocalMediaProfileType.VIDEO.value if video is not None
        else LocalMediaProfileType.MOVIE.value
    )
    if profile.type != expected_type:
        raise DownloadError("The Local Media Profile does not match the media type")
    preferred = profile.preferred_format
    media_site = None
    if episode is not None or video is not None:
        media_site = collection_site(episode.collection) if episode is not None else video_site(video)
        # The profile may be offered for Sites that cannot give what it chose, such as an HLS bundle.
        preferred = format_for_site(media_site, preferred)
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
    subtitle_mode = LocalMediaProfileSubtitleMode(profile.subtitle_mode)
    quality = ytdlp_quality(profile)
    download_profile = _download_profile(download, episode)
    auto_subtitles = AutoSubtitles(download_profile.auto_subtitles) if download_profile is not None else (
        AutoSubtitles.FALLBACK if episode is not None else AutoSubtitles.NEVER
    )
    sponsorblock = ytdlp_sponsorblock(
        download_profile.sponsorblock_enabled, dict(download_profile.sponsorblock_segments),
    ) if download_profile is not None else YtdlpSponsorBlock()
    option_texts = [("the yt-dlp Source", ytdlp_source_options(session))]
    if episode is not None:
        option_texts.append((f"the Collection '{episode.collection.title}'", episode.collection.ytdlp_options))
    subtitle_request = ytdlp_subtitles(profile, AutoSubtitles.NEVER)
    default_languages = default_subtitle_languages(profile)
    remux, ffmpeg_path, temporary_root = settings.remux_video_to_mp4, settings.ffmpeg_path, str(settings.temporary_download_root)
    output_template = profile.output_template
    title, slug, media_id = media.title, media.slug, media.id
    thumbnail = select_thumbnail(media)
    media_source = get_source(media.source_key)
    if (episode is not None and media_source.has(Feature.EPISODE_LISTS)) or video is not None:
        # A listed episode is a video on a page, just like a single video.
        page_url = media.sharing_url
        use_cookies = None
        if episode is not None and media_source.has(Feature.OPTIONAL_COOKIES):
            use_cookies = uses_cookies(episode.collection)
        session.rollback()
        playback = resolve_playback(
            media_source, slug=slug, url=page_url, title=title, tracker=tracker, use_cookies=use_cookies,
        )
        if playback.kind is PlaybackKind.YTDLP:
            if media_site.settings.offers(SiteSetting.AUTO_SUBTITLES):
                subtitle_request = ytdlp_subtitles(profile, auto_subtitles)
            source = resolve_ytdlp_source(
                playback.url, command=playback.command, preferred_format=preferred, audio_only=audio_only,
                quality=quality, subtitles=subtitle_request,
                sponsorblock=sponsorblock if media_site.settings.offers(SiteSetting.SPONSORBLOCK) else YtdlpSponsorBlock(),
                custom_options=custom_ytdlp_options(*option_texts) if media_source.has(Feature.YTDLP_OPTIONS) else (),
                ffmpeg_path=ffmpeg_path,
            )
        else:
            tracker.preparing("inspect_stream")
            source = resolve_download_source(playback.url, preferred_format=preferred, audio_only=audio_only, remux_video_to_mp4=remux, cancellation=tracker.is_canceled)
    elif episode is not None:
        video_url, audio_url = episode.video_url, episode.audio_url
        member_only = episode.collection.membership_level != DwMembershipLevel.FREE.value
        page_url = episode.sharing_url
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
                    _raise_if_access_required(media_source, slug=slug, url=page_url, title=title)
                    raise MediaUnavailableError(
                        f"{media_source.name} provides no playable {media_kind} for '{title}'"
                    )
                tracker.preparing("resolve_playback")
                detail = media_source.episode_media(slug=slug, members_only=member_only)
                tracker.ensure_active()
                video_url, audio_url = detail.video_url, detail.audio_url
                run_write_transaction(lambda w: _store_episode_media(w, media_id, detail))
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
                    _raise_if_access_required(media_source, slug=slug, url=page_url, title=title)
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
            run_write_transaction(lambda w: _store_movie_extra_metadata(w, media_id, playback.metadata))
            if playback.metadata.model_fields_set & {"thumbnail_landscape_path", "thumbnail_portrait_path", "thumbnail_square_path", "background_image_path"}:
                thumbnail = select_thumbnail(playback.metadata)
        tracker.preparing("inspect_stream")
        source = resolve_download_source(playback.url, preferred_format=preferred, audio_only=False, remux_video_to_mp4=remux, cancellation=tracker.is_canceled)

    tracker.ensure_active()
    tracker.preparing("plan_outputs")
    session.expire_all()
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise DownloadCanceled("Download was deleted while preparing output paths")
    media = download.media
    if isinstance(media, Episode):
        destination = resolve_episode_output_path(output_template, episode=media, local_media_profile=download.local_media_profile, media_download=download, extension=source.extension)
        metadata = build_episode_metadata(media, media.collection)
    elif isinstance(media, Video):
        destination = resolve_video_output_path(output_template, video=media, extension=source.extension)
        metadata = build_video_metadata(media, source_name=media_source.name)
    else:
        movie = media.movie if isinstance(media, MovieExtra) else media
        destination = resolve_movie_output_path(output_template, movie=movie, media_item=media, extension=source.extension)
        metadata = build_movie_metadata(movie, media)
    destination = settle_no_ascii_name(download, destination, session=session)
    session.rollback()

    assets: list[SidecarSpec] = []
    artwork_id = None
    # VODLoft embeds into MP4, M4A, MP3 and MKV; an Opus file only gets sidecars.
    embeddable = not source.hls_bundle and source.extension != "opus"
    if thumbnail is not None and thumbnail_mode is not ThumbnailMode.NO_THUMBNAIL:
        publish_artwork = thumbnail_mode in (ThumbnailMode.SIDECAR, ThumbnailMode.EMBED_AND_SIDECAR)
        embed_artwork = thumbnail_mode in (ThumbnailMode.EMBED, ThumbnailMode.EMBED_AND_SIDECAR) and embeddable
        if publish_artwork or embed_artwork:
            if isinstance(thumbnail, Path):
                # A frame VODLoft took from the video: a JPEG it already has.
                assets.append(SidecarSpec("artwork", "thumbnail", content=thumbnail.read_bytes(), extension="jpg", publish=publish_artwork))
            else:
                assets.append(SidecarSpec("artwork", "thumbnail", url=thumbnail, extension="jpg", publish=publish_artwork, allowed_extensions=("jpg", "jpeg", "png", "webp")))
        if embed_artwork:
            artwork_id = "artwork"
    tags = ()
    if metadata_mode in (MetadataMode.EMBED, MetadataMode.EMBED_AND_NFO) and embeddable:
        tags = tuple(metadata.ffmpeg_tags().items())
    if metadata_mode in (MetadataMode.NFO, MetadataMode.EMBED_AND_NFO):
        assets.append(SidecarSpec("nfo", "nfo", content=render_nfo(metadata), extension="nfo", target_suffix=".nfo"))

    # The source resolver already inspected the HLS master once. Reuse those
    # advertised renditions rather than requesting a second, potentially
    # expiring signed manifest for subtitles.
    publish_subtitles = subtitle_mode in (LocalMediaProfileSubtitleMode.SIDECAR, LocalMediaProfileSubtitleMode.EMBED_AND_SIDECAR)
    embed_subtitles = (
        subtitle_mode in (LocalMediaProfileSubtitleMode.EMBED, LocalMediaProfileSubtitleMode.EMBED_AND_SIDECAR)
        and not source.hls_bundle and not source.audio_only
        and source.extension in {"mp4", "m4v", "mkv"}
    )
    embedded_subtitle_ids: list[str] = []
    if (publish_subtitles or embed_subtitles) and source.ytdlp_command:
        # yt-dlp writes the subtitles itself while it downloads the media.
        assets.append(SidecarSpec(
            "subtitles", "subtitle", url=source.url, extension="srt", source_format="ytdlp",
            publish=publish_subtitles, required=False,
        ))
        if embed_subtitles:
            embedded_subtitle_ids.append("subtitles")
    elif publish_subtitles or embed_subtitles:
        for index, track in enumerate(chosen_subtitle_tracks(subtitle_request, source.subtitles)):
            asset_id = f"subtitle_{index}"
            assets.append(SidecarSpec(
                asset_id, "subtitle", url=track.url, extension="srt",
                source_format="hls_webvtt", language=track.language,
                forced=track.forced, target_suffix=track.target_suffix,
                publish=publish_subtitles, required=False,
            ))
            if embed_subtitles:
                embedded_subtitle_ids.append(asset_id)
    return build_download_plan(
        source=source, requested_destination=destination, download_mode=download_mode,
        temporary_root=temporary_root, ffmpeg_path=ffmpeg_path, assets=tuple(assets),
        metadata_tags=tags, artwork_asset_id=artwork_id,
        subtitle_asset_ids=tuple(embedded_subtitle_ids),
        default_subtitle_languages=default_languages,
        attempt_id=tracker.attempt_id,
        media_lane=(f"source:{media_source.id}", streams) if (streams := media_source.download_streams) else None,
    )


def _raise_if_access_required(source: Source, *, slug: str, url: str, title: str) -> None:
    """A Source that gives no media for an episode may only give it to members: say so, so that the
    episode is locked instead of retried."""
    try:
        access = source.current_access(slug=slug, url=url)
    except Exception:
        logger.info("Could not ask %s which access '%s' needs", source.name, title, exc_info=True)
        return
    if access is not None:
        found = link_access(source.id, url, access)
        label = found.label if found else "an access VODLoft does not have"
        raise AccessRequiredError(f"{source.name} only gives '{title}' with {label}", access)


def _download_profile(download: MediaDownloadBase, episode: Episode | None) -> DownloadProfile | None:
    """The Download Profile behind an episode download, for its YouTube choices.

    An episode downloaded by hand follows the Collection's Download Profile
    that uses the same Local Media Profile; a single video has none.
    """
    if episode is None:
        return None
    return getattr(download, "download_profile", None) or next(
        (candidate for candidate in episode.collection.download_profiles
         if candidate.local_media_profile_id == download.local_media_profile_id),
        None,
    )


def _store_episode_media(session: Session, media_id: int, detail) -> None:
    """Store the media links the Source just gave for an episode."""
    current = session.get(Episode, media_id)
    if current is None:
        raise DownloadCanceled("Episode was deleted during preparation")
    current.video_url, current.audio_url = detail.video_url, detail.audio_url


def _store_movie_extra_metadata(session: Session, media_id: int, metadata) -> None:
    current = session.get(MovieExtra, media_id)
    if current is None:
        raise DownloadCanceled("Movie extra was deleted during preparation")
    update_movie_extra_source_metadata(current.source, metadata)
