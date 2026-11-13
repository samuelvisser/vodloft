"""Downloads a Download Profile no longer covers, deleted only when a person asks.

Narrowing a profile's Which episodes never deletes by itself, apart from a date line
on a profile that deletes older episodes. What the filters now leave out stays on
disk until someone chooses to delete it: when saving the narrower profile, or later
from the profile's page. Downloads that are kept, by hand or by a Keep filter, are
listed too, but are only deleted when the person picks them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import DownloadProfile, Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.operations.download_profiles import DownloadProfileDeleteOutOfScopeOperation
from backend.services.episode_filters import (
    EpisodeSelection, evaluate, filter_leaving_out, kept_by, published_at,
)
from backend.services.errors import NotFoundError, ServiceError
from backend.types.download_profile_types import DownloadKeptBy, MediaDownloadArtifactStatus
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import queue_operation_target_dispatch

_ON_DISK = (MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value)
_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class OutOfScopeDownload:
    download: EpisodeMediaDownload
    episode: Episode
    filter_index: int
    """The position of the filter that leaves the episode out."""
    kept_by: Optional[DownloadKeptBy]

    @property
    def published_at(self) -> Optional[datetime]:
        return published_at(self.episode)

    @property
    def on_disk(self) -> bool:
        return self.download.artifact_status in _ON_DISK

    @property
    def size_bytes(self) -> Optional[int]:
        return self.download.artifact_size_bytes if self.on_disk else None


@dataclass(frozen=True)
class DownloadProfileStatistics:
    downloaded: int
    """Downloads whose file is on disk."""
    storage_size_bytes: int
    wanted: int
    """Indexed episodes the profile downloads."""
    out_of_scope: int
    """Downloads its filters leave out that nothing keeps."""
    out_of_scope_kept: int
    """Downloads its filters leave out that are kept."""


def get_profile(s: Session, profile_id: int) -> DownloadProfile:
    profile = s.get(DownloadProfile, profile_id)
    if profile is None:
        raise NotFoundError("Download profile")
    return profile


def _downloads(s: Session, profile: DownloadProfile) -> list[EpisodeMediaDownload]:
    return list(s.scalars(
        select(EpisodeMediaDownload)
        .where(EpisodeMediaDownload.download_profile_id == profile.id)
        .options(selectinload(EpisodeMediaDownload.media))
    ))


def _newest_first(item: OutOfScopeDownload):
    moment = item.published_at
    return moment is not None, moment or _EARLIEST, item.episode.id, item.download.id


def _out_of_scope(evaluation, downloads: Iterable[EpisodeMediaDownload]) -> list[OutOfScopeDownload]:
    found = []
    for download in downloads:
        index = filter_leaving_out(evaluation, download)
        if index is not None:
            found.append(OutOfScopeDownload(
                download=download, episode=download.media, filter_index=index,
                kept_by=kept_by(evaluation, download),
            ))
    return sorted(found, key=_newest_first, reverse=True)


def out_of_scope_downloads(
        s: Session, profile: DownloadProfile, selection: Optional[EpisodeSelection] = None,
) -> list[OutOfScopeDownload]:
    """The profile's downloads that its filters leave out, newest episode first.

    With a selection, the filters of a form that is not saved yet decide instead.
    """
    downloads = _downloads(s, profile)
    if not downloads:
        return []
    return _out_of_scope(evaluate(s, selection or EpisodeSelection.of_profile(profile)), downloads)


def download_profile_statistics(s: Session, profile: DownloadProfile) -> DownloadProfileStatistics:
    """What the profile's page counts: its downloads, and which of them its filters leave out."""
    downloads = _downloads(s, profile)
    evaluation = evaluate(s, EpisodeSelection.of_profile(profile))
    on_disk = [download for download in downloads if download.artifact_status in _ON_DISK]
    out = _out_of_scope(evaluation, downloads)
    return DownloadProfileStatistics(
        downloaded=len(on_disk),
        storage_size_bytes=sum(download.artifact_size_bytes or 0 for download in on_disk),
        wanted=len(evaluation.wanted),
        out_of_scope=sum(1 for item in out if item.kept_by is None),
        out_of_scope_kept=sum(1 for item in out if item.kept_by is not None),
    )


