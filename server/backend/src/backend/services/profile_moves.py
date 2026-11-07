"""Moving episode downloads from one Collection Local Media Profile to another.

A move hands each download record over to the target profile, so its history,
quality facts and *kept* flag come along, and moves its files to the path the
target's output template gives them. Nothing is overwritten: an episode the
target already has, a path another file holds, a missing file or a running
download is left where it is and reported.
"""
from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from collections.abc import Collection as CollectionOf, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.db.models import Collection, CollectionLocalMediaProfile, DownloadProfile, Episode
from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadAsset, MediaDownloadBase
from backend.services.adoption import download_root, sidecar_assets
from backend.services.custom_indexes import profile_applies_to_collection
from backend.services.download_metadata import build_episode_metadata, select_thumbnail
from backend.services.download_options import effective_metadata_mode, effective_thumbnail_mode
from backend.services.download_relocation import (
    DownloadRelocation, filter_relocation_conflicts, plan_download_relocation, relocate_downloads,
)
from backend.services.media_download_history import record_media_download_history
from backend.services.no_ascii_names import settle_no_ascii_name
from backend.services.episode_filters import EpisodeSelection, date_line_leaves_out, evaluate, is_date_line, protected
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.local_media_profile_types import EpisodeMoveOutcome
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from backend.utils.custom_index import CustomIndexNotReadyError
from backend.utils.output_template import resolve_episode_output_path
from config.settings.submodels import MetadataMode, ThumbnailMode
from downloader.metadata import render_nfo
from downloader.storage.identity import inspect_artifact
from task_manager.tasks.media_download_operations import get_active_media_download_operation
from task_manager.tasks.workers.file_watcher.service import resolve_media_download_file

logger = logging.getLogger(__name__)

_WITH_FILE = (
    MediaDownloadArtifactStatus.AVAILABLE.value,
    MediaDownloadArtifactStatus.CORRUPTED.value,
)
_CANDIDATES = (*_WITH_FILE, MediaDownloadArtifactStatus.MISSING.value)
_THUMBNAIL_EXTENSIONS = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_THUMBNAIL_BYTES = 20 * 1024 * 1024


class ProfileMoveError(ValueError):
    """The move can't be made as asked; the message says why."""


@dataclass
class EpisodeMove:
    download: EpisodeMediaDownload
    outcome: EpisodeMoveOutcome
    source: Path
    destination: Path | None = None
    """``None`` when the target's Custom Index numbers are not worked out yet."""
    target_download: EpisodeMediaDownload | None = None

    @property
    def episode(self) -> Episode:
        return self.download.media


@dataclass
class CollectionMove:
    collection: Collection
    in_scope: bool
    episodes: list[EpisodeMove] = field(default_factory=list)
    source_download_profiles: list[DownloadProfile] = field(default_factory=list)
    target_download_profiles: list[DownloadProfile] = field(default_factory=list)
    retention_at_risk: int = 0
    """Moved episodes the target's Download Profile would delete as older episodes."""

    @property
    def blocked(self) -> bool:
        return any(item.outcome is EpisodeMoveOutcome.SAME_PATH for item in self.episodes)

    @property
    def can_move_download_profile(self) -> bool:
        return bool(self.source_download_profiles) and not self.target_download_profiles

    def count(self, *outcomes: EpisodeMoveOutcome) -> int:
        return sum(item.outcome in outcomes for item in self.episodes)


