"""Rewriting the metadata of episode files that are already downloaded, without downloading them again.

A Local Media Profile embeds tags in a file, writes an NFO next to it, or both, when the episode downloads. What they
say can change afterwards: a new title or description, a genre or content rating set on the collection, or another
episode identification, which changes the season and episode numbers. Rewriting the metadata brings the files up to
date: the tags are rewritten by copying every stream of the file as it is (ffmpeg's stream copy, not a re-encode),
and the NFO is written again.

Each download remembers fingerprints of the metadata VODLoft last wrote to it completely: of the tags in the file and
of its NFO, or that it wrote none (``NO_METADATA``), or nothing when VODLoft does not know. A rewrite works out what
the file's profile asks for now and compares it with that: tags the profile wants that the file does not have, or has
otherwise, are written; tags it no longer wants are cleared; the same for the NFO, which is removed when the profile
no longer writes one. What matches is left alone, so a file the profile wants no tags in that has none is never
copied. The fingerprints are stored only once everything of the rewrite is written, so a file whose rewrite stopped
halfway still counts as not up to date.
"""
from __future__ import annotations

from backend.utils.helpers import name_in_text
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.db.core import run_write_transaction
from backend.db.models import Collection, CollectionLocalMediaProfile, Episode
from backend.operations.collections import CollectionMetadataRewriteOperation
from backend.services.errors import ServiceError
from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadAsset
from backend.services.download_metadata import build_episode_metadata, build_track_metadata
from backend.services.download_options import effective_metadata_mode
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.local_media_profile_types import keeps_tracks
from config.settings.submodels import MetadataMode
from downloader.ffmpeg import embed_metadata
from downloader.metadata import NO_METADATA, REWRITTEN_FFMPEG_TAGS, nfo_fingerprint, render_nfo, tags_fingerprint
from downloader.plan import EMBEDS_METADATA
from downloader.storage.identity import inspect_artifact
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import queue_operation_target_dispatch

logger = logging.getLogger(__name__)

_EMBEDS = (MetadataMode.EMBED, MetadataMode.EMBED_AND_NFO)
_NFOS = (MetadataMode.NFO, MetadataMode.EMBED_AND_NFO)


@dataclass(frozen=True)
class MetadataRewrite:
    """What to write for one download: its tags, its NFO, or both."""

    download_id: int
    media_path: Path
    tags: dict[str, str] | None
    """None when the file's tags stay as they are. Empty when they are cleared, as the profile embeds none now."""
    cleared_tags: tuple[str, ...]
    nfo: bytes | None
    nfo_path: Path | None
    """``nfo`` is None when the NFO stays as it is, or is removed."""
    removed_nfo: Path | None = None
    """The NFO to remove, as the profile writes none now."""


@dataclass(frozen=True)
class MetadataRewritePlan:
    rewrites: list[MetadataRewrite]
    """The files whose metadata changes."""
    untaggable: int = 0
    """Files whose format takes no tags, while the profile embeds them."""
    unchanged: int = 0
    """Files whose metadata is already what VODLoft would write."""


@dataclass
class MetadataRewriteCounts:
    files_considered: int = 0
    files_retagged: int = 0
    nfos_written: int = 0
    nfos_removed: int = 0
    """NFOs removed, as their profile writes none now."""
    files_unchanged: int = 0
    """Files whose metadata was already right."""
    files_skipped: int = 0
    """Files whose format takes no tags, while the profile embeds them."""
    files_failed: int = 0

    def summary(self) -> str:
        parts = []
        if self.files_retagged:
            parts.append(f"updated the tags of {self.files_retagged} file(s)")
        if self.nfos_written:
            parts.append(f"wrote {self.nfos_written} NFO file(s)")
        if self.nfos_removed:
            parts.append(f"removed {self.nfos_removed} NFO file(s)")
        if not parts:
            parts.append("nothing to rewrite")
        summary = "Metadata rewrite: " + " and ".join(parts)
        if self.files_unchanged:
            summary += f"; {self.files_unchanged} file(s) were already up to date"
        if self.files_skipped:
            summary += f"; {self.files_skipped} file(s) take no tags"
        if self.files_failed:
            summary += f"; {self.files_failed} file(s) failed"
        return summary

    def as_data(self) -> dict[str, int]:
        return {
            "files_considered": self.files_considered, "files_retagged": self.files_retagged,
            "nfos_written": self.nfos_written, "nfos_removed": self.nfos_removed, "files_unchanged": self.files_unchanged, "files_skipped": self.files_skipped, "files_failed": self.files_failed,
        }


