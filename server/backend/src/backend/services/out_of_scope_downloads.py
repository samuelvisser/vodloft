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
from backend.types.download_profile_types import DownloadKeptBy, MediaDownloadArtifactStatus, OutOfScopePick
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


def out_of_scope_page(s: Session, profile: DownloadProfile, offset: int, limit: int) -> OutOfScopePage:
    """One page of ``out_of_scope_downloads``.

    Every page walks the filters again: the list it pages through is only known by walking them.
    """
    out = out_of_scope_downloads(s, profile)
    kept = [item for item in out if item.kept_by is not None]
    return OutOfScopePage(
        items=out[offset:offset + limit], offset=offset, limit=limit, has_more=offset + limit < len(out),
        total=len(out), size_bytes=_size(out), kept=len(kept), kept_size_bytes=_size(kept),
        filter_indexes=sorted({item.filter_index for item in out}),
    )


@dataclass(frozen=True)
class OutOfScopePreview:
    """What saving the edit form's filters would newly leave out, apart from what is out already."""
    media_download_ids: list[int]
    """The ones nothing keeps."""
    size_bytes: int
    kept: int
    kept_size_bytes: int


def newly_out_of_scope(s: Session, profile: DownloadProfile, selection: EpisodeSelection) -> OutOfScopePreview:
    before = {item.download.id for item in out_of_scope_downloads(s, profile)}
    new = [item for item in out_of_scope_downloads(s, profile, selection) if item.download.id not in before]
    remove = [item for item in new if item.kept_by is None]
    kept = [item for item in new if item.kept_by is not None]
    return OutOfScopePreview(
        media_download_ids=[item.download.id for item in remove], size_bytes=_size(remove),
        kept=len(kept), kept_size_bytes=_size(kept),
    )


def _starts_picked(pick: OutOfScopePick, item: OutOfScopeDownload) -> bool:
    if pick == OutOfScopePick.ALL:
        return True
    return pick == OutOfScopePick.NOT_KEPT and item.kept_by is None


def picked_out_of_scope(
        s: Session, profile_id: int, pick: OutOfScopePick, include: Iterable[int] = (), exclude: Iterable[int] = (),
) -> list[int]:
    """The downloads picked to delete that the saved profile still leaves out.

    ``pick`` says which ones start picked, then ``include`` and ``exclude`` add and take away
    the ones picked by hand. Read before the delete starts, so a download the profile covers
    again after a change in between is never deleted.
    """
    included, excluded = set(include), set(exclude)
    out = out_of_scope_downloads(s, get_profile(s, profile_id))
    return [
        item.download.id for item in out
        if item.download.id not in excluded and (item.download.id in included or _starts_picked(pick, item))
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
