from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import os
import tempfile
from typing import Callable

from downloader import DownloadCancelled
from sqlalchemy import String, and_, cast, func, or_, select

from backend.db.models import DownloadProfile, Episode, EpisodeMediaDownload, Collection, CollectionLocalMediaProfile
from backend.db.models.CollectionLocalAsset import CollectionLocalAsset
from backend.services.collection_assets import (
    managed_collection_profile_pairs, resolve_collection_media_directory, shared_root_conflict,
    collection_asset_sources, collection_assets_enabled, collection_profile_is_managed, collection_profile_roots,
)
from backend.utils.collection_asset_files import (
    ArtworkConflict, PreparedCollectionAsset, asset_file_hash, asset_file_lock,
    download_collection_asset, publish_collection_asset, safe_asset_path,
)
from config import get_settings
from controller.db_utils import db_session
from task_manager.tasks.helpers.progress import update_progress

logger = logging.getLogger(__name__)
_REFRESH_AFTER = timedelta(days=1)
_SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass(frozen=True)
class AssetPlan:
    collection_id: int
    profile_id: int
    kind: str
    url: str
    directory: Path
    download_root: Path
    output_template: str
    forced_format: str | None = None


def _fallback_format() -> str:
    value = get_settings().download_settings.collection_artwork_fallback_format
    return str(getattr(value, "value", value))


def _expected_output_format(row: CollectionLocalAsset, plan: AssetPlan) -> str | None:
    if plan.forced_format is not None:
        return plan.forced_format
    if row.source_format in {"jpg", "png"}:
        return row.source_format
    if row.source_format == "other":
        return _fallback_format()
    return None


def _current(session, plan: AssetPlan) -> bool:
    profile = session.get(CollectionLocalMediaProfile, plan.profile_id)
    collection = session.get(Collection, plan.collection_id)
    if profile is None or collection is None or not collection_assets_enabled(profile):
        return False
    if profile.output_template != plan.output_template:
        return False
    if not collection_profile_is_managed(session, plan.collection_id, plan.profile_id):
        return False
    if Path(get_settings().download_settings.download_root).resolve() != plan.download_root:
        return False
    source = next((candidate for candidate in collection_asset_sources(collection) if candidate.kind == plan.kind), None)
    return (
        resolve_collection_media_directory(collection, profile.output_template).path == str(plan.directory)
        and source is not None
        and source.url == plan.url
        and source.forced_format == plan.forced_format
    )


def _path_rows(session, path: Path) -> list[CollectionLocalAsset]:
    return list(session.scalars(select(CollectionLocalAsset).where(CollectionLocalAsset.file_path == str(path))))


def _direct_child_path_filter(column, directory: Path):
    prefix = f"{directory}{os.sep}"
    relative = cast(func.substr(column, len(prefix) + 1), String)
    return and_(
        column.startswith(prefix, autoescape=True),
        ~relative.contains(os.sep, autoescape=True),
    )


def _expected_format_filter(plan: AssetPlan):
    if plan.forced_format is not None:
        return CollectionLocalAsset.file_path.endswith(
            f".{plan.forced_format}",
            autoescape=True,
        )

    fallback = _fallback_format()
    return or_(
        and_(
            CollectionLocalAsset.source_format == "jpg",
            CollectionLocalAsset.file_path.endswith(".jpg", autoescape=True),
        ),
        and_(
            CollectionLocalAsset.source_format == "png",
            CollectionLocalAsset.file_path.endswith(".png", autoescape=True),
        ),
        and_(
            CollectionLocalAsset.source_format == "other",
            CollectionLocalAsset.file_path.endswith(
                f".{fallback}",
                autoescape=True,
            ),
        ),
    )


def _owned_file(session, plan: AssetPlan, target: Path):
    safe_asset_path(plan.download_root, target)
    rows = _path_rows(session, target)
    if any(row.collection_id != plan.collection_id for row in rows):
        raise ArtworkConflict(f"Another collection owns artwork at {target}")

    for suffix in _SUPPORTED_EXTENSIONS:
        alternate = target.with_suffix(suffix)
        if alternate == target or not (alternate.exists() or alternate.is_symlink()):
            continue
        alternate_rows = _path_rows(session, alternate)
        alternate_digest = asset_file_hash(alternate)
        if alternate_digest is None or not any(
            row.collection_id == plan.collection_id
            and alternate_digest in (row.content_hash, row.pending_hash)
            for row in alternate_rows
        ):
            raise ArtworkConflict(f"Existing alternate-format artwork was left untouched: {alternate}")

    digest = asset_file_hash(target)
    if digest is not None and not any(digest in (row.content_hash, row.pending_hash) for row in rows):
        raise ArtworkConflict(f"User-supplied or edited artwork was left untouched: {target}")
    return rows, digest


