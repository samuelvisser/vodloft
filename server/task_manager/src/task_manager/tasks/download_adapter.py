"""Application adapter for the standalone download coordinator.

Workers do not implement download behavior. This adapter translates lifecycle
snapshots into TaskRun reporting and atomically persists successful artifacts.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Episode
from backend.db.models.media_download import MediaDownloadAsset, MediaDownloadBase
from backend.services.collection_cookies import note_failed_download
from backend.services.download_plans import prepare_download_plan
from backend.services.download_relocation import remove_folders_left_empty
from backend.services.media_access import lock_refused, media_access, media_site_key, site_access
from backend.services.sites import collection_site
from backend.services.upgrade_check import schedule_first_upgrade_check
from backend.services.notifications.emitters import episode_downloaded
from backend.services.media_download_history import (
    download_attempt_metadata, record_media_download_history,
    record_media_download_history_if_exists, record_media_download_operation_history_once,
)
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from config import get_settings
from sources import UnknownSourceError, get_source
from sources.pacing import RequestCanceled, request_context
from downloader import AccessRequiredError, DownloadCanceled, EncryptedMediaError, media_duration
from downloader.capacity import resources
from downloader.coordinator import DownloadExecution, execute_download_plan
from downloader.storage.replacement import (
    PreviousDownload, capture_previous_download, retire_superseded_files,
)
from downloader.lifecycle import (
    DownloadSnapshot,
    DownloadTracker,
    download_completion_fraction,
)
from downloader.transfer_context import transfer_context
from task_manager.scheduler.operation_context import current_operation_ids
from task_manager.scheduler.results import TaskResult
from task_manager.tasks.media_download_operations import on_media_download_transfer_complete


logger = logging.getLogger(__name__)


class DownloadProgressReporter:
    """Persist one ordered snapshot; numeric TaskRun progress is transfer-only."""
    def __init__(self, progress):
        self.progress = progress
        self.selected_format: str | None = None

    def __call__(self, snapshot: DownloadSnapshot) -> None:
        if self.progress is None:
            return
        media = next((stage for stage in snapshot.stages if stage.id == "media"), None)
        fraction = media.fraction if media is not None else None
        percent = min(99, int(100 * fraction)) if fraction is not None else 0
        main = next(stage for stage in snapshot.stages if stage.id == snapshot.main_activity)
        running = [stage for stage in snapshot.stages if stage.state in ("running", "waiting")]
        # A blocked auxiliary fetch must not pause media that is still moving.
        blocked = bool(running) and all(stage.wait is not None for stage in running)
        wait = asdict(main.wait) if blocked and main.wait else None
        message = main.code.replace("_", " ").capitalize()
        if wait is not None:
            from task_manager.scheduler.executor import request_wait_message
            wait["message"] = request_wait_message(wait["reason"])
            message = wait["message"]
        metadata = {"download": asdict(snapshot), "selected_format": self.selected_format}
        completion_percent = min(99, int(100 * download_completion_fraction(snapshot)))
        # The real executor supports atomic state+wait checkpoints. CLI sinks
        # report the same structured facts without owning a scheduler wait state.
        from task_manager.scheduler.executor import ProgressUpdater
        if isinstance(self.progress, ProgressUpdater):
            from task_manager.scheduler.executor import TaskCancellationRequested
            try:
                self.progress.set(
                    percent,
                    message,
                    meta=metadata,
                    completion_percent=completion_percent,
                    wait_state=wait,
                )
            except TaskCancellationRequested as exc:
                raise DownloadCanceled(str(exc)) from exc
        else:
            self.progress.set(percent, message, meta=metadata)


def _mark_drm_protected(session: Session, media_download_id: int) -> bool:
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        return False
    download.media.drm_protected = True
    download.automatic_retry_suppressed = True
    return True


def _refused_access(media_download_id: int, exc: Exception) -> str | None:
    """The key of the access the Source refused the download for lack of, or None for any other failure.

    A failure that only asks for signing in is not refused access while the Collection just started
    using the cookies file, because the retry downloads with it.
    """
    if isinstance(exc, AccessRequiredError) and exc.access is not None:
        return exc.access
    error = str(exc)
    if run_write_transaction(lambda w: note_failed_download(w, media_download_id, error)):
        return None
    session = get_session()
    try:
        download = session.get(MediaDownloadBase, media_download_id)
        source_key = download.media.source_key if download is not None else None
    finally:
        session.close()
    if source_key is None:
        return None
    try:
        return get_source(source_key).refused_access(error)
    except UnknownSourceError:
        return None


def _tell_source_refused(media_download_id: int, access: str) -> None:
    """Let the Source check whether what VODLoft has changed, such as the account's membership level."""
    session = get_session()
    try:
        download = session.get(MediaDownloadBase, media_download_id)
        source_key = download.media.source_key if download is not None else None
    finally:
        session.close()
    if source_key is None:
        return
    try:
        get_source(source_key).download_refused(access)
    except Exception:
        logger.exception("Could not let the Source check its access after download %s was refused", media_download_id)


