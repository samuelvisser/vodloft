"""Which episodes a stream profile offers, and what it plays for each one.

Every stream profile type (an RSS feed or an IPTV channel) picks its episodes the same way: from its collection,
the episode types it lists, its downloads and its Site's stream, live episodes and at most
``max_items`` of them. A type only differs in which media it serves of an episode, its
``media_kinds``, and in how it hands them to an app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.orm import object_session, Session, joinedload

from sources import FREE_LEVEL, HIGHEST_LEVEL
from backend.db.models import DownloadProfile, Episode, LocalMediaProfileBase
from backend.db.models.media_download import EpisodeMediaDownload
from backend.db.models.stream_profile import StreamProfileBase
from backend.db.models.user import User
from backend.services import users
from backend.services.episode_filters import filters_allow_new_episode
from backend.services.errors import NotFoundError, ServiceError
from backend.services.sites import collection_site, with_main_type
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.episode_types import EpisodePublishStatus
from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS, PreferredFormat
from backend.types.stream_profile_types import StreamMediaKind, StreamProfileType
from backend.utils.episode import episode_identifier_type_predicate
from config.network import is_no_internet_error
from sources import Source, StreamMethod, get_source
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file


_AVAILABLE_ARTIFACT_STATUS = MediaDownloadArtifactStatus.AVAILABLE.value
_RECONCILABLE_ARTIFACT_STATUSES = (
    MediaDownloadArtifactStatus.AVAILABLE.value,
    MediaDownloadArtifactStatus.MISSING.value,
    MediaDownloadArtifactStatus.CORRUPTED.value,
)
# Nothing to play yet, such as a YouTube premiere that has not started, or nothing usable.
_UNAVAILABLE_PUBLISH_STATUSES = {
    EpisodePublishStatus.SCHEDULED.value,
    EpisodePublishStatus.DELAYED.value,
    EpisodePublishStatus.SOURCE_PROCESSING.value,
}
_VIDEO_HEIGHTS = {fmt.value: height for fmt, height in PREFERRED_FORMAT_HEIGHTS.items()}


def _not_offered() -> ServiceError:
    return ServiceError("Episode not offered by this stream profile", status_code=404)


def owner_may_stream(s: Session, profile: StreamProfileBase) -> bool:
    """A disabled user's stream profiles stop answering until they are enabled again."""
    if profile.owner_user_id is None:
        return True
    owner = s.get(User, profile.owner_user_id)
    return owner is None or owner.is_enabled


def _owner_may_use_members_only_media(profile: StreamProfileBase) -> bool:
    """A profile streams what its owner may use: without the members-only switch, only what a free account gets."""
    if profile.owner_user_id is None:
        return True
    session = object_session(profile)
    owner = session.get(User, profile.owner_user_id) if session is not None else None
    return owner is None or users.access_of(owner).members_only


def get_stream_profile_by_token(s: Session, token: str, profile_type: StreamProfileType) -> StreamProfileBase:
    """The enabled stream profile of this type that the secret token in its addresses names."""
    item: Optional[StreamProfileBase] = (
        s.query(StreamProfileBase)
        .options(joinedload(StreamProfileBase.collection))
        .filter_by(token=token, type=profile_type.value, enable_profile=True)
        .one_or_none()
    )
    if item is None or not owner_may_stream(s, item):
        raise NotFoundError("Feed")
    return item


def download_kind(download: EpisodeMediaDownload) -> StreamMediaKind:
    """What a download gives a stream profile to serve, by its Local Media Profile's format."""
    preferred = download.local_media_profile.preferred_format
    if preferred == PreferredFormat.FORMAT_AUDIO_ONLY.value:
        return "audio"
    if preferred == PreferredFormat.FORMAT_HLS.value:
        return "hls"
    return "mp4"


def _candidate_downloads(
        downloads: list[EpisodeMediaDownload],
        *,
        kind: StreamMediaKind,
        preferred_format: str,
        prefer_exact_match: bool,
) -> list[EpisodeMediaDownload]:
    candidates = [download for download in downloads if download_kind(download) == kind]
    if not candidates:
        return []

    if kind != "mp4":
        return sorted(
            candidates,
            key=lambda download: download.downloaded_at or download.updated_at,
            reverse=True,
        )

    exact = [
        download
        for download in candidates
        if download.local_media_profile.preferred_format == preferred_format
    ]
    if exact:
        remaining = [download for download in candidates if download not in exact]
        return sorted(
            exact,
            key=lambda download: download.downloaded_at or download.updated_at,
            reverse=True,
        ) + remaining

    if prefer_exact_match and preferred_format in _VIDEO_HEIGHTS:
        return []

    desired_height = _VIDEO_HEIGHTS.get(
        preferred_format,
        _VIDEO_HEIGHTS[PreferredFormat.FORMAT_1080P.value],
    )
    return sorted(
        candidates,
        key=lambda download: (
            abs(
                _VIDEO_HEIGHTS.get(
                    download.local_media_profile.preferred_format,
                    desired_height,
                )
                - desired_height
            ),
            -_VIDEO_HEIGHTS.get(
                download.local_media_profile.preferred_format,
                0,
            ),
        ),
    )