def plan_profile_move(
    session: Session,
    source: CollectionLocalMediaProfile,
    target: CollectionLocalMediaProfile,
    *,
    collection_ids: CollectionOf[int] | None = None,
) -> list[CollectionMove]:
    """What moving the source's downloads to the target would do, per Collection. Changes nothing."""
    if source.id == target.id:
        raise ProfileMoveError("Choose another Local Media Profile to move to")

    stmt = (
        select(EpisodeMediaDownload)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .options(
            joinedload(EpisodeMediaDownload.media.of_type(Episode)).joinedload(Episode.collection),
            selectinload(EpisodeMediaDownload.assets),
        )
        .where(
            EpisodeMediaDownload.local_media_profile_id == source.id,
            EpisodeMediaDownload.artifact_status.in_(_CANDIDATES),
        )
        .order_by(Episode.collection_id, Episode.index, EpisodeMediaDownload.id)
    )
    if collection_ids is not None:
        stmt = stmt.where(Episode.collection_id.in_(tuple(collection_ids)))
    downloads = list(session.scalars(stmt).unique())

    episode_ids = [download.media_item_id for download in downloads]
    target_downloads: dict[int, EpisodeMediaDownload] = {
        download.media_item_id: download
        for download in session.scalars(select(EpisodeMediaDownload).where(
            EpisodeMediaDownload.local_media_profile_id == target.id,
            EpisodeMediaDownload.media_item_id.in_(episode_ids),
        ))
    } if episode_ids else {}

    by_collection: dict[int, list[EpisodeMediaDownload]] = defaultdict(list)
    for download in downloads:
        by_collection[download.media.collection_id].append(download)

    plans = []
    for collection_downloads in by_collection.values():
        collection = collection_downloads[0].media.collection
        plan = CollectionMove(
            collection=collection,
            in_scope=profile_applies_to_collection(target, collection),
            source_download_profiles=[dp for dp in collection.download_profiles if dp.local_media_profile_id == source.id],
            target_download_profiles=[dp for dp in collection.download_profiles if dp.local_media_profile_id == target.id],
        )
        plan.episodes = [
            _plan_episode(session, download, target, target_downloads.get(download.media_item_id))
            for download in collection_downloads
        ]
        _mark_shared_destinations(plan.episodes)
        if plan.target_download_profiles:
            plan.retention_at_risk = _retention_at_risk(
                session, plan.target_download_profiles[0],
                [item.download for item in plan.episodes if item.outcome.moves],
            )
        plans.append(plan)
    plans.sort(key=lambda plan: plan.collection.title.casefold())
    return plans


def _plan_episode(
    session: Session,
    download: EpisodeMediaDownload,
    target: CollectionLocalMediaProfile,
    target_download: EpisodeMediaDownload | None,
) -> EpisodeMove:
    source = Path(download.file_path)
    if get_active_media_download_operation(session, download.id) is not None:
        return EpisodeMove(download, EpisodeMoveOutcome.BUSY, source)
    if target_download is not None and target_download.artifact_status in _WITH_FILE:
        return EpisodeMove(download, EpisodeMoveOutcome.TARGET_HAS_FILE, source, target_download=target_download)
    if download.artifact_status == MediaDownloadArtifactStatus.MISSING.value or not source.is_file():
        return EpisodeMove(download, EpisodeMoveOutcome.FILE_MISSING, source)
    if target_download is not None and get_active_media_download_operation(session, target_download.id) is not None:
        return EpisodeMove(download, EpisodeMoveOutcome.BUSY, source)

    outcome = EpisodeMoveOutcome.REPLACE if target_download is not None else EpisodeMoveOutcome.MOVE
    try:
        destination = target_destination(session, download, target, source)
    except CustomIndexNotReadyError:
        return EpisodeMove(download, outcome, source, target_download=target_download)
    if destination != source and destination.exists():
        outcome = EpisodeMoveOutcome.PATH_TAKEN
    return EpisodeMove(download, outcome, source, destination, target_download)


def target_destination(
    session: Session, download: EpisodeMediaDownload, target: CollectionLocalMediaProfile, source: Path,
) -> Path:
    extension = source.suffix.removeprefix(".")
    if not extension:
        raise ProfileMoveError(f"Cannot tell the extension of {source}")
    destination = resolve_episode_output_path(
        target.output_template, episode=download.media, local_media_profile=target,
        media_download=download, extension=extension,
    )
    return settle_no_ascii_name(download, destination, session=session)


def _mark_shared_destinations(items: Sequence[EpisodeMove]) -> None:
    counts = Counter(item.destination for item in items if item.outcome.moves and item.destination is not None)
    for item in items:
        if item.outcome.moves and item.destination is not None and counts[item.destination] > 1:
            item.outcome = EpisodeMoveOutcome.SAME_PATH


def _retention_at_risk(
    session: Session, profile: DownloadProfile, downloads: Sequence[EpisodeMediaDownload],
) -> int:
    """How many of these downloads the Download Profile's retention would delete once they are its own.

    Follows the Download Profile worker's cleanup: only a profile that deletes older
    episodes removes files, and kept downloads or Keep filters protect them.
    """
    if not downloads or not profile.delete_older_episodes:
        return 0
    if not any(is_date_line(item) for item in profile.filters):
        return 0
    evaluation = evaluate(session, EpisodeSelection.of_profile(profile))
    return sum(
        1 for download in downloads
        if not protected(evaluation, download) and date_line_leaves_out(evaluation, download)
    )


@dataclass(frozen=True)
class CollectionMoveResult:
    moved: int = 0
    skipped: int = 0
    sidecars_added: int = 0
    download_profiles_moved: int = 0

    def as_data(self) -> dict[str, int]:
        return {
            "episodes_moved": self.moved,
            "episodes_skipped": self.skipped,
            "sidecars_added": self.sidecars_added,
            "download_profiles_moved": self.download_profiles_moved,
        }