def _lock_media(session: Session, media_download_id: int, access: str) -> str | None:
    """Lock the download's media, and return what its Site calls the access."""
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        return None
    lock_refused(download.media, access)
    found = media_access(download.media)
    return found.label if found is not None else "an access VODLoft does not have"


def _retire_previous_after_commit(previous: PreviousDownload, execution: DownloadExecution) -> None:
    """Remove superseded paths only once the new download is fully committed."""
    retained = frozenset((
        execution.result.path,
        *(asset.path for asset in execution.assets),
    ))
    superseded = [
        path for path in (previous.media.path, *(asset.path for asset in previous.assets))
        if str(path) not in retained and path.exists()
    ]
    retire_superseded_files(previous, retained_paths=retained)
    # A new name can put the download in another folder; the old one goes when nothing at all is left in it.
    remove_folders_left_empty(
        (path.parent for path in superseded if not path.exists()),
        keep=(Path(path) for path in retained),
    )


def _allow_automatic_retry(session: Session, media_download_id: int) -> None:
    current = session.get(MediaDownloadBase, media_download_id)
    if current is None:
        raise DownloadCanceled("Media download was deleted before replacement preparation")
    current.automatic_retry_suppressed = False


def _record_download(
    session: Session, *, media_download_id: int, execution: DownloadExecution, plan, duration, publish_status,
    is_redownload: bool, lifecycle, started: datetime, attempt: dict, title: str, progress,
) -> TaskResult:
    """Record the finished download, and complete its task run in the same transaction."""
    download = session.get(MediaDownloadBase, media_download_id)
    if download is None:
        raise DownloadCanceled("Download was deleted during execution")
    identity = execution.identity
    download.file_path = execution.result.path
    download.assets.clear()
    session.flush()
    for asset in execution.assets:
        suffix = Path(asset.path).name[len(Path(execution.result.path).stem):]
        download.assets.append(MediaDownloadAsset(
            asset_key=asset.id, kind=asset.kind, path=asset.path, suffix=suffix,
            size_bytes=asset.identity.size_bytes, fingerprint=asset.identity.fingerprint,
        ))
    download.artifact_stat_dev, download.artifact_stat_ino = identity.stat_dev, identity.stat_ino
    download.artifact_size_bytes, download.artifact_fingerprint = identity.size_bytes, identity.fingerprint
    download.artifact_status = MediaDownloadArtifactStatus.AVAILABLE.value
    download.artifact_error = None
    download.automatic_retry_suppressed = False
    download.downloaded_bytes = execution.result.bytes_downloaded
    download.format_downloaded = execution.format_downloaded
    segments = execution.result.sponsorblock
    download.sponsorblock_segments = None if segments is None else [segment._asdict() for segment in segments]
    video = execution.result.video
    download.video_height, download.video_codec = (video.height, video.codec) if video is not None else (None, None)
    download.duration = duration
    download.subtitle_languages = (
        [subtitle.language for subtitle in execution.result.subtitles if not subtitle.auto_generated]
        if plan.source.ytdlp_command else None
    )
    finished = datetime.now(timezone.utc)
    download.downloaded_at = finished
    if isinstance(download.media, Episode):
        download.downloaded_publish_status = publish_status
        schedule_first_upgrade_check(download, collection_site(download.media.collection), finished)
        episode_downloaded(session, download.media, path=execution.result.path, replaced=is_redownload)
    result_data = {
        "media_download_id": media_download_id, "is_redownload": is_redownload,
        "file_path": execution.result.path, "downloaded_bytes": execution.result.bytes_downloaded,
        "format_downloaded": execution.format_downloaded,
        "thumbnail_path": download.thumbnail_path, "nfo_path": download.nfo_path,
        "lifecycle": asdict(lifecycle),
    }
    record_media_download_history(
        session, media_download_id, MediaDownloadHistoryAction.COMPLETED,
        metadata=download_attempt_metadata(
            started_at=started, finished_at=finished, **attempt, **result_data,
            started_publish_status=publish_status, downloaded_publish_status=publish_status,
        ), occurred_at=finished,
    )
    result = TaskResult(summary=f"Downloaded {title}", data=result_data)
    if progress is not None:
        progress.complete_transactionally(session, result)
    return result