def _select_resolvable_download(
        s: Session,
        downloads: list[EpisodeMediaDownload],
        *,
        kind: StreamMediaKind,
        preferred_format: str,
        prefer_exact_match: bool,
) -> Optional[EpisodeMediaDownload]:
    for candidate in _candidate_downloads(
        downloads,
        kind=kind,
        preferred_format=preferred_format,
        prefer_exact_match=prefer_exact_match,
    ):
        path = resolve_media_download_file(
            s,
            candidate,
            release_read_transaction=True,
        )
        if path is None or candidate.artifact_status != _AVAILABLE_ARTIFACT_STATUS:
            continue
        if kind == "mp4" and path.suffix.lower() != ".mp4":
            continue
        if kind == "hls" and path.suffix.lower() != ".m3u8":
            continue
        return candidate
    return None


def _episode_downloads(
        s: Session,
        profile: StreamProfileBase,
        episode_id: int,
) -> list[EpisodeMediaDownload]:
    if not profile.use_downloads:
        return []
    return (
        s.query(EpisodeMediaDownload)
        .options(joinedload(EpisodeMediaDownload.local_media_profile))
        .filter(EpisodeMediaDownload.media_item_id == episode_id)
        .filter(
            EpisodeMediaDownload.artifact_status.in_(_RECONCILABLE_ARTIFACT_STATUSES)
        )
        .all()
    )


def get_local_download_for_episode(
        s: Session,
        profile: StreamProfileBase,
        episode: Episode,
        *,
        kind: StreamMediaKind,
) -> Optional[EpisodeMediaDownload]:
    return _select_resolvable_download(
        s,
        _episode_downloads(s, profile, episode.id),
        kind=kind,
        preferred_format=profile.preferred_format,
        prefer_exact_match=profile.prefer_exact_match,
    )


def get_local_hls_master(
        s: Session,
        profile: StreamProfileBase,
        episode_slug: str,
) -> Optional[Path]:
    """The playlist of the HLS download of the episode the profile offers under this slug, for serving
    one of its parts.

    A player asks for many parts at once when it starts and one every few seconds after, so this only
    trusts what VODLoft already knows of the download. Checking the whole bundle for each part (its
    playlists and every file they list) cost a tenth of a second or more a part and the parts waited
    on each other, so a starting player waited seconds; the playlist is checked when the player first
    asks for it.
    """
    episode = _offered_episode(s, profile, episode_slug)
    for download in _candidate_downloads(
        _episode_downloads(s, profile, episode.id),
        kind="hls",
        preferred_format=profile.preferred_format,
        prefer_exact_match=False,
    ):
        path = Path(download.file_path)
        if download.artifact_status == _AVAILABLE_ARTIFACT_STATUS and path.suffix.lower() == ".m3u8":
            return path
    return None


def _local_media(
        s: Session,
        profile: StreamProfileBase,
        downloads: list[EpisodeMediaDownload],
) -> dict[StreamMediaKind, Optional[EpisodeMediaDownload]]:
    """The download the profile serves for each kind of media it offers, main one first; ``None`` where
    no download of that kind is available."""
    return {
        kind: _select_resolvable_download(
            s,
            downloads,
            kind=kind,
            preferred_format=profile.preferred_format,
            prefer_exact_match=kind == "mp4" and profile.prefer_exact_match,
        )
        for kind in profile.media_kinds
    }


def _relevant_local_download(
        local: dict[StreamMediaKind, Optional[EpisodeMediaDownload]],
) -> Optional[EpisodeMediaDownload]:
    """The download that stands for the episode, such as for its size: that of the main media when there is one."""
    return next((download for download in local.values() if download is not None), None)


def _has_required_local_media(
        profile: StreamProfileBase,
        local: dict[StreamMediaKind, Optional[EpisodeMediaDownload]],
) -> bool:
    """Whether the media the profile needs of an episode is available locally: every kind it offers, or one
    for a profile that plays one at a time.

    A download-only profile must never publish a stable media URL that only the Site can
    satisfy. When streaming from the Site is enabled, partial local coverage is fine because
    each stable URL can independently fall back at request time.
    """
    available = (download is not None for download in local.values())
    return all(available) if profile.plays_every_media_kind else any(available)