def _owner(session, rows, plan: AssetPlan, target: Path) -> CollectionLocalAsset:
    owner = next((
        row for row in rows
        if row.local_media_profile_id == plan.profile_id and row.asset_type == plan.kind
    ), None)
    if owner is None:
        owner = CollectionLocalAsset(
            collection_id=plan.collection_id,
            local_media_profile_id=plan.profile_id,
            asset_type=plan.kind,
            file_path=str(target),
        )
        session.add(owner)
        rows.append(owner)
    return owner


def _claim_fresh_asset(
    plan: AssetPlan,
    now: datetime,
    check_cancelled: Callable[[], None],
) -> tuple[bool, Path | None]:
    with db_session() as session:
        if not _current(session, plan):
            return False, None
        candidates = [
            Path(path)
            for path in session.scalars(
                select(CollectionLocalAsset.file_path).where(
                    CollectionLocalAsset.collection_id == plan.collection_id,
                    CollectionLocalAsset.asset_type == plan.kind,
                    CollectionLocalAsset.source_url == plan.url,
                    CollectionLocalAsset.pending_hash.is_(None),
                    CollectionLocalAsset.checked_at.is_not(None),
                    CollectionLocalAsset.checked_at > now - _REFRESH_AFTER,
                    _direct_child_path_filter(
                        CollectionLocalAsset.file_path,
                        plan.directory,
                    ),
                    _expected_format_filter(plan),
                )
            )
        ]

    for target in dict.fromkeys(candidates):
        check_cancelled()
        with asset_file_lock(plan.download_root, target):
            with db_session() as session:
                if not _current(session, plan):
                    return False, None
                rows = _path_rows(session, target)
                if any(row.collection_id != plan.collection_id for row in rows):
                    raise ArtworkConflict(f"Another collection owns artwork at {target}")
                digest = asset_file_hash(target)
                owned_by_profile = next((
                    row for row in rows
                    if row.collection_id == plan.collection_id
                    and row.local_media_profile_id == plan.profile_id
                    and row.asset_type == plan.kind
                ), None)
                if owned_by_profile is not None and digest not in (
                    owned_by_profile.content_hash,
                    owned_by_profile.pending_hash,
                ):
                    raise ArtworkConflict(f"User-supplied or edited artwork was left untouched: {target}")
                fresh = next((
                    row for row in rows
                    if row.collection_id == plan.collection_id
                    and row.asset_type == plan.kind
                    and digest is not None
                    and row.content_hash == digest
                    and row.pending_hash is None
                    and row.source_url == plan.url
                    and row.checked_at is not None
                    and now - row.checked_at < _REFRESH_AFTER
                    and _expected_output_format(row, plan) is not None
                    and target.suffix.lower() == f".{_expected_output_format(row, plan)}"
                ), None)
                if fresh is None:
                    continue
                owner = _owner(session, rows, plan, target)
                owner.content_hash = digest
                owner.pending_hash = None
                owner.source_url = plan.url
                owner.source_format = fresh.source_format
                owner.checked_at = fresh.checked_at
                session.commit()
                return True, target
    return True, None


def _cleanup_obsolete_variants(
    plan: AssetPlan,
    current_target: Path,
    check_cancelled: Callable[[], None],
) -> None:
    with db_session() as session:
        obsolete = [
            (row_id, Path(file_path))
            for row_id, file_path in session.execute(
                select(CollectionLocalAsset.id, CollectionLocalAsset.file_path).where(
                    CollectionLocalAsset.collection_id == plan.collection_id,
                    CollectionLocalAsset.local_media_profile_id == plan.profile_id,
                    CollectionLocalAsset.asset_type == plan.kind,
                    CollectionLocalAsset.file_path != str(current_target),
                    _direct_child_path_filter(
                        CollectionLocalAsset.file_path,
                        plan.directory,
                    ),
                )
            )
        ]

    for record_id, path in obsolete:
        check_cancelled()
        try:
            with asset_file_lock(plan.download_root, path):
                with db_session() as session:
                    row = session.get(CollectionLocalAsset, record_id)
                    if row is None or not _current(session, plan):
                        continue
                    replacement = session.scalar(select(CollectionLocalAsset).where(
                        CollectionLocalAsset.collection_id == plan.collection_id,
                        CollectionLocalAsset.local_media_profile_id == plan.profile_id,
                        CollectionLocalAsset.asset_type == plan.kind,
                        CollectionLocalAsset.file_path == str(current_target),
                    ))
                    if (
                        replacement is None
                        or replacement.content_hash is None
                        or asset_file_hash(current_target) != replacement.content_hash
                    ):
                        continue
                    shared = session.scalar(select(CollectionLocalAsset.id).where(
                        CollectionLocalAsset.file_path == str(path),
                        CollectionLocalAsset.id != record_id,
                    ).limit(1))
                    if shared is None:
                        digest = asset_file_hash(path)
                        if digest is not None and digest in (row.content_hash, row.pending_hash):
                            safe_asset_path(plan.download_root, path).unlink(missing_ok=True)
                    session.delete(row)
                    session.commit()
        except ArtworkConflict as exc:
            logger.warning("Old collection artwork variant was left untouched: %s", exc)


