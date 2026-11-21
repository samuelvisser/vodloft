"""Bulk edit in the Library: deleting many creators at once."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.models.profile_bulk import BulkResultRead, BulkSelectionIn
from backend.db.models import Creator
from backend.services import creators


def delete_creators(s: Session, body: BulkSelectionIn) -> BulkResultRead:
    """Take the chosen creators out of the Library, as their Edit page does; their collections stay as plain ones."""
    chosen = s.scalars(select(Creator).where(Creator.id.in_(body.ids))).all()
    for creator in chosen:
        creators.delete_creator(s, creator)
    return BulkResultRead(done=len(chosen), skipped=[])