def _episode_type_prefix(episode: Episode) -> str:
    return episode.episode_type or ""


def _profile_allows_episode(profile: StreamProfileBase, episode: Episode) -> bool:
    return _episode_type_prefix(episode) in with_main_type(profile.collection, profile.ep_id_type_list or [])


def _profile_streams_live_hls(profile: StreamProfileBase) -> bool:
    return (
        bool(profile.stream_live_episodes)
        and StreamMethod.LIVE in collection_site(profile.collection).stream_methods
        and "hls" in profile.media_kinds
    )


def keeps_live_episode_handoff(profile: StreamProfileBase) -> bool:
    """Whether the profile keeps a live episode it played from the Site playable from there until its download lands."""
    return (
        _profile_streams_live_hls(profile)
        and not profile.use_source_stream
        and profile.use_downloads
    )


def _download_profile_format_filter(kind: StreamMediaKind):
    preferred = LocalMediaProfileBase.preferred_format
    if kind == "audio":
        return preferred == PreferredFormat.FORMAT_AUDIO_ONLY
    if kind == "hls":
        return preferred == PreferredFormat.FORMAT_HLS
    return preferred.notin_((PreferredFormat.FORMAT_AUDIO_ONLY, PreferredFormat.FORMAT_HLS))


def _has_download_profile_for_episode(
        s: Session,
        episode: Episode,
        kind: StreamMediaKind,
) -> bool:
    """Whether an enabled Download Profile of this format will download the episode once it is published."""
    profiles = s.scalars(
        select(DownloadProfile)
        .join(LocalMediaProfileBase, LocalMediaProfileBase.id == DownloadProfile.local_media_profile_id)
        .where(
            DownloadProfile.collection_id == episode.collection_id,
            DownloadProfile.enable_profile.is_(True),
            _download_profile_format_filter(kind),
        )
    )
    return any(filters_allow_new_episode(profile.filters, episode) for profile in profiles)


def _can_stream_live_episode(
        s: Session,
        profile: StreamProfileBase,
        episode: Episode,
) -> bool:
    if not _profile_streams_live_hls(profile):
        return False
    if profile.use_source_stream:
        return True
    # A download-only profile lists a live episode only when its Download Profiles
    # will provide every kind of media it offers once the episode is published.
    # A profile that plays one media at a time keeps playing the episode from its HLS download.
    kinds = profile.media_kinds if profile.plays_every_media_kind else ("hls",)
    return profile.use_downloads and all(
        _has_download_profile_for_episode(s, episode, kind)
        for kind in kinds
    )


def can_stream_from_source(
        profile: StreamProfileBase,
        episode: Episode,
) -> bool:
    """Whether the profile may stream the episode straight from its Source, when it is not downloaded. The Site only
    has the whole video, so never a part of a split video."""
    if episode.part_of is not None:
        return False
    if profile.use_source_stream:
        return collection_site(profile.collection).streams
    if not keeps_live_episode_handoff(profile):
        return False
    if episode.publish_status == EpisodePublishStatus.LIVE.value:
        return True
    return episode.id in set(profile.live_episode_handoff_ids or [])


def remember_live_episode_handoff(
        profile: StreamProfileBase,
        episode: Episode,
) -> None:
    if (
        not keeps_live_episode_handoff(profile)
        or episode.publish_status != EpisodePublishStatus.LIVE.value
    ):
        return
    ids = set(profile.live_episode_handoff_ids or [])
    if episode.id not in ids:
        ids.add(episode.id)
        profile.live_episode_handoff_ids = sorted(ids)


def _download_completes_live_handoff(
        download: EpisodeMediaDownload,
) -> bool:
    return (
        download_kind(download) == "hls"
        and download.downloaded_publish_status
        == EpisodePublishStatus.PUBLISHED_FINAL.value
    )