def _refresh_asset(plan: AssetPlan, check_cancelled: Callable[[], None]) -> bool:
    check_cancelled()
    now = datetime.now(timezone.utc)
    current, fresh_target = _claim_fresh_asset(plan, now, check_cancelled)
    if not current:
        return False
    if fresh_target is not None:
        _cleanup_obsolete_variants(plan, fresh_target, check_cancelled)
        return True

    with tempfile.TemporaryDirectory(prefix="vodloft-show-assets-") as temporary:
        settings = get_settings().download_settings
        prepared: PreparedCollectionAsset = download_collection_asset(
            plan.url,
            Path(temporary),
            ffmpeg_path=settings.ffmpeg_path,
            fallback_format=settings.collection_artwork_fallback_format,
            forced_format=plan.forced_format,
            check_cancelled=check_cancelled,
        )
        target = plan.directory / f"{plan.kind}.{prepared.output_format}"
        new_hash = asset_file_hash(prepared.path)
        if new_hash is None:
            raise ValueError("Prepared collection artwork disappeared before publication")
        check_cancelled()
        with asset_file_lock(plan.download_root, target):
            with db_session() as session:
                if not _current(session, plan):
                    return False
                if shared_root_conflict(collection_profile_roots(session), plan.collection_id, str(plan.directory)):
                    raise ArtworkConflict("The collection directory became shared by another collection")
                rows, previous_hash = _owned_file(session, plan, target)
                _owner(session, rows, plan, target)
                for row in rows:
                    row.pending_hash = new_hash
                session.commit()
                if new_hash != previous_hash:
                    publish_collection_asset(
                        prepared.path,
                        target,
                        download_root=plan.download_root,
                        expected_hash=previous_hash,
                        check_cancelled=check_cancelled,
                    )
                for row in rows:
                    row.content_hash = new_hash
                    row.pending_hash = None
                    row.source_url = plan.url
                    row.source_format = prepared.source_format
                    row.checked_at = now
                session.commit()

    _cleanup_obsolete_variants(plan, target, check_cancelled)
    return True


