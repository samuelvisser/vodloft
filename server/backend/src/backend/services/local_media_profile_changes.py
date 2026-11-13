"""Creating and changing Local Media Profiles, for the API and the importer alike."""
from __future__ import annotations

from uuid import uuid4

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.db.models import Collection, CollectionLocalMediaProfile, CustomIndexState, LocalMediaProfileBase, MovieLocalMediaProfile
from backend.services.collection_assets import request_profile_collection_assets
from backend.services.custom_indexes import (
    compare_custom_index_assignments,
    profile_collection_scope_filter,
    profile_uses_custom_indexes,
    request_custom_index_reconciliation,
)
from backend.services.errors import NotFoundError, ServiceError
from backend.services.profile_file_renames import request_collection_local_media_profile_file_rename
from backend.services.local_media_profile_inputs import (
    CollectionLocalMediaProfileInput, LocalMediaProfileInput, MovieLocalMediaProfileInput, NewCollectionLocalMediaProfile,
)
from jinja_analysis import CustomIndexReachabilityStatus
from jinja_analysis.comparison import OutputOverlap
from backend.utils.custom_index import indexing_value_definition_keys, kept_index_keys, replace_indexing_value_definitions
from backend.utils.output_template import (
    _sanitize_emitted_output_value, finalize_output_path, output_template_custom_index_keys,
)
from backend.utils.output_template_analysis import analyze_profile_outputs, compare_profile_outputs
from backend.utils.output_template_jinja import create_output_template_environment

from task_manager.scheduler.operations import OperationTargetSpec, create_operation, queue_operation_target_dispatch
from task_manager.scheduler.types import OperationSource

logger = logging.getLogger(__name__)


def ensure_unique_profile_settings(
    s: Session,
    profile_model: type[LocalMediaProfileBase],
    body: LocalMediaProfileInput,
    *,
    exclude_id: int | None = None,
) -> None:
    duplicate_stmt = select(profile_model.name).where(
        profile_model.output_template == body.output_template,
        profile_model.preferred_format == body.preferred_format,
    )
    if exclude_id is not None:
        duplicate_stmt = duplicate_stmt.where(profile_model.id != exclude_id)
    duplicate_name = s.scalar(duplicate_stmt.limit(1))
    if duplicate_name is not None:
        # Either setting can tell the two profiles apart, so both fields say what clashes.
        raise ServiceError(
            f"Local Media Profile '{duplicate_name}' already uses this output path template with the same "
            "download format. Change the template or the format.",
            field="outputTemplate", status_code=409, kind="unique_violation",
            other_fields={
                "preferredFormat": f"Local Media Profile '{duplicate_name}' already downloads this format "
                                   "with the same output path template. Change the format or the template.",
            },
        )

    query = s.query(profile_model)
    if exclude_id is not None:
        query = query.filter(profile_model.id != exclude_id)

    environment = create_output_template_environment()
    environment.finalize = _sanitize_emitted_output_value
    candidate = analyze_profile_outputs(
        body.output_template, body.type, body.preferred_format,
        environment=environment, namespace="candidate",
    )

    # Stream candidates to speed up the process; only ask more if we need it
    for existing in query.yield_per(50):
        previous = analyze_profile_outputs(
            existing.output_template, existing.type, existing.preferred_format,
            environment=environment, namespace=f"profile:{existing.id}",
        )
        comparison = compare_profile_outputs(
            candidate, previous, environment=environment, finalize_path=finalize_output_path,
        )
        if comparison.status == OutputOverlap.OVERLAP:
            raise ServiceError(
                f"Output template can produce the same file as Local Media Profile '{existing.name}'. "
                "Choose a different output path.",
                field="outputTemplate", status_code=409, kind="output_path_collision",
            )
        if comparison.status == OutputOverlap.UNKNOWN:
            # Static validation is not a filesystem reservation. Do not reject
            # valid advanced templates merely because their expressions are not
            # comparable; actual download/rename collision guards remain final.
            logger.debug("Output comparison with Local Media Profile %s is inconclusive: %s",
                         existing.id, comparison.reason)