def get_stream_items(
        s: Session,
        profile: StreamProfileBase,
) -> list[tuple[Episode, Optional[EpisodeMediaDownload]]]:
    """The episodes the profile offers, newest first, each with the download that stands for it.

    A live episode a download-only profile played stays listed, and playable from its Site, until its
    final HLS download lands (its handoff), so an app that is watching it keeps going.
    """
    live_enabled = _profile_streams_live_hls(profile)
    if not profile.use_downloads and not profile.use_source_stream and not live_enabled:
        return []

    previous_handoffs = set(profile.live_episode_handoff_ids or [])
    next_handoffs: set[int] = set()
    items: list[tuple[Episode, Optional[EpisodeMediaDownload]]] = []
    seen_episode_ids: set[int] = set()

    order_date = func.coalesce(
        Episode.published_date,
        Episode.went_live_date,
        Episode.created_at,
    )
    allowed_types = with_main_type(profile.collection, profile.ep_id_type_list or [])
    if not allowed_types:
        return []

    local_download_exists = exists(
        select(EpisodeMediaDownload.id).where(
            EpisodeMediaDownload.media_item_id == Episode.id,
            EpisodeMediaDownload.artifact_status.in_(
                _RECONCILABLE_ARTIFACT_STATUSES
            ),
        )
    )
    handoff_candidate = (
        Episode.id.in_(previous_handoffs)
        if previous_handoffs
        else false()
    )
    non_live_delivery_candidate = (
        or_(Episode.part_of.is_(None), local_download_exists)
        if profile.use_source_stream
        else local_download_exists
        if profile.use_downloads
        else false()
    )
    non_live_candidate = and_(
        Episode.publish_status != EpisodePublishStatus.LIVE.value,
        or_(
            handoff_candidate,
            and_(
                Episode.publish_status.not_in(_UNAVAILABLE_PUBLISH_STATUSES),
                non_live_delivery_candidate,
            ),
        ),
    )
    live_candidate = (
        Episode.publish_status == EpisodePublishStatus.LIVE.value
        if live_enabled and (profile.use_source_stream or profile.use_downloads)
        else false()
    )

    episode_query = (
        s.query(Episode)
        .filter(
            Episode.collection_id == profile.collection_id,
            episode_identifier_type_predicate(
                Episode.episode_identifier,
                allowed_types,
            ),
            or_(live_candidate, non_live_candidate),
        )
        .order_by(order_date.desc(), Episode.id.asc())
    )

    def load_downloads(episodes: list[Episode]) -> dict[int, list[EpisodeMediaDownload]]:
        if not profile.use_downloads or not episodes:
            return {}
        rows = (
            s.query(EpisodeMediaDownload)
            .options(joinedload(EpisodeMediaDownload.local_media_profile))
            .filter(EpisodeMediaDownload.media_item_id.in_(
                [episode.id for episode in episodes]
            ))
            .filter(
                EpisodeMediaDownload.artifact_status.in_(_RECONCILABLE_ARTIFACT_STATUSES)
            )
            .all()
        )
        grouped: dict[int, list[EpisodeMediaDownload]] = {}
        for download in rows:
            grouped.setdefault(download.media_item_id, []).append(download)
        return grouped

    def consider(
        episode: Episode,
        downloads_by_episode: dict[int, list[EpisodeMediaDownload]],
        *,
        collect: bool,
    ) -> None:
        seen_episode_ids.add(episode.id)
        if not _profile_allows_episode(profile, episode):
            return

        is_live = episode.publish_status == EpisodePublishStatus.LIVE.value
        if is_live:
            if _can_stream_live_episode(s, profile, episode):
                if collect:
                    items.append((episode, None))
                if (
                    episode.id in previous_handoffs
                    and keeps_live_episode_handoff(profile)
                ):
                    next_handoffs.add(episode.id)
            return

        local = _local_media(s, profile, downloads_by_episode.get(episode.id, []))
        relevant_local = _relevant_local_download(local)
        hls = local.get("hls")

        handoff_active = (
            episode.id in previous_handoffs
            and keeps_live_episode_handoff(profile)
        )
        if handoff_active and hls is not None and _download_completes_live_handoff(hls):
            handoff_active = False

        if handoff_active:
            if collect:
                items.append((episode, relevant_local))
            next_handoffs.add(episode.id)
            return

        if episode.publish_status in _UNAVAILABLE_PUBLISH_STATUSES:
            return

        # The Site only has the whole video, so a part of a split video is only served from its own file.
        streams = profile.use_source_stream and episode.part_of is None
        if collect and (streams or _has_required_local_media(profile, local)):
            items.append((episode, relevant_local))

    if profile.max_items > 0:
        batch_size = max(50, min(profile.max_items * 2, 250))
        offset = 0
        while len(items) < profile.max_items:
            batch = episode_query.offset(offset).limit(batch_size).all()
            if not batch:
                break
            downloads_by_episode = load_downloads(batch)
            for episode in batch:
                consider(episode, downloads_by_episode, collect=True)
            offset += len(batch)
            if len(batch) < batch_size:
                break
    else:
        episodes = episode_query.all()
        downloads_by_episode = load_downloads(episodes)
        for episode in episodes:
            consider(episode, downloads_by_episode, collect=True)

    # Handoff durability is independent of max_items. Reconcile old handoffs that
    # were older than the bounded scan without loading the rest of the collection.
    remaining_handoff_ids = previous_handoffs - seen_episode_ids
    if remaining_handoff_ids:
        handoff_episodes = (
            s.query(Episode)
            .filter(
                Episode.collection_id == profile.collection_id,
                Episode.id.in_(remaining_handoff_ids),
            )
            .all()
        )
        downloads_by_episode = load_downloads(handoff_episodes)
        for episode in handoff_episodes:
            consider(episode, downloads_by_episode, collect=False)

    normalized_handoffs = sorted(next_handoffs)
    if list(profile.live_episode_handoff_ids or []) != normalized_handoffs:
        profile.live_episode_handoff_ids = normalized_handoffs

    return items[:profile.max_items] if profile.max_items > 0 else items


