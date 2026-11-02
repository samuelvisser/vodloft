"""Applying an import plan's records: WireLoft's shows, episodes, movies, profiles and downloads.

A record names VODLoft's own kind of row (``RecordPlan.kind``) with its fields
by VODLoft's names. This module creates it, or links it when VODLoft already
has the same record (``RecordPlan.identity``, such as a Daily Wire id), and
resolves its references to VODLoft ids. Like the rest of the import it keeps a
ledger (``ImportLink``): a repeat run updates only fields the person did not
change in VODLoft, and adds what is new.

Downloads are adopted where they are. A file the other program recorded is
taken when it is still there; its stored identity is compared with the file,
not recomputed into a new kind of identity. A file VODLoft can't reach keeps
its row, marked as not downloaded and not to be downloaded again, so a later
import adopts it once the folder is reachable.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, inspect as sa_inspect, select
from sqlalchemy.orm import Session

from importer.contract import ImportPlan, RecordPlan, Reference

from backend.db.models import (
    Collection,
    CollectionLocalAsset,
    CustomIndexState,
    DownloadProfile,
    Episode,
    EpisodeMediaDownload,
    LocalMediaProfileBase,
    MediaDownloadBase,
    Movie,
    MovieExtra,
    MovieExtraMediaDownload,
    MovieMediaDownload,
    Season,
)
from backend.db.models.media_download.MediaDownloadAsset import MediaDownloadAsset
from backend.db.models.media_download.MediaDownloadHistory import MediaDownloadHistory
from backend.db.models.media_item.MovieExtraSource import MovieExtraSource
from backend.db.models.stream_profile.RssStreamProfile import RssStreamProfile
from backend.services.adoption import AdoptionError, real_path
from backend.services.media_download_history import record_media_download_history
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.types.media_download_history_types import MediaDownloadHistoryAction
from downloader.storage.identity import inspect_artifact

if TYPE_CHECKING:
    from backend.db.models import ImportLink

_MODELS: dict[str, type] = {
    "collection": Collection,
    "season": Season,
    "episode": Episode,
    "movie": Movie,
    "movie_extra_source": MovieExtraSource,
    "movie_extra": MovieExtra,
    "download_profile": DownloadProfile,
    "stream_profile": RssStreamProfile,
    "custom_index_state": CustomIndexState,
    "collection_asset": CollectionLocalAsset,
}
_DOWNLOAD_MODELS = {"episode": EpisodeMediaDownload, "movie": MovieMediaDownload, "movie_extra": MovieExtraMediaDownload}
_SLUGGED = {"collection", "season", "episode", "movie", "movie_extra_source"}
_NOT_COMPARED = {"artifact_stat_dev", "artifact_stat_ino"}
_WIRELOFT_HLS_MARKER = ".wireloft-hls-bundle"
_VODLOFT_HLS_MARKER = ".vodloft-hls-bundle"
_AVAILABLE = MediaDownloadArtifactStatus.AVAILABLE.value
_ABSENT = MediaDownloadArtifactStatus.ABSENT.value


@dataclass
class RecordResult:
    """What applying the records did, for the run's report."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    download_profiles: list[tuple[int, bool]] = field(default_factory=list)
    """Download Profiles this run created (off), each with whether it should be on once the import is done."""

    def add(self, kind: str, subject: str, message: str) -> None:
        self.entries.append({"kind": kind, "subject": subject, "message": message})


def _hash(value: object) -> str:
    from backend.services.imports import _hash as import_hash

    return import_hash(value)


def _attributes(model: type) -> dict[str, Any]:
    """Column name -> (attribute name, column) of a model, across its joined tables."""
    mapper = sa_inspect(model)
    return {prop.columns[0].name: (prop.key, prop.columns[0]) for prop in mapper.column_attrs}


def _python_type(column) -> type | None:
    column_type = column.type
    impl = getattr(column_type, "impl_instance", None) or column_type
    try:
        return impl.python_type
    except NotImplementedError:
        return None


def _convert(column, value: object) -> object:
    if value is None:
        return None
    kind = _python_type(column)
    if kind is datetime and isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if kind is date and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if kind is bool:
        return bool(value)
    if isinstance(column.type, JSON) and isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class _Unresolved(LookupError):
    pass