def run_download(
    session: Session, *, media_download_id: int, is_redownload: bool = False,
    prepare_existing_artifact: bool = False, progress=None,
) -> TaskResult:
    """Download one media item. ``session`` only reads; every write is a short write transaction of its own,
    and none stays open while the Source is asked or the file is transferred."""
    operation_ids = current_operation_ids()
    run_id = getattr(progress, "run_id", None)
    attempt = {"operation_ids": list(operation_ids)}
    if run_id is not None:
        attempt["task_run_id"] = int(run_id)
    started = datetime.now(timezone.utc)

    def record_start(w: Session) -> tuple[str, str | None, str]:
        download = w.get(MediaDownloadBase, media_download_id)
        if download is None:
            raise DownloadCanceled("Media download was deleted before it started")
        publish_status = getattr(download.media, "publish_status", None)
        record_media_download_history(
            w, media_download_id, MediaDownloadHistoryAction.STARTED,
            metadata={**attempt, "is_redownload": is_redownload, "started_publish_status": publish_status},
            occurred_at=started,
        )
        return download.media.title, publish_status, download.artifact_status

    title, publish_status, artifact_status = run_write_transaction(record_start)
    reporter = DownloadProgressReporter(progress)
    tracker = DownloadTracker(reporter, progress if callable(progress) else None)
    execution = None
    previous: PreviousDownload | None = None
    preserving_artifact = False
    committed = False
    resources.media.configure(get_settings().download_settings.max_concurrent_downloads)
    try:
        with tracker:
            if prepare_existing_artifact or artifact_status != MediaDownloadArtifactStatus.ABSENT.value:
                tracker.ensure_active()
                tracker.preparing("prepare_existing_artifact")
                session.rollback()
                current = session.get(MediaDownloadBase, media_download_id)
                if current is None:
                    raise DownloadCanceled("Media download was deleted before replacement preparation")
                preserving_artifact = (
                    current.artifact_status != MediaDownloadArtifactStatus.ABSENT.value
                )
                file_path, size_bytes, fingerprint = current.file_path, current.artifact_size_bytes, current.artifact_fingerprint
                assets = tuple((asset.path, asset.size_bytes, asset.fingerprint) for asset in current.assets)
                session.rollback()
                if preserving_artifact:
                    previous = capture_previous_download(
                        file_path, size_bytes=size_bytes, fingerprint=fingerprint, assets=assets,
                    )
                    if previous is None:
                        # The file at the recorded path no longer matches its
                        # recorded identity (Corrupted, changed or never
                        # fingerprinted). Replace it in place rather than
                        # publishing the new download next to it as a duplicate.
                        previous = capture_previous_download(
                            file_path,
                            size_bytes=None,
                            fingerprint=None,
                            assets=tuple((path, None, None) for path, _, _ in assets),
                            claim_current=True,
                        )
                # An attempt owns none of the previous output paths until a new
                # artifact is committed. Never delete or reset the old artifact
                # merely because retry work is starting, including Missing or
                # Corrupted records that may still have a physical file.
                run_write_transaction(lambda w: _allow_automatic_retry(w, media_download_id))

            def waiting(event):
                tracker.wait("prepare", event.reason if event else None, event.until if event else None)
            with request_context(observer=waiting, should_cancel=tracker.is_canceled), transfer_context(tracker.is_canceled, waiting):
                plan = prepare_download_plan(session, media_download_id, tracker)
            reporter.selected_format = plan.source.format_downloaded

            def reserved(destination: str) -> None:
                def write(w: Session) -> None:
                    current = w.get(MediaDownloadBase, media_download_id)
                    if current is None:
                        raise DownloadCanceled("Download was deleted before reserving its destination")
                    if not preserving_artifact:
                        current.file_path = destination

                run_write_transaction(write)

            execution = execute_download_plan(
                plan, tracker=tracker, resources=resources,
                on_destination_reserved=reserved,
                on_media_transfer_complete=on_media_download_transfer_complete,
                previous=previous,
                media_download_id=media_download_id,
                downloaded_publish_status=publish_status,
            )
            tracker.ensure_active()
            duration = media_duration(execution.result.path, ffmpeg_path=plan.ffmpeg_path)
            # Stop concurrent reporting before entering the final transaction;
            # no auxiliary thread owns a Session or writes past publication.
            lifecycle = tracker.finish()
            session.rollback()
            from task_manager.scheduler.executor import ProgressUpdater

            def publish(session: Session) -> TaskResult:
                return _record_download(
                    session, media_download_id=media_download_id, execution=execution, plan=plan,
                    duration=duration, publish_status=publish_status, is_redownload=is_redownload,
                    lifecycle=lifecycle, started=started, attempt=attempt, title=title,
                    progress=progress if isinstance(progress, ProgressUpdater) else None,
                )

            result = run_write_transaction(publish)
            committed = True
            try:
                if execution.replacement_journal is not None:
                    # All final names were replaced before the database commit.
                    # Startup recovery handles a crash or failure before cleanup.
                    execution.replacement_journal.cleanup_committed()
                elif previous is not None:
                    # Changed output paths and local HLS bundles cannot be
                    # replaced as a single file; publish first, retire second.
                    _retire_previous_after_commit(previous, execution)
            except Exception:
                logger.exception(
                    "Completed download %s but could not clean replacement files",
                    media_download_id,
                )
        return result
    except BaseException as exc:
        tracker.cancel(user_requested=isinstance(exc, (DownloadCanceled, RequestCanceled)))
        tracker.stop_reporting()
        session.rollback()
        if execution is not None and not committed:
            execution.rollback()
        if not isinstance(exc, Exception):
            raise
        finished = datetime.now(timezone.utc)
        metadata = download_attempt_metadata(
            started_at=started, finished_at=finished, is_redownload=is_redownload,
            **attempt, error=exc, lifecycle=asdict(tracker.snapshot()),
        )
        canceled = isinstance(exc, (DownloadCanceled, RequestCanceled))
        refused = None
        if not canceled and not isinstance(exc, EncryptedMediaError):
            try:
                # A Collection with automatic cookies uses the cookies file from the retry on.
                refused = _refused_access(media_download_id, exc)
            except Exception:
                logger.exception("Could not tell whether download %s was refused for lack of access", media_download_id)
            if refused:
                _tell_source_refused(media_download_id, refused)

        def record_failure(w: Session) -> None:
            if canceled:
                record_media_download_operation_history_once(
                    w, media_download_id, MediaDownloadHistoryAction.CANCELED,
                    operation_ids=operation_ids, metadata=metadata, occurred_at=finished,
                )
            elif refused:
                download = w.get(MediaDownloadBase, media_download_id)
                media = download.media if download is not None else None
                found = site_access(media.source_key, media_site_key(media), refused) if media is not None else None
                record_media_download_history_if_exists(
                    w, media_download_id, MediaDownloadHistoryAction.LOCKED,
                    metadata={**metadata, "access": refused, "access_label": found.label if found else None},
                    occurred_at=finished,
                )
            else:
                record_media_download_history_if_exists(
                    w, media_download_id, MediaDownloadHistoryAction.FAILED,
                    metadata=metadata, occurred_at=finished,
                )

        run_write_transaction(record_failure)
        if isinstance(exc, EncryptedMediaError) and run_write_transaction(
            lambda w: _mark_drm_protected(w, media_download_id)
        ):
            # Retrying cannot help; the item now shows it cannot be downloaded.
            return TaskResult(summary=f"{title} is protected by DRM and cannot be downloaded", outcome="failed")
        if refused is not None:
            label = run_write_transaction(lambda w: _lock_media(w, media_download_id, refused))
            if label is not None:
                # Retrying cannot help until VODLoft has the access, so the media waits, locked.
                return TaskResult(summary=f"{title} is locked: {label}", outcome="failed")
        raise
    finally:
        if execution is not None:
            execution.cleanup_workspace()
