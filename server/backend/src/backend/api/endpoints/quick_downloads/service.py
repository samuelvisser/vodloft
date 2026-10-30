from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from backend.api.endpoints.sources.service import resolve_link
from backend.api.models.operations import TaskOperationRead
from backend.api.models.source import ResolvedLinkAPIRead
from backend.api.models.quick_download import (
    QuickDownloadAPICreate,
    QuickDownloadAPIRead,
    QuickDownloadHistoryAPIRead,
    QuickDownloadOptionsAPIRead,
    QuickDownloadOptionsAPIRequest,
    QuickDownloadsAPIRead,
)
from backend.services.quick_downloads import (
    QuickChoice,
    QuickDownloadRefused,
    QuickDownloadRequest,
    QuickRules,
    apply_quick_rules,
    check_quick_choice,
    check_quick_rules,
    estimate_choice,
    check_quick_downloadable,
    deliveries,
    discard_quick_download,
    mark_delivered,
    QuickOptions,
    quick_options,
    ready_quick_download,
)
from backend.services import quick_download_history as history
from backend.services.source_requests import asking_source
from config import get_settings
from downloader.storage.quick import QuickFolder, list_quick_folders, new_quick_download_id
from sources import Feature, LinkKind, get_source
from task_manager.scheduler.operation_control import cancel_operation
from task_manager.scheduler.operations import get_operation
from task_manager.tasks.media_download_operations import dispatch_queued_media_download_operations
from task_manager.tasks.quick_download_operations import (
    active_quick_download_operations,
    create_quick_download_operation,
    record_quick_download_delivered,
)

_CHUNK = 1024 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def start_quick_download(s: Session, body: QuickDownloadAPICreate) -> dict:
    """Look up the link, refuse what cannot be downloaded or what the rules do not allow, and queue it."""
    link = resolve_link(s, body.url, body.source_key)
    source = get_source(link.source.id)
    kind = LinkKind(link.kind)
    try:
        choice = QuickChoice(**body.choice.model_dump())
    except ValueError as exc:
        raise QuickDownloadRefused(str(exc)) from exc
    rules = QuickRules.from_settings()
    choice = apply_quick_rules(source, choice, rules)
    quick_id = new_quick_download_id()
    try:
        check_quick_downloadable(
            source, kind, drm_protected=link.drm_protected, needs_subscription=link.needs_subscription,
        )
    except QuickDownloadRefused as exc:
        if link.drm_protected or link.needs_subscription:
            # Remembered on its own, because the refusal rolls the request back.
            history.record_refused(
                quick_id=quick_id, title=link.preview.title, source_key=source.id, source_name=source.name,
                url=link.url, choice=choice, message="Protected by DRM" if link.drm_protected else "Needs a subscription",
            )
        raise
    check_quick_choice(source, choice)
    estimate = None
    duration = None
    if source.has(Feature.FORMAT_CHOICES) and (rules.max_bytes or rules.max_duration or rules.fixed_codec):
        with asking_source(f"{source.name} could not list the formats of this video"):
            options = quick_options(source, link.url)
        estimate = estimate_choice(options, choice)
        duration = options.duration
    check_quick_rules(
        source, choice, rules, size_bytes=estimate.size_bytes if estimate else None, duration=duration,
        codecs=estimate.codecs if estimate else None,
    )
    request = QuickDownloadRequest(
        id=quick_id,
        source_key=source.id,
        kind=kind,
        slug=link.slug,
        url=link.url,
        title=link.preview.title,
        description=link.preview.description,
        image_url=link.preview.image_url,
        author_name=link.preview.author_name,
        choice=choice,
    )
    operation = create_quick_download_operation(s, request)
    history.record_started(request, source_name=source.name, session=s)
    dispatch_queued_media_download_operations(s)
    return {"queued": True, "operation_id": operation.id, "quick_download_id": request.id}


@dataclass(frozen=True)
class _OptionsSource:
    link: ResolvedLinkAPIRead
    refused: str | None = None
    options: QuickOptions | None = None