class _Applier:
    def __init__(self, session: Session, plan: ImportPlan, profiles: dict[str, LocalMediaProfileBase | None],
                 links: dict[tuple[str, str], "ImportLink"], run, skip_collections: set[str]) -> None:
        self.session = session
        self.plan = plan
        self.profiles = profiles
        self.links = links
        self.run = run
        self.skip_collections = skip_collections
        self.resolved: dict[tuple[str, str], int] = {}
        self.skipped: set[tuple[str, str]] = set()
        self.created: set[tuple[str, str]] = set()
        self.result = RecordResult()

    # References ----------------------------------------------------------------

    def resolve(self, reference: Reference) -> int:
        if reference.kind == "profile":
            profile = self.profiles.get(reference.external_id)
            if profile is None:
                raise _Unresolved(f"its Local Media Profile {reference.external_id} was not imported")
            return profile.id
        key = (reference.kind, reference.external_id)
        if key in self.resolved:
            return self.resolved[key]
        raise _Unresolved(f"the {reference.kind.replace('_', ' ')} it belongs to was not imported")

    def _identity_filters(self, model: type, record: RecordPlan) -> list | None:
        if not record.identity:
            return None
        attributes = _attributes(model)
        filters = []
        for name, value in record.identity.items():
            if isinstance(value, Reference):
                value = self.resolve(value)
            if name not in attributes:
                return None
            attribute, column = attributes[name]
            filters.append(getattr(model, attribute) == _convert(column, value))
        return filters

    def _find(self, model: type, record: RecordPlan):
        link = self.links.get((record.kind, record.external_id))
        if link is not None and link.entity_id:
            found = self.session.get(model, link.entity_id)
            if found is not None:
                return found, link
        filters = self._identity_filters(model, record)
        if filters:
            found = self.session.scalar(select(model).where(*filters).limit(1))
            if found is not None:
                return found, None
        return None, None

    def _values(self, model: type, record: RecordPlan) -> dict[str, object]:
        attributes = _attributes(model)
        values: dict[str, object] = {}
        for name, value in record.values.items():
            if name in attributes:
                attribute, column = attributes[name]
                values[attribute] = _convert(column, value)
        for name, reference in record.references.items():
            if name in attributes:
                values[attributes[name][0]] = self.resolve(reference)
        return values

    def _unique_slug(self, model: type, slug: str) -> str:
        candidate, number = slug, 1
        while self.session.scalar(select(model.id).where(model.slug == candidate).limit(1)) is not None:
            number += 1
            candidate = f"{slug}-{number}"
        return candidate

    def _remember(self, record: RecordPlan, entity_id: int, written: dict[str, object]) -> None:
        from backend.services.imports import _remember

        hashes = {name: _hash(value) for name, value in written.items()}
        link = self.links.get((record.kind, record.external_id))
        if link is not None:
            hashes = {**(link.written or {}), **hashes}
        _remember(self.session, self.links, self.run.importer, record.kind, record.external_id, entity_id,
                  hashes, [], self.run.id)
        self.resolved[(record.kind, record.external_id)] = entity_id

    def _metadata(self, entity, record: RecordPlan) -> None:
        if not hasattr(entity, "set_meta"):
            return
        for key, value in record.metadata.items():
            if entity.get_meta(key) is None:
                entity.set_meta(key, value)
        for profile_external_id, prefix, suffix, value in record.profile_metadata:
            profile = self.profiles.get(profile_external_id)
            if profile is None:
                continue
            key = f"{prefix}{profile.id}{suffix}"
            if entity.get_meta(key) is None:
                entity.set_meta(key, value)

    # Records -------------------------------------------------------------------

    def apply(self, record: RecordPlan) -> None:
        if record.kind == "collection" and record.external_id in self.skip_collections:
            self.skipped.add((record.kind, record.external_id))
            return
        try:
            if record.kind == "download":
                self._download(record)
            elif record.kind == "download_profile_season":
                self._download_profile_season(record)
            elif record.kind in _MODELS:
                self._record(record)
            else:
                self.result.add("not_supported", record.kind, "VODLoft doesn't import this kind of record")
        except _Unresolved as exc:
            self.skipped.add((record.kind, record.external_id))
            self.result.counts["records_skipped"] += 1
            if record.kind in ("collection", "movie", "stream_profile", "download_profile"):
                self.result.add("skipped", f"{record.kind} {record.external_id}", f"Not imported: {exc}")

    def _record(self, record: RecordPlan) -> None:
        model = _MODELS[record.kind]
        existing, link = self._find(model, record)
        values = self._values(model, record)
        subject = str(record.values.get("title") or record.values.get("name") or f"{record.kind} {record.external_id}")
        if record.kind == "stream_profile" and existing is not None and link is None:
            self.result.add("refused", subject, f"The feed token {record.values.get('token')} is already used by "
                            "another VODLoft feed; this feed was not imported")
            self.result.counts["feeds_refused"] += 1
            self.skipped.add((record.kind, record.external_id))
            return
        if existing is None:
            if record.kind in _SLUGGED and values.get("slug"):
                values["slug"] = self._unique_slug(model, str(values["slug"]))
            if record.kind == "download_profile":
                wanted_on = bool(values.get("enable_profile"))
                values["enable_profile"] = False
            entity = model(**values)
            self.session.add(entity)
            self.session.flush()
            self._metadata(entity, record)
            self._remember(record, entity.id, values)
            self.created.add((record.kind, record.external_id))
            self.result.counts[f"{record.kind}s_created"] += 1
            if record.kind == "download_profile":
                self.result.download_profiles.append((entity.id, wanted_on))
            return
        # Linked: write only what the person did not change in VODLoft since the last run.
        written = dict(link.written or {}) if link is not None else None
        changed, kept = [], []
        for attribute, value in values.items():
            if attribute in ("slug",) or (record.kind == "download_profile" and attribute == "enable_profile"):
                continue
            current = getattr(existing, attribute)
            if _hash(current) == _hash(value):
                continue
            if written is None or (attribute in written and written[attribute] != _hash(current)):
                kept.append(attribute)
                continue
            setattr(existing, attribute, value)
            changed.append(attribute)
        self.session.flush()
        self._metadata(existing, record)
        self._remember(record, existing.id, {name: getattr(existing, name) for name in values})
        if (record.kind, record.external_id) in self.created:
            return  # A second part of a record this run created, such as a movie's trailer.
        if link is None:
            self.result.counts[f"{record.kind}s_linked"] += 1
            if record.kind == "collection":
                self.result.add("linked", subject, "Already in your Library; linked, not added twice")
        elif changed:
            self.result.counts["updated"] += 1
            self.result.add("updated", subject, "Updated: " + ", ".join(changed))
        if kept and link is not None:
            self.result.add("kept", subject, "Kept your change: " + ", ".join(kept))

    def _download_profile_season(self, record: RecordPlan) -> None:
        profile = self.session.get(DownloadProfile, self.resolve(record.references["download_profile_id"]))
        season = self.session.get(Season, self.resolve(record.references["season_id"]))
        if profile is not None and season is not None and season not in profile.seasons:
            profile.seasons.append(season)

    # Downloads -----------------------------------------------------------------

    def _download(self, record: RecordPlan) -> None:
        media_id = self.resolve(record.references["media_item_id"])
        profile_id = self.resolve(record.references["local_media_profile_id"])
        model = _DOWNLOAD_MODELS[record.references["media_item_id"].kind]
        existing = self.session.scalar(select(MediaDownloadBase).where(
            MediaDownloadBase.media_item_id == media_id, MediaDownloadBase.local_media_profile_id == profile_id,
        ))
        if existing is not None and existing.artifact_status == _AVAILABLE:
            self.resolved[(record.kind, record.external_id)] = existing.id
            self.result.counts["already_adopted"] += 1
            return
        values = self._values(model, record)
        values.pop("file_path", None)
        recorded = record.values.get("file_path")
        path = self._reachable(recorded)
        wanted_available = record.values.get("artifact_status") == _AVAILABLE
        download = existing or model(**{
            name: value for name, value in values.items()
            if name not in ("artifact_stat_dev", "artifact_stat_ino", "artifact_size_bytes", "artifact_fingerprint",
                            "artifact_status", "artifact_error")
        })
        if existing is None:
            download.file_path = str(recorded or record.values.get("original_path") or "")
            download.artifact_status = _ABSENT
            self.session.add(download)
            self.session.flush()
            for child in record.children:
                if child.kind == "download_history":
                    download.history.append(MediaDownloadHistory(
                        action=child.values["action"], event_metadata=child.values.get("metadata") or {},
                        occurred_at=_convert(MediaDownloadHistory.__table__.c.occurred_at, child.values.get("occurred_at")),
                    ))
            self._metadata(download, record)
        if wanted_available and path is not None:
            self._adopt(download, record, path)
        elif wanted_available:
            # The file is not where VODLoft can see it: keep the row, don't download it again.
            download.automatic_retry_suppressed = True
            self.result.counts["not_reachable"] += 1
        self.session.flush()
        self._remember(record, download.id, {"file_path": download.file_path})

    def _reachable(self, virtual: object) -> Path | None:
        if not virtual:
            return None
        try:
            path = real_path(str(virtual))
        except AdoptionError:
            return None
        return path if path.is_file() else None

    def _adopt(self, download: MediaDownloadBase, record: RecordPlan, path: Path) -> None:
        identity = inspect_artifact(path)
        stored = (record.values.get("artifact_size_bytes"), record.values.get("artifact_fingerprint"))
        same = stored == (identity.size_bytes, identity.fingerprint)
        if path.suffix.lower() == ".m3u8":
            _rename_hls_marker(path)
        download.file_path = str(path)
        download.artifact_stat_dev, download.artifact_stat_ino = identity.stat_dev, identity.stat_ino
        download.artifact_size_bytes, download.artifact_fingerprint = identity.size_bytes, identity.fingerprint
        download.artifact_status = _AVAILABLE
        download.artifact_error = None
        download.automatic_retry_suppressed = False
        download.downloaded_bytes = identity.size_bytes
        download.assets.clear()
        self.session.flush()
        for child in record.children:
            if child.kind != "download_asset" or not child.values.get("path"):
                continue
            asset_path = self._reachable(child.values["path"])
            if asset_path is None:
                continue
            download.assets.append(MediaDownloadAsset(
                asset_key=child.values["asset_key"], kind=child.values["kind"], path=str(asset_path),
                suffix=child.values["suffix"], size_bytes=child.values.get("size_bytes"),
                fingerprint=child.values.get("fingerprint"),
            ))
        self.session.flush()
        record_media_download_history(self.session, download.id, MediaDownloadHistoryAction.IMPORTED, metadata={
            "file_path": str(path), "local_media_profile_id": download.local_media_profile_id,
            "matched_by": "Recorded path", "importer": self.run.importer,
            **({} if same else {"note": "The file changed since it was recorded"}),
        })
        self.result.counts["adopted"] += 1
        if not same:
            self.result.counts["adopted_changed"] += 1