def move_collection_downloads(
    session: Session,
    *,
    source_id: int,
    target_id: int,
    collection_id: int,
    move_download_profile: bool,
    progress=None,
) -> CollectionMoveResult:
    """Move one Collection's downloads from the source profile to the target.

    Files move first, each download's path is recorded, and only then does the
    download change profile. A run that stops halfway leaves files on the source
    profile at their new path, which running the move again picks up.
    """
    source = session.get(CollectionLocalMediaProfile, source_id)
    target = session.get(CollectionLocalMediaProfile, target_id)
    if source is None or target is None:
        raise ProfileMoveError("The Local Media Profile no longer exists")
    plans = plan_profile_move(session, source, target, collection_ids=(collection_id,))
    if not plans:
        return CollectionMoveResult()
    plan = plans[0]
    if not plan.in_scope:
        raise ProfileMoveError(f"{target.name} is not offered for {plan.collection.title}")
    if plan.blocked:
        raise ProfileMoveError(
            f"Several episodes of {plan.collection.title} would get the same path in {target.name}"
        )

    candidates = [item for item in plan.episodes if item.outcome.moves]
    skipped = len(plan.episodes) - len(candidates)
    moves: list[DownloadRelocation] = []
    in_place: list[EpisodeMove] = []
    by_id: dict[int, EpisodeMove] = {}
    for index, item in enumerate(candidates, start=1):
        download = item.download
        current = resolve_media_download_file(session, download)
        if current is None:
            skipped += 1
            continue
        _record_untracked_sidecars(session, download, current)
        destination = target_destination(session, download, target, current)
        by_id[download.id] = item
        if destination == current:
            in_place.append(item)
        else:
            moves.append(plan_download_relocation(download, current, destination))
        _progress(progress, round(index / max(len(candidates), 1) * 20), "Planning the move")

    remaining, blocked = filter_relocation_conflicts(moves)
    skipped += len(blocked)
    if remaining:
        relocate_downloads(session, remaining, progress=progress, reason="profile_move")
        _remove_empty_folders(path.source.parent for move in remaining for path in move.paths)
    moved_items = [by_id[move.download_id] for move in remaining] + in_place

    managing_profile = _managing_download_profile(plan, move_download_profile)
    moved_ids: list[int] = []
    for item in moved_items:
        download = session.get(EpisodeMediaDownload, item.download.id)
        if download is None or download.local_media_profile_id != source.id:
            continue
        existing = session.scalar(select(EpisodeMediaDownload).where(
            EpisodeMediaDownload.local_media_profile_id == target.id,
            EpisodeMediaDownload.media_item_id == download.media_item_id,
        ))
        if existing is not None:
            if existing.artifact_status in _WITH_FILE:
                skipped += 1
                continue
            # The target only had a record without a file; the moved download takes its place.
            session.delete(existing)
            session.flush()
        download.local_media_profile_id = target.id
        download.download_profile_id = managing_profile.id if managing_profile is not None else None
        record_media_download_history(session, download.id, MediaDownloadHistoryAction.MOVED, metadata={
            "from_profile": source.name, "to_profile": target.name,
            "from_profile_id": source.id, "to_profile_id": target.id,
        })
        moved_ids.append(download.id)
    session.flush()

    profiles_moved = 0
    if move_download_profile and plan.can_move_download_profile:
        for profile in plan.source_download_profiles:
            profile.local_media_profile_id = target.id
            profiles_moved += 1
            # Downloads that stayed behind no longer belong to a Download Profile of their own profile.
            for download in list(profile.episode_downloads):
                if download.local_media_profile_id == source.id:
                    download.download_profile_id = None
    session.commit()

    sidecars = 0
    for index, download_id in enumerate(moved_ids, start=1):
        download = session.get(EpisodeMediaDownload, download_id)
        if download is not None:
            sidecars += fill_missing_sidecars(session, download)
            session.commit()
        _progress(progress, 90 + round(index / len(moved_ids) * 10), "Filling in missing sidecars")

    return CollectionMoveResult(
        moved=len(moved_ids), skipped=skipped,
        sidecars_added=sidecars, download_profiles_moved=profiles_moved,
    )


def _managing_download_profile(plan: CollectionMove, move_download_profile: bool) -> DownloadProfile | None:
    if plan.target_download_profiles:
        return plan.target_download_profiles[0]
    if move_download_profile and plan.source_download_profiles:
        return plan.source_download_profiles[0]
    return None


