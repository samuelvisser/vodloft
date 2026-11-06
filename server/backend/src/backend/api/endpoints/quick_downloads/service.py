from __future__ import annotations

import logging
import mimetypes
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from backend.api.endpoints.sources.service import preferred_sources, resolve_link
from backend.api.models.operations import TaskOperationRead
from backend.api.models.source import ResolvedLinkAPIRead
from backend.api.models.quick_download import (
    QuickDownloadAPICreate,
    QuickDownloadAPIRead,
    QuickDownloadActiveAPIRead,
    QuickDownloadHistoryAPIRead,
    QuickDownloadOptionsAPIRead,
    QuickDownloadOptionsAPIRequest,
    QuickDownloadPreviewAPIRead,
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
from backend.api.models.settings import QuickDownloadPreferencesValue, QuickDownloadSettingsForUser
from backend.db.core import get_session, run_write_transaction
from backend.db.models import User
from backend.security.access import Access, Area, Level
from backend.services import quick_download_history as history
from backend.services.source_requests import asking_source
from config import get_settings
from downloader.storage.quick import QuickFolder, list_quick_folders, new_quick_download_id
from sources import Feature, LinkKind, get_source, sources_for
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

logger = logging.getLogger(__name__)


def start_quick_download(access: Access, body: QuickDownloadAPICreate) -> dict:
    """Look up the link, refuse what cannot be downloaded or what the rules do not allow, and queue it.

    The Source is asked before the short write transaction that queues the download.
    """
    s = get_session()
    try:
        link = resolve_link(s, access, body.url, body.source_key)
    finally:
        s.rollback()
        s.close()
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
                owner=owner_of(access),
            )
        raise
    check_quick_choice(source, choice)
    request = _request(access, link, quick_id, choice)
    estimate = None
    duration = None
    if rules.max_bytes or rules.max_duration or (rules.fixed_codec and source.has(Feature.FORMAT_CHOICES)):
        with asking_source(f"{source.name} could not list the formats of this video"):
            options = quick_options(source, link.url, request)
        estimate = estimate_choice(options, choice)
        duration = options.duration
    check_quick_rules(
        source, choice, rules, size_bytes=estimate.size_bytes if estimate else None, duration=duration,
        codecs=estimate.codecs if estimate else None,
    )

    def queue(s: Session) -> dict:
        operation = create_quick_download_operation(s, request)
        history.record_started(request, source_name=source.name, session=s)
        dispatch_queued_media_download_operations(s)
        return {"queued": True, "operation_id": operation.id, "quick_download_id": request.id}

    return run_write_transaction(queue)


def _request(access: Access, link: ResolvedLinkAPIRead, quick_id: str, choice: QuickChoice) -> QuickDownloadRequest:
    return QuickDownloadRequest(
        id=quick_id,
        source_key=link.source.id,
        kind=LinkKind(link.kind),
        slug=link.slug,
        url=link.url,
        title=link.preview.title,
        description=link.preview.description,
        image_url=link.preview.image_url,
        author_name=link.preview.author_name,
        choice=choice,
        members_only=access.members_only,
        owner=owner_of(access),
    )


@dataclass(frozen=True)
class _OptionsSource:
    link: ResolvedLinkAPIRead
    refused: str | None = None
    options: QuickOptions | None = None


def quick_download_preview(s: Session, access: Access, body: QuickDownloadOptionsAPIRequest) -> QuickDownloadPreviewAPIRead | None:
    """The title and thumbnail of a link from a faster lookup than the full one, or None.

    Only Sources and domains the user may use are asked; anything else, and any
    failure, gives None, and the full lookup says why.
    """
    url = body.url.strip()
    if "://" not in url:
        url = f"https://{url}"
    candidates = [
        source for source in sources_for(url, preferred_sources(s))
        if access.allows_link(source.id, url) and (body.source_key is None or source.id == body.source_key)
    ]
    for source in candidates:
        try:
            preview = source.preview(url)
        except Exception:  # noqa: BLE001 - a preview is a nicety; the full lookup reports problems.
            logger.debug("No quick preview from %s for %s", source.id, url, exc_info=True)
            return None
        if preview is not None:
            return QuickDownloadPreviewAPIRead(
                source_key=source.id, title=preview.title, image_url=preview.image_url,
                author_name=preview.author_name, site=preview.site,
            )
        # The first Source asked is the one the full lookup asks first too.
        return None
    return None


def quick_download_options(s: Session, access: Access, body: QuickDownloadOptionsAPIRequest) -> QuickDownloadOptionsAPIRead:
    """Look up the link and what it can be downloaded as, or why it cannot be."""
    link = resolve_link(s, access, body.url, body.source_key)
    source = get_source(link.source.id)
    try:
        check_quick_downloadable(
            source, LinkKind(link.kind), drm_protected=link.drm_protected, needs_subscription=link.needs_subscription,
        )
    except QuickDownloadRefused as exc:
        return QuickDownloadOptionsAPIRead.model_validate(_OptionsSource(link, refused=str(exc)))
    with asking_source(f"{source.name} could not list the formats of this video"):
        options = quick_options(source, link.url, _request(access, link, "", QuickChoice()))
    return QuickDownloadOptionsAPIRead.model_validate(_OptionsSource(link, options=options))


def owner_of(access: Access) -> str | None:
    """How a quick download remembers who asked: the user's id, or None without user accounts."""
    return owner_of_user_id(access.user_id)