def _rename_hls_marker(master: Path) -> None:
    """A local HLS bundle WireLoft made carries WireLoft's marker; VODLoft recognises its own.

    Only the hidden marker is renamed, never a media file. In a folder VODLoft may not write to the
    bundle stays WireLoft's: it plays the same, and VODLoft just won't replace it by itself.
    """
    assets = Path(f"{master}.assets")
    old, new = assets / _WIRELOFT_HLS_MARKER, assets / _VODLOFT_HLS_MARKER
    if old.is_file() and not new.exists():
        try:
            old.rename(new)
        except OSError:
            pass


def apply_records(
    session: Session, plan: ImportPlan, profiles: dict[str, LocalMediaProfileBase | None],
    links: dict[tuple[str, str], "ImportLink"], run, *, skip_collections: set[str] | None = None,
) -> RecordResult:
    """Create or link every record of ``plan``, in its order."""
    applier = _Applier(session, plan, profiles, links, run, skip_collections or set())
    for record in plan.records:
        applier.apply(record)
    session.flush()
    return applier.result


def record_summary(session: Session, plan: ImportPlan, links: dict[tuple[str, str], "ImportLink"]) -> dict[str, Any]:
    """What applying the records would do, without writing: per kind, how many are new and how many are linked."""
    from backend.services.imports import _exists

    by_kind: dict[str, Counter] = {}
    collections = []
    for record in plan.records:
        if record.kind == "download_profile_season":
            continue
        counts = by_kind.setdefault(record.kind, Counter())
        model = _MODELS.get(record.kind)
        linked = (record.kind, record.external_id) in links
        known = False
        if not linked and model is not None and record.identity and all(
            not isinstance(value, Reference) for value in record.identity.values()
        ):
            attributes = _attributes(model)
            filters = [getattr(model, attributes[name][0]) == value for name, value in record.identity.items()
                       if name in attributes]
            known = bool(filters) and session.scalar(select(model.id).where(*filters).limit(1)) is not None
        counts["linked" if linked else "in_library" if known else "new"] += 1
        if record.kind == "download" and record.values.get("artifact_status") == _AVAILABLE:
            counts["on_disk" if record.values.get("file_path") and _exists(str(record.values["file_path"])) else "not_reachable"] += 1
        if record.kind == "collection":
            collections.append({
                "external_id": record.external_id, "title": record.values.get("title"),
                "url": record.values.get("sharing_url"),
                "becomes": "linked" if linked else "in_library" if known else "new",
            })
    return {"kinds": {kind: dict(counts) for kind, counts in by_kind.items()}, "collections": collections}
