from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.orm import Session
from backend.services.custom_indexes import request_collection_custom_index_reconciliation
from backend.services.metadata_refresh import refreshes_metadata
from sqlalchemy import and_, case, func, or_, select

from fastapi import HTTPException

from backend.db.model_mapping import create_database_fields, update_database_fields
from backend.api.models.episode import *
from backend.api.pagination import InvalidCursorError, decode_cursor, encode_cursor, keyset_after, KeysetField
from backend.db.models import Collection
from backend.db.models.media_item import Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode import episode_identifier_type_predicate
from backend.services.episode_download_delay import episode_download_delay_ready_at
from backend.utils.episode_publication_timing import (
    record_publication_lifecycle_observation,
)
from task_manager.events.transactional import queue_event
from task_manager.scheduler.operations import (
    OperationTargetSpec,
    create_operation,
    queue_operation_target_dispatch,
)


@dataclass(frozen=True)
class _EpisodeAPIReadSource:
    episode: Episode
    download_delay_passed: bool
    download_delay_ready_at: datetime | None


_METADATA_REFRESH_TASK_KEY = "refresh_episode_metadata"
_EARLY_DELETE_TASK_KEY = "monitor_no_usable_media_episode"


def _episode_api_read(episode: Episode) -> EpisodeAPIRead:
    ready_at = episode_download_delay_ready_at(episode)
    return EpisodeAPIRead.model_validate(_EpisodeAPIReadSource(
        episode=episode,
        download_delay_passed=(
            ready_at is None
            or ready_at <= datetime.now(timezone.utc)
        ),
        download_delay_ready_at=ready_at,
    ))


def _episodes_for_collection_stmt(collection_slug: str):
    return (
        select(Episode)
        .join(Collection, Episode.collection_id == Collection.id)
        .where(Collection.slug == collection_slug)
        .order_by(Episode.published_date.desc())
    )


def get_episodes_by_collection_list(s: Session, collection_slug: str, limit: int | None = None) -> list[EpisodeAPIRead]:
    # Join directly through the indexed collection slug rather than using Episode.collection.has(), which
    # produces a correlated EXISTS predicate. This keeps the full-list query simple while
    # preserving the existing endpoint contract for callers that need complete episode records.
    stmt = _episodes_for_collection_stmt(collection_slug)
    if limit is not None:
        stmt = stmt.limit(limit)
    episodes: Sequence[Episode] = s.scalars(stmt).all()

    return [_episode_api_read(episode) for episode in episodes]


def _episode_view_order(s: Session, collection_slug: str, season_id: int | None) -> EpisodeOrder:
    """The order of a collection's episode list, or of one of its seasons."""
    row = s.execute(
        select(Collection.episode_order, Collection.episode_identifier).where(Collection.slug == collection_slug)
    ).one_or_none()
    if row is None:
        return EpisodeOrder.NEWEST_FIRST
    # A seasonal collection orders the episodes of each season. Its list of every episode stays newest
    # first: the browser keeps its start as a preview, and the page opens on the latest season.
    if season_id is None and row.episode_identifier == EpisodeIdentifier.SEASONAL.value:
        return EpisodeOrder.NEWEST_FIRST
    return EpisodeOrder(row.episode_order)