def _record_untracked_sidecars(session: Session, download: EpisodeMediaDownload, media_path: Path) -> None:
    """Record sidecars next to the file that VODLoft recognises but doesn't track yet, so they move along."""
    known_keys = {asset.asset_key for asset in download.assets}
    known_paths = {Path(asset.path) for asset in download.assets}
    for asset_key, kind, path in sidecar_assets(media_path):
        if asset_key in known_keys or path in known_paths:
            continue
        try:
            identity = inspect_artifact(path)
        except (OSError, ValueError):
            continue
        download.assets.append(MediaDownloadAsset(
            asset_key=asset_key, kind=kind, path=str(path), suffix=path.name[len(media_path.stem):],
            size_bytes=identity.size_bytes, fingerprint=identity.fingerprint,
        ))
    session.flush()


def fill_missing_sidecars(session: Session, download: EpisodeMediaDownload) -> int:
    """Write the NFO and thumbnail the download's profile asks for but the file doesn't have yet.

    Subtitles need the episode's stream looked up again, so a move leaves them to a redownload.
    Returns how many sidecars were added. A sidecar that can't be made is logged and skipped.
    """
    profile = download.local_media_profile
    media_path = Path(download.file_path)
    episode = download.media
    kinds = {asset.kind for asset in download.assets}
    added = 0

    if effective_metadata_mode(profile) in (MetadataMode.NFO, MetadataMode.EMBED_AND_NFO) and "nfo" not in kinds:
        path = media_path.with_name(media_path.stem + ".nfo")
        content = render_nfo(build_episode_metadata(episode, episode.collection))
        if _write_new_file(path, content):
            _add_asset(download, "nfo", "nfo", path, media_path)
            added += 1

    thumbnail_mode = effective_thumbnail_mode(profile)
    if thumbnail_mode in (ThumbnailMode.SIDECAR, ThumbnailMode.EMBED_AND_SIDECAR) and "thumbnail" not in kinds:
        thumbnail = select_thumbnail(episode)
        fetched = (
            _own_thumbnail(thumbnail) if isinstance(thumbnail, Path)
            else _fetch_thumbnail(thumbnail) if thumbnail else None
        )
        if fetched is not None:
            extension, content = fetched
            path = media_path.with_name(f"{media_path.stem}.{extension}")
            if _write_new_file(path, content):
                _add_asset(download, "artwork", "thumbnail", path, media_path)
                added += 1
    session.flush()
    return added


def _own_thumbnail(path: Path) -> tuple[str, bytes] | None:
    """A frame VODLoft took from the video, which it keeps as a JPEG."""
    try:
        return "jpg", path.read_bytes()
    except OSError as exc:  # A missing thumbnail never fails the move.
        logger.warning("Could not read the thumbnail %s: %s", path, exc)
        return None


def _fetch_thumbnail(url: str) -> tuple[str, bytes] | None:
    from downloader.http import http_get

    try:
        with http_get(url, retries=1) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            extension = _THUMBNAIL_EXTENSIONS.get(content_type)
            if extension is None:
                logger.warning("Not adding a thumbnail from %s: unexpected type %r", url, content_type)
                return None
            content = response.read()
    except Exception as exc:  # A missing thumbnail never fails the move.
        logger.warning("Could not fetch the thumbnail %s: %s", url, exc)
        return None
    if not content or len(content) > _MAX_THUMBNAIL_BYTES:
        return None
    return extension, content


def _write_new_file(path: Path, content: bytes) -> bool:
    """Write ``content`` to ``path`` unless something is already there."""
    try:
        with path.open("xb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
    except FileExistsError:
        return False
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)
        path.unlink(missing_ok=True)
        return False
    return True


def _add_asset(download: MediaDownloadBase, asset_key: str, kind: str, path: Path, media_path: Path) -> None:
    identity = inspect_artifact(path)
    download.assets.append(MediaDownloadAsset(
        asset_key=asset_key, kind=kind, path=str(path), suffix=path.name[len(media_path.stem):],
        size_bytes=identity.size_bytes, fingerprint=identity.fingerprint,
    ))


def _remove_empty_folders(folders) -> None:
    """Remove the folders the moved files left empty, up to the download folder."""
    root = download_root()
    for folder in sorted(set(folders), key=lambda path: len(path.parts), reverse=True):
        while folder != root and folder.is_relative_to(root):
            try:
                folder.rmdir()
            except OSError:
                break
            folder = folder.parent


def _progress(progress, value: int, message: str) -> None:
    if progress is not None:
        from task_manager.tasks.helpers.progress import update_progress

        update_progress(progress, value, message)
