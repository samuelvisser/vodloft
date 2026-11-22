"""Bulk edit in the Library: deleting many creators at once."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.creator import CreatorBulkDeleteIn
from backend.api.models.profile_bulk import BulkResultRead
from backend.db.models import Creator

from .service import remove_creator


def delete_creators(s: Session, body: CreatorBulkDeleteIn) -> BulkResultRead:
    """Take the chosen creators out of the Library, as their Edit page does: their collections stay as plain ones,
    or go with them."""
    chosen = s.scalars(select(Creator).where(Creator.id.in_(body.ids))).all()
    for creator in chosen:
        remove_creator(s, creator, with_collections=body.delete_collections)
    return BulkResultRead(done=len(chosen), skipped=[])