def _episode_view_stmt(
        collection_slug: str,
        season_id: int | None = None,
        episode_types: Sequence[str] = (),
        order: EpisodeOrder = EpisodeOrder.NEWEST_FIRST,
):
    # The collection grid needs only a small subset of Episode. Selecting those columns directly avoids
    # constructing full ORM entities (and their select-in metadata relationship), then sending and
    # validating descriptions/timestamps that the grid never renders.
    stmt = (
        select(
            Episode.id.label("id"),
            Episode.source_key.label("source_key"),
            Episode.collection_id.label("collection_id"),
            Episode.season_id.label("season_id"),
            Episode.index.label("index"),
            Episode.episode_identifier.label("episode_identifier"),
            Episode.dw_episode_number.label("dw_episode_number"),
            Episode.publish_status.label("publish_status"),
            Episode.drm_protected.label("drm_protected"),
            Episode.access.label("access"),
            Collection.site_key.label("site_key"),
            Episode.access_refused_at.label("access_refused_at"),
            Episode.access_check_at.label("access_check_at"),
            Episode.removed_from_source.label("removed_from_source"),
            Episode.title.label("title"),
            Episode.duration.label("duration"),
            Episode.slug.label("slug"),
            Episode.thumbnail_landscape_path.label("thumbnail_landscape_path"),
            Episode.thumbnail_portrait_path.label("thumbnail_portrait_path"),
            Episode.thumbnail_square_path.label("thumbnail_square_path"),
            Episode.published_date.label("published_date"),
        )
        .join(Collection, Episode.collection_id == Collection.id)
        .where(Collection.slug == collection_slug)
    )
    if episode_types:
        stmt = stmt.where(episode_identifier_type_predicate(Episode.episode_identifier, set(episode_types)))
    newest_first = order == EpisodeOrder.NEWEST_FIRST
    if season_id is not None:
        stmt = stmt.where(Episode.season_id == season_id)
        if newest_first:
            return stmt.order_by(Episode.index.desc(), Episode.id.desc())
        return stmt.order_by(Episode.index.asc(), Episode.id.asc())
    if newest_first:
        return stmt.order_by(Episode.published_date.desc().nulls_last(), Episode.id.desc())
    return stmt.order_by(Episode.published_date.asc().nulls_last(), Episode.id.asc())


def get_episode_views_by_collection_list(
        s: Session,
        collection_slug: str,
        limit: int | None = None,
) -> list[EpisodeAPIReadView]:
    """Return compact rows for internal callers that still need a simple list."""
    stmt = _episode_view_stmt(collection_slug, order=_episode_view_order(s, collection_slug, None))
    if limit is not None:
        stmt = stmt.limit(limit)

    return [
        EpisodeAPIReadView.model_validate(row)
        for row in s.execute(stmt).mappings().all()
    ]