@dataclass(frozen=True)
class MetadataRewriteRequest:
    operation_id: str
    local_media_profiles_queued: int


def request_metadata_rewrite(
        s: Session, collection: Collection, local_media_profile_id: int | None,
) -> MetadataRewriteRequest:
    """Start rewriting the metadata of the collection's downloaded files, for one Local Media Profile or each one
    that keeps metadata. ``s`` is a write transaction's session."""
    profile_ids = [
        profile_id for profile_id in s.scalars(
            select(EpisodeMediaDownload.local_media_profile_id).distinct()
            .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
            .where(
                Episode.collection_id == collection.id,
                EpisodeMediaDownload.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
            )
            .order_by(EpisodeMediaDownload.local_media_profile_id)
        )
        if local_media_profile_id is None or profile_id == local_media_profile_id
    ]
    profile_ids = [
        profile_id for profile_id in profile_ids
        if effective_metadata_mode(s.get(CollectionLocalMediaProfile, profile_id)) is not MetadataMode.NO_METADATA
    ]
    if not profile_ids:
        raise ServiceError(
            f"{name_in_text(collection.title)} has no downloaded files whose Local Media Profile keeps metadata",
            field="localMediaProfileId",
        )
    operation = create_operation(s, CollectionMetadataRewriteOperation(collection, local_media_profile_ids=profile_ids))
    for profile_id in profile_ids:
        queue_operation_target_dispatch(s, operation.id, f"profile:{profile_id}")
    s.flush()
    return MetadataRewriteRequest(operation_id=operation.id, local_media_profiles_queued=len(profile_ids))


def plan_metadata_rewrites(
        s: Session, *, collection_id: int, local_media_profile_id: int, episode_ids: Sequence[int] | None = None,
) -> MetadataRewritePlan:
    """The rewrites a collection's files of one Local Media Profile need, or only the files of ``episode_ids``: the
    files whose metadata would change. Reading only."""
    profile = s.get(CollectionLocalMediaProfile, local_media_profile_id)
    if profile is None:
        return MetadataRewritePlan([])
    mode = effective_metadata_mode(profile)
    build = build_track_metadata if keeps_tracks(profile) else build_episode_metadata
    downloads = s.scalars(
        select(EpisodeMediaDownload)
        .options(joinedload(EpisodeMediaDownload.assets))
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(
            Episode.collection_id == collection_id,
            EpisodeMediaDownload.local_media_profile_id == local_media_profile_id,
            EpisodeMediaDownload.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
            EpisodeMediaDownload.file_path.is_not(None),
            *([Episode.id.in_(episode_ids)] if episode_ids is not None else []),
        )
        .order_by(Episode.index, EpisodeMediaDownload.id)
    ).unique()
    rewrites: list[MetadataRewrite] = []
    untaggable = unchanged = 0
    for download in downloads:
        episode = download.media
        metadata = build(episode, episode.collection, profile)
        media_path = Path(download.file_path)
        # What the profile asks for now: the tags, when it embeds them and the file can take them, and the NFO.
        wanted_tags = None
        if mode in _EMBEDS:
            if media_path.suffix.lower().removeprefix(".") in EMBEDS_METADATA:
                wanted_tags = metadata.ffmpeg_tags()
            else:
                untaggable += 1
        wanted_nfo = render_nfo(metadata, kodi_safe=profile.kodi_safe_nfo) if mode in _NFOS else None
        tags = cleared = None
        if wanted_tags is not None:
            if tags_fingerprint(wanted_tags) != download.tags_fingerprint:
                tags, cleared = wanted_tags, metadata.cleared_ffmpeg_tags()
        elif download.tags_fingerprint not in (None, NO_METADATA):
            # VODLoft embedded tags the profile no longer wants: clear them.
            tags, cleared = {}, REWRITTEN_FFMPEG_TAGS
        nfo = nfo_path = removed_nfo = None
        if wanted_nfo is not None:
            if nfo_fingerprint(wanted_nfo) != download.nfo_fingerprint or not download.nfo_path:
                nfo = wanted_nfo
                nfo_path = Path(download.nfo_path) if download.nfo_path else media_path.with_name(media_path.stem + ".nfo")
        elif download.nfo_path and download.nfo_fingerprint not in (None, NO_METADATA):
            # VODLoft wrote an NFO the profile no longer wants: remove it.
            removed_nfo = Path(download.nfo_path)
        if tags is None and nfo is None and removed_nfo is None:
            unchanged += 1
            continue
        rewrites.append(MetadataRewrite(
            download_id=download.id, media_path=media_path, tags=tags, cleared_tags=cleared or (),
            nfo=nfo, nfo_path=nfo_path, removed_nfo=removed_nfo,
        ))
    return MetadataRewritePlan(rewrites, untaggable=untaggable, unchanged=unchanged)