def _cleanup_old_roots(
    collection_id: int, profile_id: int, current_root: Path, download_root: Path,
    check_cancelled: Callable[[], None],
) -> None:
    with db_session() as session:
        obsolete = [
            (row_id, Path(file_path))
            for row_id, file_path in session.execute(
                select(CollectionLocalAsset.id, CollectionLocalAsset.file_path).where(
                    CollectionLocalAsset.collection_id == collection_id,
                    CollectionLocalAsset.local_media_profile_id == profile_id,
                    ~_direct_child_path_filter(
                        CollectionLocalAsset.file_path,
                        current_root,
                    ),
                )
            )
        ]
        media_paths = [Path(path).resolve() for path in session.scalars(
            select(EpisodeMediaDownload.file_path).join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
            .where(Episode.collection_id == collection_id, EpisodeMediaDownload.local_media_profile_id == profile_id)
        ) if path]
    for record_id, path in obsolete:
        check_cancelled()
        if any(media.is_relative_to(path.parent) and not media.is_relative_to(current_root) for media in media_paths):
            continue
        try:
            with asset_file_lock(download_root, path):
                with db_session() as session:
                    row = session.get(CollectionLocalAsset, record_id)
                    profile = session.get(CollectionLocalMediaProfile, profile_id)
                    collection = session.get(Collection, collection_id)
                    if row is None or profile is None or collection is None or not collection_assets_enabled(profile):
                        continue
                    if not collection_profile_is_managed(session, collection_id, profile_id):
                        continue
                    if resolve_collection_media_directory(collection, profile.output_template).path != str(current_root):
                        continue
                    replacement = session.scalar(
                        select(CollectionLocalAsset)
                        .where(
                            CollectionLocalAsset.collection_id == collection_id,
                            CollectionLocalAsset.local_media_profile_id == profile_id,
                            CollectionLocalAsset.asset_type == row.asset_type,
                            CollectionLocalAsset.content_hash.is_not(None),
                            _direct_child_path_filter(
                                CollectionLocalAsset.file_path,
                                current_root,
                            ),
                        )
                        .order_by(CollectionLocalAsset.id)
                        .limit(1)
                    )
                    if replacement is None:
                        continue
                    if asset_file_hash(Path(replacement.file_path)) != replacement.content_hash:
                        continue
                    shared = session.scalar(select(CollectionLocalAsset.id).where(
                        CollectionLocalAsset.file_path == str(path), CollectionLocalAsset.id != record_id,
                    ).limit(1))
                    if shared is None:
                        digest = asset_file_hash(path)
                        if digest is not None and digest in (row.content_hash, row.pending_hash):
                            safe_asset_path(download_root, path).unlink(missing_ok=True)
                    session.delete(row)
                    session.commit()
        except ArtworkConflict as exc:
            logger.warning("Old collection artwork was left untouched: %s", exc)


def run_reconcile_collection_assets(
    *, resource_id=None, resource_type=None, progress=None, check_cancelled: Callable[[], None],
) -> None:
    warnings = []
    plans = []
    cleanup = []
    download_root = Path(get_settings().download_settings.download_root).resolve()
    with db_session() as session:
        if resource_type == "download_profile" and resource_id:
            profile = session.get(DownloadProfile, resource_id)
            if profile is None:
                return
            collection_id = profile.collection_id
        else:
            collection_id = resource_id or None
        check_cancelled()
        roots = collection_profile_roots(session)
        indexed_collection_ids = set(session.scalars(select(Episode.collection_id).distinct()))
        for (current_collection_id, profile_id), root in roots.items():
            if current_collection_id not in indexed_collection_ids:
                continue
            if collection_id is not None and current_collection_id != collection_id:
                continue
            profile = session.get(CollectionLocalMediaProfile, profile_id)
            collection = session.get(Collection, current_collection_id)
            if profile is None or collection is None or not collection_assets_enabled(profile):
                continue
            if root.path is None or shared_root_conflict(roots, current_collection_id, root.path):
                warnings.append(
                    f"{collection.title} via Local Media Profile '{profile.name}': "
                    f"{root.reason or 'the artwork directory is shared by another collection'}"
                )
                continue
            directory = Path(root.path)
            sources = collection_asset_sources(collection)
            plans.extend(
                AssetPlan(
                    collection.id,
                    profile_id,
                    source.kind,
                    source.url,
                    directory,
                    download_root,
                    profile.output_template,
                    source.forced_format,
                )
                for source in sources
            )
            if sources:
                cleanup.append((collection.id, profile_id, directory))

    errors = []
    failed_pairs = set()
    for index, plan in enumerate(plans):
        update_progress(progress, int(index * 90 / max(1, len(plans))), f"Reconciling collection artwork ({index + 1}/{len(plans)})")
        try:
            if not _refresh_asset(plan, check_cancelled):
                failed_pairs.add((plan.collection_id, plan.profile_id))
        except DownloadCancelled:
            raise
        except ArtworkConflict as exc:
            warnings.append(str(exc))
            failed_pairs.add((plan.collection_id, plan.profile_id))
        except Exception as exc:
            logger.exception("Collection %s artwork %s could not be refreshed", plan.collection_id, plan.kind)
            errors.append(str(exc))
            failed_pairs.add((plan.collection_id, plan.profile_id))
    for collection_id, profile_id, directory in cleanup:
        if (collection_id, profile_id) not in failed_pairs:
            _cleanup_old_roots(collection_id, profile_id, directory, download_root, check_cancelled)
    for warning in warnings:
        logger.warning("Collection artwork: %s", warning)
    if errors:
        raise RuntimeError(f"Could not refresh {len(errors)} collection artwork file(s): {errors[0]}")
    update_progress(progress, 100, f"Reconciled collection artwork; {len(warnings)} skipped or ambiguous destination(s)")
