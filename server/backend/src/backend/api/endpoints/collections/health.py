"""The collection health check: what it found that needs the user, its checks, and the user's answers to its
suggestions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.api.endpoints.creators.service import collection_link, look_up_collection_creator
from backend.api.models.collection_health import (
    HealthCheckAPIRead, HealthCheckAPIUpdate, HealthChecksAPIRead, LibraryHealthAPIRead, SuggestionAnswerAPIIn,
)
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in
from backend.services import collection_health as health
from backend.services import creators
from backend.services.errors import ServiceError
from backend.types.collection_health_types import HealthIssueKind

router = APIRouter(prefix="/health", tags=["Collection health"])


@router.get("", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=LibraryHealthAPIRead)
def library_health():
    """Every collection that needs the user, with what for, as each stored its health, and the creators whose
    collections the user could group."""
    with db_session() as s:
        try:
            return LibraryHealthAPIRead.model_validate({
                "collections": health.unhealthy_collections(s),
                "creator_suggestions": health.creator_suggestions(s),
            }, from_attributes=True)
        finally:
            s.rollback()


def _checks(s) -> HealthChecksAPIRead:
    off = health.checks_off(s)
    return HealthChecksAPIRead(
        checks=[
            HealthCheckAPIRead(kind=kind, title=health.TITLES[kind.value], on=kind.value not in off)
            for kind in HealthIssueKind
        ],
        dismissed=health.dismissed_count(s),
    )


@router.get("/checks", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=HealthChecksAPIRead)
def health_checks():
    """The checks of the collection health check, which are on, and how many suggestions the user put away."""
    with db_session() as s:
        try:
            return _checks(s)
        finally:
            s.rollback()


@router.put("/checks/{kind}", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=HealthChecksAPIRead)
def health_check_update(kind: HealthIssueKind, body: HealthCheckAPIUpdate):
    """Turn one check on or off. Home shows what a check found only while it is on."""
    run_write_transaction(lambda s: health.set_check(s, kind, body.on), concurrent=True)
    return health_checks()


@router.delete("/dismissals", dependencies=[requires(Area.LIBRARY, Level.MANAGE)], response_model=HealthChecksAPIRead)
def health_dismissals_reset():
    """Show every suggestion the user put off or dismissed again."""
    run_write_transaction(health.reset_dismissals, concurrent=True)
    return health_checks()


@router.post(
    "/creators/{site_key}/{ref}/answer", dependencies=[requires(Area.LIBRARY, Level.MANAGE)],
    status_code=status.HTTP_204_NO_CONTENT,
)
def creator_suggestion_answer(site_key: str, ref: str, body: SuggestionAnswerAPIIn):
    """Put a suggestion to group a creator's collections off for a week, or dismiss it for good."""
    subject = health.creator_subject(site_key, ref)
    run_write_transaction(
        lambda s: health.put_off_suggestion(s, HealthIssueKind.CREATORS, subject, for_good=body.answer == "dismiss"),
        concurrent=True,
    )


@router.post("/creators/{site_key}/{ref}/group", dependencies=[requires(Area.LIBRARY, Level.MANAGE)])
def creator_suggestion_group(site_key: str, ref: str, access: Access = signed_in()):
    """Group the collections of a suggestion under their creator, adding the creator when they are not in the
    Library. Nothing the collections hold changes. Answers with the creator's slug."""
    with db_session() as s:
        try:
            collections = health.suggested_collections(s, site_key, ref)
            if not collections:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "There is nothing left to group for this creator")
            slugs = [collection.slug for collection in collections]
            link = collection_link(s, slugs[0])
        finally:
            s.rollback()
    # Slow: asks the Site who the creator is, before the write transaction.
    details = look_up_collection_creator(link)
    if details.ref != ref:
        raise ServiceError("The Site names another creator behind these collections now: run the health check again")

    def group(w) -> str:
        from backend.db.models import Collection
        from sqlalchemy import select

        found = {collection.slug: collection for collection in w.scalars(select(Collection).where(Collection.slug.in_(slugs)))}
        first = found[slugs[0]]
        creator = creators.join_creator_of(w, first, link.source_key, details, added_by_id=access.user_id)
        for slug in slugs[1:]:
            collection = found.get(slug)
            if collection is not None and collection.creator_id is None:
                creators.join_creator(w, collection, creator)
        return creator.slug

    return {"creatorSlug": run_write_transaction(group)}