def rewrite_metadata(rewrite: MetadataRewrite, *, should_cancel=None) -> None:
    """Write one download's tags and NFO. Runs outside any transaction: retagging copies the whole file."""
    if rewrite.tags is not None:
        embed_metadata(
            str(rewrite.media_path), rewrite.tags, cleared_metadata=rewrite.cleared_tags, should_cancel=should_cancel,
        )
    if rewrite.nfo is not None and rewrite.nfo_path is not None:
        _replace_file(rewrite.nfo_path, rewrite.nfo)
    if rewrite.removed_nfo is not None:
        rewrite.removed_nfo.unlink(missing_ok=True)


def record_metadata_rewrite(rewrite: MetadataRewrite) -> None:
    """Remember what the rewritten files are now, so VODLoft still knows them as its own, and the fingerprints of
    the metadata written. Only call it once ``rewrite_metadata`` wrote everything of the rewrite."""
    media = inspect_artifact(rewrite.media_path) if rewrite.tags is not None else None
    nfo = inspect_artifact(rewrite.nfo_path) if rewrite.nfo is not None and rewrite.nfo_path is not None else None

    def record(w: Session) -> None:
        download = w.get(EpisodeMediaDownload, rewrite.download_id)
        if download is None:
            return
        if media is not None:
            download.artifact_stat_dev, download.artifact_stat_ino = media.stat_dev, media.stat_ino
            download.artifact_size_bytes, download.artifact_fingerprint = media.size_bytes, media.fingerprint
            download.tags_fingerprint = tags_fingerprint(rewrite.tags) if rewrite.tags else NO_METADATA
        if nfo is not None:
            asset = next((asset for asset in download.assets if asset.asset_key == "nfo"), None)
            if asset is None:
                asset = MediaDownloadAsset(
                    asset_key="nfo", kind="nfo", path=str(rewrite.nfo_path),
                    suffix=rewrite.nfo_path.name[len(rewrite.media_path.stem):],
                )
                download.assets.append(asset)
            asset.size_bytes, asset.fingerprint = nfo.size_bytes, nfo.fingerprint
            download.nfo_fingerprint = nfo_fingerprint(rewrite.nfo)
        if rewrite.removed_nfo is not None:
            for asset in [asset for asset in download.assets if asset.kind == "nfo"]:
                download.assets.remove(asset)
            download.nfo_fingerprint = NO_METADATA

    run_write_transaction(record)


def _replace_file(path: Path, content: bytes) -> None:
    part = path.with_name(path.name + ".part")
    try:
        with part.open("wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