def get_episode_views_by_collection_page(
        s: Session,
        collection_slug: str,
        *,
        cursor: str | None,
        limit: int,
        season_id: int | None = None,
        episode_types: Sequence[str] = (),
) -> EpisodeAPIReadViewPage:
    """Return one stable cursor page of compact episodes for a collection, optionally of some episode types only."""
    episode_types = sorted(set(episode_types))
    collection_count_stmt = (
        select(func.count(Episode.id))
        .join(Collection, Episode.collection_id == Collection.id)
        .where(Collection.slug == collection_slug)
    )
    collection_total = int(s.scalar(collection_count_stmt) or 0)
    view_count_stmt = collection_count_stmt
    if season_id is not None:
        view_count_stmt = view_count_stmt.where(Episode.season_id == season_id)
    if episode_types:
        view_count_stmt = view_count_stmt.where(
            episode_identifier_type_predicate(Episode.episode_identifier, set(episode_types))
        )
    total = (
        collection_total
        if view_count_stmt is collection_count_stmt
        else int(s.scalar(view_count_stmt) or 0)
    )
    revision_stmt = (
        select(func.max(case(
            (Episode.updated_at > Episode.created_at, Episode.updated_at),
            else_=None,
        )))
        .join(Collection, Episode.collection_id == Collection.id)
        .where(Collection.slug == collection_slug)
    )
    if season_id is not None:
        revision_stmt = revision_stmt.where(Episode.season_id == season_id)
    latest_ordering_change = s.scalar(revision_stmt)
    revision = (
        latest_ordering_change.isoformat()
        if latest_ordering_change is not None
        else ""
    )

    order = _episode_view_order(s, collection_slug, season_id)
    newest_first = order == EpisodeOrder.NEWEST_FIRST
    stmt = _episode_view_stmt(collection_slug, season_id, episode_types, order)
    if cursor:
        try:
            values = decode_cursor(cursor)
            if (
                values.get("kind") != "collection-episodes"
                or values.get("collection_slug") != collection_slug
                or values.get("season_id") != season_id
                or values.get("episode_types", []) != episode_types
            ):
                raise InvalidCursorError("Cursor does not match this episode collection")
            cursor_id = values.get("id")
            if not isinstance(cursor_id, int) or isinstance(cursor_id, bool):
                raise InvalidCursorError("Invalid episode cursor id")

            # Episode dates/indexes can be corrected by metadata refreshes. A
            # changed revision means the old sort boundary is no longer safe;
            # restart at the head and let the generic frontend replace the old
            # page chain immediately. So does a change of the collection's order.
            if values.get("revision") == revision and values.get("order") == order.value:
                if season_id is not None:
                    cursor_index = values.get("index")
                    if not isinstance(cursor_index, int) or isinstance(cursor_index, bool):
                        raise InvalidCursorError("Invalid episode cursor index")
                    stmt = stmt.where(keyset_after([
                        KeysetField(Episode.index, cursor_index, descending=newest_first),
                        KeysetField(Episode.id, cursor_id, descending=newest_first),
                    ]))
                else:
                    published_raw = values.get("published_at")
                    if published_raw is not None and not isinstance(published_raw, str):
                        raise InvalidCursorError("Invalid episode cursor date")
                    published_at = (
                        datetime.fromisoformat(published_raw)
                        if published_raw is not None
                        else None
                    )
                    # Episodes without a date come last either way.
                    id_after = Episode.id < cursor_id if newest_first else Episode.id > cursor_id
                    if published_at is None:
                        stmt = stmt.where(
                            Episode.published_date.is_(None),
                            id_after,
                        )
                    else:
                        stmt = stmt.where(or_(
                            (
                                Episode.published_date < published_at
                                if newest_first
                                else Episode.published_date > published_at
                            ),
                            and_(
                                Episode.published_date == published_at,
                                id_after,
                            ),
                            Episode.published_date.is_(None),
                        ))
        except (InvalidCursorError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows = s.execute(stmt.limit(limit + 1)).mappings().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [EpisodeAPIReadView.model_validate(row) for row in rows]

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        values: dict[str, object] = {
            "kind": "collection-episodes",
            "collection_slug": collection_slug,
            "season_id": season_id,
            "episode_types": episode_types,
            "revision": revision,
            "order": order.value,
            "id": last["id"],
        }
        if season_id is not None:
            values["index"] = last["index"]
        else:
            published_at = last["published_date"]
            values["published_at"] = (
                published_at.isoformat() if published_at is not None else None
            )
        next_cursor = encode_cursor(values)

    return EpisodeAPIReadViewPage(
        items=items,
        limit=limit,
        total=total,
        collection_total=collection_total,
        next_cursor=next_cursor,
        revision=revision,
    )


def get_recently_indexed_episodes(
        s: Session,
        *,
        limit: int,
) -> list[EpisodeIndexedActivityAPIRead]:
    """Return the newest episode records by the time VODLoft indexed them."""
    rows = s.execute(
        select(
            Episode.id.label("id"),
            Episode.title.label("title"),
            Episode.slug.label("slug"),
            Episode.created_at.label("indexed_at"),
            Collection.title.label("collection_title"),
            Collection.slug.label("collection_slug"),
        )
        .select_from(Episode)
        .join(Collection, Episode.collection_id == Collection.id)
        .order_by(Episode.created_at.desc(), Episode.id.desc())
        .limit(limit)
    ).mappings().all()

    return [
        EpisodeIndexedActivityAPIRead.model_validate(row)
        for row in rows
    ]


def get_episode(s: Session, episode_slug: str) -> EpisodeAPIRead:
    episode = (
        s.query(Episode)
        .filter_by(slug=episode_slug)
        .one_or_none()
    )

    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    return _episode_api_read(episode)


def request_episode_metadata_refresh(
        s: Session,
        episode_slug: str,
) -> dict[str, bool | int | str]:
    episode = (
        s.query(Episode)
        .filter_by(slug=episode_slug)
        .one_or_none()
    )
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not refreshes_metadata(episode.source_key):
        raise HTTPException(
            status_code=409,
            detail="This episode is kept up to date by the daily catalogue refresh",
        )

    target = OperationTargetSpec(
        task_key=_METADATA_REFRESH_TASK_KEY,
        resource_type="episode",
        resource_id=episode.id,
    )
    collection = episode.collection
    operation = create_operation(
        s,
        kind="episode.refresh_metadata",
        resource_type="episode",
        resource_id=episode.id,
        title=episode.title,
        targets=[target],
        context={
            "episode_slug": episode.slug,
            "episode_title": episode.title,
            "collection_id": episode.collection_id,
            "collection_slug": collection.slug if collection is not None else None,
            "collection_title": collection.title if collection is not None else None,
        },
    )
    if queue_operation_target_dispatch(s, operation.id, target.resolved_slot_key()):
        episode.metadata_is_final = False
    s.flush()
    return {
        "queued": True,
        "episode_id": episode.id,
        "operation_id": operation.id,
    }


def request_episode_early_delete(
        s: Session,
        episode_slug: str,
) -> dict[str, bool | str]:
    """Queue an immediate no-usable-media verification for a confirmed missing episode."""
    episode = (
        s.query(Episode)
        .filter_by(slug=episode_slug)
        .one_or_none()
    )
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not episode.early_delete_available:
        raise HTTPException(
            status_code=409,
            detail="Early Delete is only available after Daily Wire has returned 404 for this episode",
        )

    collection = episode.collection
    target = OperationTargetSpec(
        task_key=_EARLY_DELETE_TASK_KEY,
        resource_type="collection",
        resource_id=episode.collection_id,
        task_kwargs={
            "episode_id": episode.id,
            "force": True,
        },
        slot_key=f"{_EARLY_DELETE_TASK_KEY}:episode:{episode.id}:force",
    )
    operation = create_operation(
        s,
        kind="episode.early_delete",
        resource_type="episode",
        resource_id=episode.id,
        title=episode.title,
        targets=[target],
        context={
            "episode_slug": episode.slug,
            "episode_title": episode.title,
            "collection_id": episode.collection_id,
            "collection_slug": collection.slug if collection is not None else None,
            "collection_title": collection.title if collection is not None else None,
        },
    )
    queue_operation_target_dispatch(s, operation.id, target.resolved_slot_key())
    s.flush()
    return {
        "queued": True,
        "operation_id": operation.id,
    }


def create_episode(s: Session, body: EpisodeAPICreate) -> EpisodeAPIRead:
    collection = s.get(Collection, body.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    episode = create_database_fields(Episode, body)
    # An episode comes from its collection's Source.
    episode.source_key = collection.source_key
    s.add(episode)
    s.flush()

    record_publication_lifecycle_observation(
        episode,
        old_status=None,
        new_status=EpisodePublishStatus(episode.publish_status),
    )

    queue_event(s, "episode.added", {
        "resource_id": episode.id,
        "id": episode.id,
        "slug": episode.slug,
        "collection_id": episode.collection_id,
        "status": episode.publish_status
    })
    request_collection_custom_index_reconciliation(s, episode.collection_id)

    return _episode_api_read(episode)


def update_episode(s: Session, episode_slug: str, body: EpisodeAPIUpdate) -> EpisodeAPIRead:
    episode: Optional[Episode] = (
        s.query(Episode)
        .filter_by(slug=episode_slug)
        .one_or_none()
    )
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    old_status = episode.publish_status

    # Apply updates and flush; commit in router
    update_database_fields(episode, body)
    s.flush()

    # Emit status-specific events if status changed
    if hasattr(body, 'publish_status') and body.publish_status is not None and body.publish_status != old_status:
        new_status = EpisodePublishStatus(body.publish_status)
        record_publication_lifecycle_observation(
            episode,
            old_status=old_status,
            new_status=new_status,
        )

        event_data = {
            "old_status": old_status,
            "status": body.publish_status,
            "resource_id": episode.id,
            "id": episode.id,
            "slug": episode.slug,
            "collection_id": episode.collection_id,
        }
        queue_event(s, "episode.status_updated", event_data)

        if new_status is EpisodePublishStatus.PUBLISHED_FINAL:
            queue_event(s, "episode.published_final", event_data)
        elif new_status is EpisodePublishStatus.PUBLISHED_PRELIMINARY:
            queue_event(s, "episode.published_preliminary", event_data)

    request_collection_custom_index_reconciliation(s, episode.collection_id)
    return _episode_api_read(episode)


def delete_episode(s: Session, episode_slug: str) -> EpisodeAPIRead:
    episode = (
        s.query(Episode)
        .filter_by(slug=episode_slug)
        .one_or_none()
    )
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    payload = _episode_api_read(episode)

    media_download = s.scalar(
        select(EpisodeMediaDownload.id).where(
            EpisodeMediaDownload.media_item_id == episode.id,
        ).limit(1)
    )
    if media_download is not None:
        raise HTTPException(
            status_code=409,
            detail="This episode owns persistent download history and can only be removed with its collection",
        )

    queue_event(s, "episode.deleted", {
        "resource_id": episode.id,
        "id": episode.id,
        "slug": episode.slug,
        "collection_id": episode.collection_id
    })
    request_collection_custom_index_reconciliation(s, episode.collection_id)

    s.delete(episode)
    s.flush()
    return payload