def owner_of_user_id(user_id: int | None) -> str | None:
    return None if user_id is None else str(user_id)


def sees_everyones(access: Access) -> bool:
    return access.allows(Area.QUICK_DOWNLOADS, Level.MANAGE)


def _mine(access: Access, owner: str | None) -> bool:
    return sees_everyones(access) or (owner is not None and owner == owner_of(access))


def _my_operations(s: Session, access: Access):
    return [
        operation for operation in active_quick_download_operations(s)
        if sees_everyones(access) or (access.user_id is not None and operation.requested_by_user_id == access.user_id)
    ]


def _ready() -> list[QuickFolder]:
    folders = list_quick_folders(get_settings().download_settings.quick_download_root)
    return sorted((f for f in folders if f.manifest is not None), key=lambda f: f.manifest.created_at, reverse=True)


def list_quick_downloads(s: Session, access: Access) -> QuickDownloadsAPIRead:
    """The user's own quick downloads, or everyone's for those who manage Quick downloads."""
    operations = _my_operations(s, access)
    manifests = [folder.manifest for folder in _ready() if _mine(access, folder.manifest.owner)]
    names = _owner_names(s, access, [
        *(_operation_owner(operation) for operation in operations),
        *(manifest.owner for manifest in manifests),
    ])
    active = [(get_operation(operation.id), _operation_owner(operation)) for operation in operations]
    return QuickDownloadsAPIRead(
        active=[
            QuickDownloadActiveAPIRead(operation=TaskOperationRead.model_validate(snapshot), owner_name=names.get(owner))
            for snapshot, owner in active if snapshot is not None
        ],
        ready=[
            QuickDownloadAPIRead.model_validate(manifest).model_copy(update={"owner_name": names.get(manifest.owner)})
            for manifest in manifests
        ],
    )


def _operation_owner(operation) -> str | None:
    """The owner of a running quick download, in the form a ready file's manifest keeps it."""
    return owner_of_user_id(operation.requested_by_user_id)


def _owner_names(s: Session, access: Access, owners) -> dict[str | None, str]:
    """Usernames by owner, for those who see everyone's quick downloads with user accounts on."""
    if access.user_id is None or not sees_everyones(access):
        return {}
    ids = {int(owner) for owner in owners if owner and owner.isdigit()}
    if not ids:
        return {}
    return {str(user.id): user.username for user in s.query(User).filter(User.id.in_(ids))}


def remove_quick_download(s: Session, access: Access, quick_id: str) -> bool:
    """Cancel a quick download that is still working, or delete its ready file."""
    found = False
    for operation in _my_operations(s, access):
        if (operation.context or {}).get("quick_download_id") == quick_id:
            cancel_operation(operation.id, reason="Canceled by user")
            found = True
    ready = ready_quick_download(quick_id)
    if ready is not None and ready.manifest is not None and not _mine(access, ready.manifest.owner):
        return found
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


def file_delivery(access: Access, quick_id: str, range_header: str | None) -> FileDelivery | None:
    found = ready_quick_download(quick_id)
    if found is None or found.manifest is None or found.file is None:
        return None
    if not _mine(access, found.manifest.owner):
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


def quick_download_history(s: Session, access: Access) -> list[QuickDownloadHistoryAPIRead]:
    rows = history.list_history(s, owner=owner_of(access), everyone=sees_everyones(access))
    names = _owner_names(s, access, (row.owner for row in rows))
    return [
        QuickDownloadHistoryAPIRead.model_validate(row).model_copy(update={"owner_name": names.get(row.owner)})
        for row in rows
    ]


def clear_quick_download_history(s: Session, access: Access) -> int:
    return history.clear_history(s, owner=owner_of(access), everyone=sees_everyones(access))


# Each user's own defaults -----------------------------------------------------


def quick_download_settings_for(s: Session, access: Access) -> QuickDownloadSettingsForUser:
    """Settings › Quick download as this user sees it.

    The rules are the install's for everyone. A user who saved their own
    defaults starts from those, unless the install locks everyone to its own.
    """
    quick = get_settings().quick_download
    result = QuickDownloadSettingsForUser.model_validate(quick)
    if access.user_id is None or quick.lock_to_defaults:
        return result
    user = s.get(User, access.user_id)
    saved = user.quick_download_preferences if user is not None else None
    if not saved:
        return result
    try:
        own = QuickDownloadPreferencesValue.model_validate(saved)
    except ValueError:
        # Saved before a choice was taken away; the install's defaults stand.
        return result
    return result.model_copy(update={**own.model_dump(), "own_defaults": True})


def save_quick_download_preferences(
    s: Session, access: Access, preferences: QuickDownloadPreferencesValue | None,
) -> QuickDownloadSettingsForUser:
    """Keep (or with None, forget) the user's own Quick download defaults."""
    if access.user_id is None:
        raise PreferencesNeedAnAccount(
            "Without user accounts, VODLoft keeps one set of defaults: change them in Settings › Quick download."
        )
    user = s.get(User, access.user_id)
    if user is None:
        raise PreferencesNeedAnAccount("Your account no longer exists.")
    user.quick_download_preferences = None if preferences is None else preferences.model_dump(by_alias=False)
    s.flush()
    return quick_download_settings_for(s, access)


class PreferencesNeedAnAccount(Exception):
    """Own defaults belong to a user account."""