def quick_download_options(s: Session, body: QuickDownloadOptionsAPIRequest) -> QuickDownloadOptionsAPIRead:
    """Look up the link and what it can be downloaded as, or why it cannot be."""
    link = resolve_link(s, body.url, body.source_key)
    source = get_source(link.source.id)
    try:
        check_quick_downloadable(
            source, LinkKind(link.kind), drm_protected=link.drm_protected, needs_subscription=link.needs_subscription,
        )
    except QuickDownloadRefused as exc:
        return QuickDownloadOptionsAPIRead.model_validate(_OptionsSource(link, refused=str(exc)))
    with asking_source(f"{source.name} could not list the formats of this video"):
        options = quick_options(source, link.url)
    return QuickDownloadOptionsAPIRead.model_validate(_OptionsSource(link, options=options))


def _ready() -> list[QuickFolder]:
    folders = list_quick_folders(get_settings().download_settings.temporary_download_root)
    return sorted((f for f in folders if f.manifest is not None), key=lambda f: f.manifest.created_at, reverse=True)


def list_quick_downloads(s: Session) -> QuickDownloadsAPIRead:
    active = [get_operation(operation.id) for operation in active_quick_download_operations(s)]
    return QuickDownloadsAPIRead(
        active=[TaskOperationRead.model_validate(snapshot) for snapshot in active if snapshot is not None],
        ready=[QuickDownloadAPIRead.model_validate(folder.manifest) for folder in _ready()],
    )


def remove_quick_download(s: Session, quick_id: str) -> bool:
    """Cancel a quick download that is still working, or delete its ready file."""
    found = False
    for operation in active_quick_download_operations(s):
        if (operation.context or {}).get("quick_download_id") == quick_id:
            cancel_operation(operation.id, reason="Canceled by user")
            found = True
    return discard_quick_download(quick_id) or found


class RangeNotSatisfiable(ValueError):
    pass


@dataclass(frozen=True)
class FileDelivery:
    """One response for a ready file: the whole file or one byte range of it."""

    quick_id: str
    path: str
    file_name: str
    size: int
    start: int
    end: int
    """Exclusive."""
    partial: bool

    @property
    def headers(self) -> dict[str, str]:
        fallback = self.file_name.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
        headers = {
            "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(self.file_name)}",
            "Content-Length": str(self.end - self.start),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            # A buffering reverse proxy would take every byte at once and make
            # the file look delivered while the browser is still receiving it.
            "X-Accel-Buffering": "no",
        }
        if self.partial:
            headers["Content-Range"] = f"bytes {self.start}-{self.end - 1}/{self.size}"
        return headers

    @property
    def media_type(self) -> str:
        return mimetypes.guess_type(self.file_name)[0] or "application/octet-stream"

    def chunks(self) -> Iterator[bytes]:
        """The bytes, recording each chunk as sent once the server has handed it on."""
        with open(self.path, "rb") as handle:
            handle.seek(self.start)
            position = self.start
            while position < self.end:
                chunk = handle.read(min(_CHUNK, self.end - position))
                if not chunk:
                    break
                yield chunk
                # Resumed only after the chunk went out; a dropped connection never gets here.
                if deliveries.sent(self.quick_id, position, position + len(chunk), self.size):
                    mark_delivered(self.quick_id)
                    record_quick_download_delivered(self.quick_id, self.file_name)
                position += len(chunk)


def file_delivery(quick_id: str, range_header: str | None) -> FileDelivery | None:
    found = ready_quick_download(quick_id)
    if found is None or found.manifest is None or found.file is None:
        return None
    size = found.file.stat().st_size
    start, end, partial = 0, size, False
    if range_header:
        match = _RANGE.match(range_header.strip())
        # Several ranges at once, or a header that is not a byte range, get the whole file.
        if match is not None:
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(size, int(last) + 1) if last else size
            elif last:
                start = max(0, size - int(last))
            else:
                raise RangeNotSatisfiable(size)
            if start >= size or start >= end:
                raise RangeNotSatisfiable(size)
            partial = True
    return FileDelivery(quick_id, str(found.file), found.manifest.file_name, size, start, end, partial)


def quick_download_history(s: Session) -> list[QuickDownloadHistoryAPIRead]:
    return [QuickDownloadHistoryAPIRead.model_validate(row) for row in history.list_history(s)]


def clear_quick_download_history(s: Session) -> int:
    removed = history.clear_history(s)
    s.commit()
    return removed
