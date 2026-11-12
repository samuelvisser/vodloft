"""Domain path mapping; all physical relocation is handled by the downloader."""
from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models.media_download import MediaDownloadBase
from backend.services.media_download_history import record_media_download_history
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from downloader import hls_asset_marker, hls_asset_root
from downloader.storage.identity import inspect_artifact
from downloader.storage.relocation import PathMove, RelocationTransaction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadRelocation:
    download_id: int
    source: Path
    destination: Path
    paths: tuple[PathMove, ...]
    assets: tuple[tuple[str, Path], ...]
    recovered: bool = False


def plan_download_relocation(download: MediaDownloadBase, source: Path, destination: Path) -> DownloadRelocation:
    recovered = not source.exists()
    if recovered:
        identity = inspect_artifact(destination)
        if not (identity.fingerprint == download.artifact_fingerprint and identity.size_bytes == download.artifact_size_bytes):
            raise FileExistsError('Cannot prove ownership of the recovered destination')
    paths = [] if recovered else [PathMove(source, destination)]
    assets = []
    for asset in download.assets:
        target = destination.with_name(destination.stem + asset.suffix)
        path = Path(asset.path)
        if path.exists():
            paths.append(PathMove(path, target))
            assets.append((asset.asset_key, target))
        elif recovered and target.exists():
            identity = inspect_artifact(target)
            if identity.fingerprint != asset.fingerprint or identity.size_bytes != asset.size_bytes:
                raise FileExistsError(f'Cannot prove ownership of recovered sidecar: {target}')
            assets.append((asset.asset_key, target))
    if source.suffix.lower() == '.m3u8' and hls_asset_marker(source).is_file():
        paths.append(PathMove(hls_asset_root(source), hls_asset_root(destination)))
    return DownloadRelocation(download.id, source, destination, tuple(paths), tuple(assets), recovered)


def number_shared_destinations(planned: Sequence[tuple[Path, Path]]) -> list[Path]:
    """The destination of each ``(source, destination)`` pair, numbered where several files share one.

    The downloader stores a file whose name is taken as ``name-1.ext``, ``name-2.ext`` and so on, for
    example two extras of one movie with the same type when the template tells them apart only by
    ``media_type``. A rename numbers them the same way: a file that already has one of the shared
    name's numbered forms keeps it, and the others take the lowest free number in the given order.
    A number is free when no other planned file claims it and no file outside this rename is there.
    """
    counts = Counter(destination for _source, destination in planned)
    sources = {source for source, _destination in planned}
    result = [destination for _source, destination in planned]
    taken = {destination for destination, count in counts.items() if count == 1}
    for shared in (destination for destination, count in counts.items() if count > 1):
        indexes = [index for index, (_source, destination) in enumerate(planned) if destination == shared]
        pending = []
        for index in indexes:
            source = planned[index][0]
            if _is_numbered_form(source, shared) and source not in taken:
                taken.add(source)
                result[index] = source
            else:
                pending.append(index)
        number = 0
        for index in pending:
            while True:
                candidate = shared if number == 0 else shared.with_name(f"{shared.stem}-{number}{shared.suffix}")
                number += 1
                if candidate not in taken and (candidate in sources or not candidate.exists()):
                    break
            taken.add(candidate)
            result[index] = candidate
    return result


def _is_numbered_form(path: Path, destination: Path) -> bool:
    return (
        path.parent == destination.parent and path.suffix == destination.suffix
        and re.fullmatch(re.escape(destination.stem) + r"(-[1-9][0-9]*)?", path.stem) is not None
    )


def filter_relocation_conflicts(moves: list[DownloadRelocation]) -> tuple[list[DownloadRelocation], list[DownloadRelocation]]:
    """Skip whole downloads transitively while retaining safe internal cycles."""
    remaining, skipped = list(moves), []
    while remaining:
        sources = {path.source for move in remaining for path in move.paths}
        blocked = [move for move in remaining if any(path.destination.exists() and path.destination not in sources for path in move.paths)]
        if not blocked:
            break
        remaining = [move for move in remaining if move not in blocked]
        skipped.extend(blocked)
        for move in blocked:
            logger.warning('Skipping rename for media download %s: %s -> %s; destination already exists', move.download_id, move.source, move.destination)
    return remaining, skipped


def relocate_downloads(
    moves: list[DownloadRelocation], *, progress=None, skip_existing: bool = False,
    reason: str = 'output_template_rename',
) -> tuple[int, int]:
    """Move the files, then record where they went. No transaction stays open while files are copied."""
    destinations = [path.destination for move in moves for path in move.paths]
    if len(destinations) != len(set(destinations)):
        raise FileExistsError('Multiple managed artifacts resolve to the same destination')
    skipped = []
    if skip_existing:
        moves, skipped = filter_relocation_conflicts(moves)
    paths = tuple(path for move in moves for path in move.paths)
    transaction = RelocationTransaction(paths, progress if callable(progress) else lambda: False)
    try:
        transaction.execute(lambda value: progress.set(value, 'Renaming media and auxiliary files') if progress else None)
        identities = [inspect_artifact(move.destination) for move in moves]
        run_write_transaction(lambda session: _record_relocations(session, moves, identities, reason))
    except BaseException:
        transaction.rollback()
        raise
    return len(moves), len(skipped)


def _record_relocations(session: Session, moves: list[DownloadRelocation], identities, reason: str) -> None:
    for move, identity in zip(moves, identities):
        download = session.get(MediaDownloadBase, move.download_id)
        if download is None:
            raise RuntimeError('Download was deleted while renaming')
        download.file_path = str(move.destination)
        download.artifact_status, download.artifact_error = 'available', None
        download.artifact_stat_dev, download.artifact_stat_ino = identity.stat_dev, identity.stat_ino
        download.artifact_size_bytes, download.artifact_fingerprint = identity.size_bytes, identity.fingerprint
        targets = dict(move.assets)
        for asset in list(download.assets):
            if asset.asset_key in targets:
                asset.path = str(targets[asset.asset_key])
            else:
                download.assets.remove(asset)
        record_media_download_history(session, download.id, MediaDownloadHistoryAction.ARTIFACT_RENAMED, metadata={
            'old_path': str(move.source), 'new_path': str(move.destination),
            'reason': reason, 'recovered': move.recovered,
        })