def _size(items: Iterable[OutOfScopeDownload]) -> int:
    return sum(item.size_bytes or 0 for item in items)


@dataclass(frozen=True)
class OutOfScopePage:
    """A page of the profile's out-of-scope downloads, with totals for all of them."""
    items: list[OutOfScopeDownload]
    offset: int
    limit: int
    has_more: bool
    total: int
    size_bytes: int
    kept: int
    """How many of all of them are kept."""
    kept_size_bytes: int
    filter_indexes: list[int]
    """The filters that leave any of them out, so a page can tell when one filter leaves out all of them."""


def _page(out: list[OutOfScopeDownload], offset: int, limit: int) -> OutOfScopePage:
    kept = [item for item in out if item.kept_by is not None]
    return OutOfScopePage(
        items=out[offset:offset + limit], offset=offset, limit=limit, has_more=offset + limit < len(out),
        total=len(out), size_bytes=_size(out), kept=len(kept), kept_size_bytes=_size(kept),
        filter_indexes=sorted({item.filter_index for item in out}),
    )


def out_of_scope_page(s: Session, profile: DownloadProfile, offset: int, limit: int) -> OutOfScopePage:
    """One page of ``out_of_scope_downloads``.

    Every page walks the filters again: the list it pages through is only known by walking them.
    """
    return _page(out_of_scope_downloads(s, profile), offset, limit)


@dataclass(frozen=True)
class OutOfScopePreviewPage(OutOfScopePage):
    """A page of what saving the edit form's filters would newly leave out, apart from what is out already.

    The profile is saved before the delete starts, and after that nothing tells the new ones from
    the ones left out before. So the preview carries the ids of all of them, for the form to say
    exactly which ones to delete.
    """
    not_kept_ids: list[int]
    kept_ids: list[int]


def newly_out_of_scope(
        s: Session, profile: DownloadProfile, selection: EpisodeSelection, offset: int, limit: int,
) -> OutOfScopePreviewPage:
    before = {item.download.id for item in out_of_scope_downloads(s, profile)}
    new = [item for item in out_of_scope_downloads(s, profile, selection) if item.download.id not in before]
    page = _page(new, offset, limit)
    return OutOfScopePreviewPage(
        **{field: getattr(page, field) for field in OutOfScopePage.__dataclass_fields__},
        not_kept_ids=[item.download.id for item in new if item.kept_by is None],
        kept_ids=[item.download.id for item in new if item.kept_by is not None],
    )


def picked_out_of_scope(
        s: Session, profile_id: int, *, not_kept: bool, kept: bool,
        include: Iterable[int] = (), exclude: Iterable[int] = (),
) -> list[int]:
    """The downloads picked to delete that the saved profile still leaves out.

    ``not_kept`` and ``kept`` pick every download that nothing keeps and every kept one,
    then ``include`` and ``exclude`` add and take away the ones picked by hand. Read before
    the delete starts, so a download the profile covers again after a change in between is
    never deleted.
    """
    included, excluded = set(include), set(exclude)
    out = out_of_scope_downloads(s, get_profile(s, profile_id))
    return [
        item.download.id for item in out
        if item.download.id not in excluded
        and (item.download.id in included or (kept if item.kept_by is not None else not_kept))
    ]


def request_out_of_scope_delete(s: Session, profile_id: int, media_download_ids: Iterable[int]) -> dict[str, object]:
    """Start deleting these downloads and their files in the background."""
    profile = get_profile(s, profile_id)
    ids = tuple(media_download_ids)
    if not ids:
        raise ServiceError("Its filters leave none of the picked downloads out any more")
    operation = create_operation(s, DownloadProfileDeleteOutOfScopeOperation(profile, media_download_ids=ids))
    for download_id in ids:
        queue_operation_target_dispatch(s, operation.id, f"media_download:{download_id}")
    s.flush()
    return {"queued": True, "operation_id": operation.id, "downloads_queued": len(ids)}