def _offered_episode(
        s: Session,
        profile: StreamProfileBase,
        episode_slug: str,
) -> Episode:
    """The episode under this slug, if it is of a type the profile offers; whether it has media is not checked."""
    allowed_types = with_main_type(profile.collection, profile.ep_id_type_list or [])
    if not allowed_types:
        raise _not_offered()

    episode: Optional[Episode] = (
        s.query(Episode)
        .filter(
            Episode.slug == episode_slug,
            Episode.collection_id == profile.collection_id,
            episode_identifier_type_predicate(
                Episode.episode_identifier,
                allowed_types,
            ),
        )
        .one_or_none()
    )
    if episode is None:
        raise _not_offered()
    return episode


def get_stream_episode(
        s: Session,
        profile: StreamProfileBase,
        episode_slug: str,
) -> Episode:
    """The episode the profile offers under this slug, for playing it."""
    episode = _offered_episode(s, profile, episode_slug)

    if episode.publish_status == EpisodePublishStatus.LIVE.value:
        if not _can_stream_live_episode(s, profile, episode):
            raise ServiceError("Live episode streaming is not available for this episode", status_code=404)
        return episode

    handoff_active = (
        episode.id in set(profile.live_episode_handoff_ids or [])
        and keeps_live_episode_handoff(profile)
    )
    local: dict[StreamMediaKind, Optional[EpisodeMediaDownload]] | None = None

    if handoff_active:
        local = _local_media(s, profile, _episode_downloads(s, profile, episode.id))
        hls = local.get("hls")
        if hls is not None and _download_completes_live_handoff(hls):
            remaining = set(profile.live_episode_handoff_ids or [])
            remaining.discard(episode.id)
            profile.live_episode_handoff_ids = sorted(remaining)
        else:
            return episode

    if episode.publish_status == EpisodePublishStatus.SOURCE_PROCESSING.value:
        raise ServiceError("Episode media is still processing", status_code=404)

    if local is None:
        local = _local_media(s, profile, _episode_downloads(s, profile, episode.id))
    if _has_required_local_media(profile, local) or profile.use_source_stream:
        return episode

    raise ServiceError("No media available for this episode", status_code=404)


def get_media_for_episode(
        s: Session,
        profile: StreamProfileBase,
        episode_slug: str,
) -> tuple[Episode, Optional[EpisodeMediaDownload]]:
    """The episode under this slug, and the download that stands for it, if any."""
    episode = get_stream_episode(s, profile, episode_slug)
    return episode, _relevant_local_download(_local_media(s, profile, _episode_downloads(s, profile, episode.id)))


def get_source_stream_url(
        profile: StreamProfileBase,
        episode: Episode,
        *,
        media_kind: Literal["audio", "video"] | None = None,
        source: Source | None = None,
) -> str:
    """Ask the episode's Source for its current stream URL."""
    source = source or get_source(episode.source_key)
    members_only = profile.collection.membership_level not in {
        FREE_LEVEL,
        HIGHEST_LEVEL,
    } and _owner_may_use_members_only_media(profile)
    try:
        media = source.episode_media(slug=episode.slug, members_only=members_only, interactive=True)
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        raise ServiceError(f"{source.name} stream is currently unavailable", status_code=502) from exc

    if media_kind is None:
        media_kind = (
            "audio"
            if profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
            else "video"
        )

    media_url = media.audio_url if media_kind == "audio" else media.video_url
    if not media_url:
        raise ServiceError(f"No {source.name} {media_kind} stream available for this episode", status_code=404)
    return media_url

