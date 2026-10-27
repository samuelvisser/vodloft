from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from backend.api.endpoints.sources.service import resolve_link
from backend.api.models.operations import TaskOperationRead
from backend.api.models.quick_download import QuickDownloadAPICreate, QuickDownloadAPIRead, QuickDownloadsAPIRead
from backend.services.quick_downloads import (
    QuickChoice,
    QuickDownloadRequest,
    check_quick_downloadable,
    deliveries,
    discard_quick_download,
    mark_delivered,
    ready_quick_download,
)
from config import get_settings
from downloader.storage.quick import QuickFolder, list_quick_folders, new_quick_download_id
from sources import LinkKind, get_source
from task_manager.scheduler.operation_control import cancel_operation
from task_manager.scheduler.operations import get_operation
from task_manager.tasks.media_download_operations import dispatch_queued_media_download_operations
from task_manager.tasks.quick_download_operations import (
    active_quick_download_operations,
    create_quick_download_operation,
)

_CHUNK = 1024 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def start_quick_download(s: Session, body: QuickDownloadAPICreate) -> dict:
    """Look up the link, refuse what cannot be downloaded, and queue the download."""
    link = resolve_link(s, body.url, body.source_key)
    source = get_source(link.source.id)
    kind = LinkKind(link.kind)
    check_quick_downloadable(
        source, kind, drm_protected=link.drm_protected, needs_subscription=link.needs_subscription,
    )
    request = QuickDownloadRequest(
        id=new_quick_download_id(),
        source_key=source.id,
        kind=kind,
        slug=link.slug,
        url=link.url,
        title=link.preview.title,
        description=link.preview.description,
        image_url=link.preview.image_url,
        author_name=link.preview.author_name,
        choice=QuickChoice(**body.choice.model_dump()),
    )
    operation = create_quick_download_operation(s, request)
    dispatch_queued_media_download_operations(s)
    return {"queued": True, "operation_id": operation.id, "quick_download_id": request.id}


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