def _queue_custom_index_management(
    s: Session,
    profile: CollectionLocalMediaProfile,
    *,
    rename_files: bool = False,
) -> str | None:
    existing = set(s.scalars(select(CustomIndexState.collection_id).where(
        CustomIndexState.local_media_profile_id == profile.id,
    )))
    collection_ids = tuple(sorted(existing | set(s.scalars(
        select(Collection.id).where(profile_collection_scope_filter(profile))
    ))))
    if not collection_ids:
        if rename_files:
            request_collection_local_media_profile_file_rename(s, profile.slug)
        return None

    for collection_id in collection_ids:
        request_custom_index_reconciliation(
            s, collection_id=collection_id, local_media_profile_id=profile.id, dispatch=False,
        )
    target = OperationTargetSpec(
        task_key="manage_custom_indexes", resource_type="local_media_profile",
        resource_id=profile.id,
        task_kwargs={"rename_after": rename_files, "profile_change_token": uuid4().hex},
    )
    operation = create_operation(
        s,
        kind="local_media_profile.manage_custom_indexes",
        source=OperationSource.UI.value,
        resource_type="local_media_profile",
        resource_id=profile.id,
        title=profile.name,
        targets=[target],
        context={
            "local_media_profile_slug": profile.slug,
            "local_media_profile_name": profile.name,
            "rename_after": rename_files,
        },
    )
    queue_operation_target_dispatch(s, operation.id, target.resolved_slot_key())
    return operation.id


def _profile_by_slug(s: Session, model: type[LocalMediaProfileBase], slug: str, what: str):
    profile = s.scalar(select(model).where(model.slug == slug))
    if profile is None:
        raise NotFoundError(what)
    return profile


def create_collection_local_media_profile(
    s: Session,
    fields: NewCollectionLocalMediaProfile,
) -> CollectionLocalMediaProfile:
    ensure_unique_profile_settings(s, CollectionLocalMediaProfile, fields)
    item = create_database_fields(CollectionLocalMediaProfile, fields)
    s.add(item)
    s.flush()
    replace_indexing_value_definitions(item, fields.indexing_values)
    if profile_uses_custom_indexes(item):
        _queue_custom_index_management(s, item)
    request_profile_collection_assets(s, item.id)
    return item


def update_collection_local_media_profile(
    s: Session,
    local_media_profile_slug: str,
    fields: CollectionLocalMediaProfileInput,
    *,
    rename_files: bool = False,
) -> CollectionLocalMediaProfile:
    item = _profile_by_slug(s, CollectionLocalMediaProfile, local_media_profile_slug, "Collection Local Media Profile")

    previous_template = item.output_template
    previous_index_keys = output_template_custom_index_keys(previous_template)
    previous_definition_keys = indexing_value_definition_keys(item)
    previous_kept_keys = kept_index_keys(item)
    # The order of the Sites does not change which Collections the profile is for.
    previous_scope = (item.collection_scope, set(item.site_keys))

    ensure_unique_profile_settings(s, CollectionLocalMediaProfile, fields, exclude_id=item.id)
    # Missing values on updates are not creation defaults; retain the
    # persisted selection, even if collection_scope was changed.
    excluded_fields = {"indexing_values", *fields.fields_kept_on_update()}
    update_database_fields(item, fields, exclude_fields=excluded_fields)
    replace_indexing_value_definitions(item, fields.indexing_values)
    s.flush()

    current_index_keys = output_template_custom_index_keys(item.output_template)
    current_definition_keys = indexing_value_definition_keys(item)
    definition_keys_changed = previous_definition_keys != current_definition_keys
    template_changed = previous_template != item.output_template
    scope_changed = previous_scope != (item.collection_scope, set(item.site_keys))

    assignment_change = compare_custom_index_assignments(
        previous_template,
        item.output_template,
        previous_definition_keys=previous_definition_keys,
        current_definition_keys=current_definition_keys,
        previous_kept_keys=previous_kept_keys,
        current_kept_keys=kept_index_keys(item),
    )
    has_active_indexes = bool(
        previous_index_keys & previous_definition_keys
        or current_index_keys & current_definition_keys
    )
    needs_custom_index_management = (
        assignment_change.status != CustomIndexReachabilityStatus.UNCHANGED
        or scope_changed and has_active_indexes
    )

    if needs_custom_index_management:
        _queue_custom_index_management(s, item, rename_files=rename_files)
    elif rename_files and (template_changed or definition_keys_changed):
        request_collection_local_media_profile_file_rename(s, item.slug)

    request_profile_collection_assets(s, item.id)
    return item


def create_movie_local_media_profile(s: Session, fields: MovieLocalMediaProfileInput) -> MovieLocalMediaProfile:
    ensure_unique_profile_settings(s, MovieLocalMediaProfile, fields)
    item = create_database_fields(MovieLocalMediaProfile, fields)
    s.add(item)
    s.flush()
    return item


def update_movie_local_media_profile(
    s: Session, local_media_profile_slug: str, fields: MovieLocalMediaProfileInput,
) -> MovieLocalMediaProfile:
    item = _profile_by_slug(s, MovieLocalMediaProfile, local_media_profile_slug, "Movie Local Media Profile")
    ensure_unique_profile_settings(s, MovieLocalMediaProfile, fields, exclude_id=item.id)
    update_database_fields(item, fields, exclude_fields=fields.fields_kept_on_update())
    s.flush()
    return item
