"""Shared collection-directory resolution and artwork reconciliation requests."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from os.path import normcase
from typing import TYPE_CHECKING

from sqlalchemy import exists, or_, select, union
from sqlalchemy.orm import Session, selectinload

from backend.db.models import DownloadProfile, Episode, EpisodeMediaDownload, Collection, CollectionLocalMediaProfile
from backend.db.models.CollectionLocalAsset import CollectionLocalAsset
from backend.services.example_episodes import EXAMPLE_SOURCE_PREFIX
from backend.utils.custom_metadata import custom_metadata_template_values, get_custom_metadata
from backend.utils.output_template import (
    COLLECTION_OUTPUT_TEMPLATE_FIELDS, COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    _sanitize_emitted_output_value, output_template_fields, sanitize_path_component,
    validate_output_template_path_requirements,
)
from backend.utils.output_template_jinja import create_output_template_environment
from backend.utils.collection_media_directory import CollectionMediaDirectory, infer_collection_media_directory
from config import get_settings

if TYPE_CHECKING:
    from sources.dailywire.api.records import DwShowRecord

COLLECTION_ASSETS_REQUESTED = "collection_assets.reconcile_requested"


@dataclass(frozen=True)
class CollectionAssetRootPreview:
    path: str | None
    reason: str | None
    collection_title: str | None
    system_enabled: bool


@dataclass(frozen=True)
class CollectionAssetSource:
    kind: str
    url: str
    forced_format: str | None = None


def collection_assets_enabled(profile: CollectionLocalMediaProfile) -> bool:
    override = profile.download_collection_assets
    return get_settings().download_settings.download_collection_assets if override is None else override


def collection_profile_is_managed(
        session: Session,
        collection_id: int,
        profile_id: int,
) -> bool:
    """Return whether one collection/profile pair is still managed without loading all pairs."""
    profile_assignment = exists(
        select(DownloadProfile.id).where(
            DownloadProfile.collection_id == collection_id,
            DownloadProfile.local_media_profile_id == profile_id,
        )
    )
    manual_download = exists(
        select(EpisodeMediaDownload.id)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(
            Episode.collection_id == collection_id,
            EpisodeMediaDownload.local_media_profile_id == profile_id,
        )
    )
    return bool(session.scalar(select(or_(profile_assignment, manual_download))))


def managed_collection_profile_pairs(session: Session) -> set[tuple[int, int]]:
    """Include manual downloads as well as Download Profile assignments."""
    pairs = union(
        select(
            DownloadProfile.collection_id.label("collection_id"),
            DownloadProfile.local_media_profile_id.label("profile_id"),
        ).where(
            DownloadProfile.collection_id.is_not(None),
            DownloadProfile.local_media_profile_id.is_not(None),
        ),
        select(
            Episode.collection_id.label("collection_id"),
            EpisodeMediaDownload.local_media_profile_id.label("profile_id"),
        )
        .join(
            EpisodeMediaDownload,
            EpisodeMediaDownload.media_item_id == Episode.id,
        )
        .where(
            Episode.collection_id.is_not(None),
            EpisodeMediaDownload.local_media_profile_id.is_not(None),
        ),
    ).subquery()
    return {
        (int(collection_id), int(profile_id))
        for collection_id, profile_id in session.execute(
            select(pairs.c.collection_id, pairs.c.profile_id)
        )
    }


def resolve_collection_media_directory(
    collection: Collection | None, output_template: str, *, values_overrides: Mapping[str, str] | None = None,
) -> CollectionMediaDirectory:
    """Resolve with the production path policy and optional read-only preview edits.

    Overrides replace values in a separate context, never on ORM records. The
    semantic resolver still treats episode/season fields as variable, so editing
    a season cannot accidentally turn it into the shared collection directory.
    """
    validate_output_template_path_requirements(
        output_template,
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    )
    values = {field: "" for field in COLLECTION_OUTPUT_TEMPLATE_FIELDS | output_template_fields(output_template)}
    if collection is not None:
        values.update(collection=collection.slug, collection_title=collection.title)
        values.update(custom_metadata_template_values("collection", get_custom_metadata(collection)))
    values.update(values_overrides or {})
    environment = create_output_template_environment(custom_index_resolver=lambda _key, _group: "")
    environment.finalize = _sanitize_emitted_output_value
    settings = get_settings().download_settings
    names = tuple(
        str(value) for season in (collection.seasons if collection is not None else ())
        for value in (season.slug, season.name, season.index, season.season_number)
        if value is not None
    )
    names += tuple(values[field] for field in ("season", "season_name", "season_index", "season_number") if values.get(field))
    resolution = infer_collection_media_directory(
        output_template, values, environment=environment,
        sanitize_component=lambda part: sanitize_path_component(part, mode=settings.filename_restriction_mode),
        season_names=names,
    )
    if resolution.path is None:
        return resolution
    base = Path(settings.download_root).resolve()
    destination = (base / resolution.path.removeprefix("/downloads/")).resolve()
    if destination == base or not destination.is_relative_to(base):
        return CollectionMediaDirectory(None, "The resolved collection root is outside the download root or is the download root itself.")
    return CollectionMediaDirectory(str(destination))


def collection_profile_roots(
    session: Session, *, draft_profile_id: int | None = None, draft_template: str | None = None,
) -> dict[tuple[int, int], CollectionMediaDirectory]:
    pairs = managed_collection_profile_pairs(session)
    if not pairs:
        return {}
    profiles = {profile.id: profile for profile in session.scalars(
        select(CollectionLocalMediaProfile).where(CollectionLocalMediaProfile.id.in_({profile_id for _, profile_id in pairs}))
    )}
    collections = {collection.id: collection for collection in session.scalars(
        select(Collection).where(Collection.id.in_({collection_id for collection_id, _ in pairs}))
        .options(selectinload(Collection.seasons), selectinload(Collection.meta_items))
    )}
    roots = {}
    for collection_id, profile_id in sorted(pairs):
        collection, profile = collections.get(collection_id), profiles.get(profile_id)
        if collection is None or profile is None:
            continue
        template = draft_template if profile_id == draft_profile_id and draft_template is not None else profile.output_template
        try:
            roots[collection_id, profile_id] = resolve_collection_media_directory(collection, template)
        except ValueError as exc:
            roots[collection_id, profile_id] = CollectionMediaDirectory(None, str(exc))
    return roots


def shared_root_conflict(roots: dict[tuple[int, int], CollectionMediaDirectory], collection_id: int, path: str) -> bool:
    # Compare normalized filesystem paths, not unsanitized collection titles.
    for (other_collection, _), root in roots.items():
        if other_collection == collection_id or root.path is None:
            continue
        if normcase(root.path) == normcase(path):
            return True
        # Case-insensitive network mounts can exist on case-sensitive hosts.
        # Avoid filesystem round trips unless the names differ only in case.
        if root.path.casefold() == path.casefold():
            try:
                if Path(root.path).samefile(path):
                    return True
            except OSError:
                pass
    return False


def get_collection_asset_root_preview(
    session: Session, *, source_id: str | None, output_template: str, local_media_profile_id: int | None,
    values_overrides: Mapping[str, str] | None = None,
) -> CollectionAssetRootPreview:
    enabled = get_settings().download_settings.download_collection_assets
    collection = None
    if source_id and source_id.startswith("episode:") and source_id[8:].isascii() and source_id[8:].isdigit():
        episode = session.get(Episode, int(source_id[8:]))
        if episode is None:
            return CollectionAssetRootPreview(None, "The selected episode no longer exists.", None, enabled)
        collection = episode.collection
    elif (
        source_id not in {None, "example:collection"} and not source_id.startswith(EXAMPLE_SOURCE_PREFIX)
    ) or values_overrides is None:
        return CollectionAssetRootPreview(None, "Select an episode in the Jinja editor to resolve its collection's root.", None, enabled)
    result = resolve_collection_media_directory(collection, output_template, values_overrides=values_overrides)
    if result.path:
        roots = collection_profile_roots(session, draft_profile_id=local_media_profile_id, draft_template=output_template)
        if shared_root_conflict(roots, collection.id if collection is not None else -1, result.path):
            result = CollectionMediaDirectory(None, "This directory is also used by another collection. Shared artwork would collide.")
    title = (values_overrides or {}).get("collection_title", collection.title if collection is not None else None)
    return CollectionAssetRootPreview(result.path, result.reason, title, enabled)


def collection_asset_sources(collection: Collection) -> tuple[CollectionAssetSource, ...]:
    choices = (
        ("poster", (collection.thumbnail_portrait_path, collection.thumbnail_square_path), None),
        ("fanart", (collection.background_image_path, collection.thumbnail_landscape_path), None),
        ("square", (collection.thumbnail_square_path,), None),
        ("clearlogo", (collection.logo_image_path,), "png"),
    )
    sources = []
    for kind, candidates, forced_format in choices:
        url = next(
            (value for value in candidates if isinstance(value, str) and value.startswith(("https://", "http://"))),
            None,
        )
        if url is not None:
            sources.append(CollectionAssetSource(kind, url, forced_format))
    return tuple(sources)


def request_collection_asset_reconciliation(session: Session, collection_id: int = 0) -> None:
    from task_manager.events.transactional import queue_event
    queue_event(session, COLLECTION_ASSETS_REQUESTED, {"resource_id": collection_id})


def request_profile_collection_assets(session: Session, profile_id: int) -> None:
    collection_ids = union(
        select(DownloadProfile.collection_id.label("collection_id")).where(
            DownloadProfile.local_media_profile_id == profile_id,
            DownloadProfile.collection_id.is_not(None),
        ),
        select(Episode.collection_id.label("collection_id"))
        .join(
            EpisodeMediaDownload,
            EpisodeMediaDownload.media_item_id == Episode.id,
        )
        .where(
            EpisodeMediaDownload.local_media_profile_id == profile_id,
            Episode.collection_id.is_not(None),
        ),
        select(CollectionLocalAsset.collection_id.label("collection_id")).where(
            CollectionLocalAsset.local_media_profile_id == profile_id,
            CollectionLocalAsset.collection_id.is_not(None),
        ),
    ).subquery()
    for collection_id in session.scalars(
        select(collection_ids.c.collection_id).order_by(collection_ids.c.collection_id)
    ):
        request_collection_asset_reconciliation(session, int(collection_id))


def update_collection_artwork_metadata(collection: Collection, source: "DwShowRecord") -> None:
    """Reuse the already fetched collection page; absent variants keep their known URL."""
    for field in (
        "thumbnail_portrait_path", "thumbnail_landscape_path", "thumbnail_square_path",
        "background_image_path", "logo_image_path",
    ):
        value = getattr(source, field, None)
        if value:
            setattr(collection, field, value)
