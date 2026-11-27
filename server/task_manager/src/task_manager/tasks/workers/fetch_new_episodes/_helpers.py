from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Collection


def get_collections(s: Session, *, collection_id: Optional[int], collection_slug: Optional[str]) -> Sequence[Collection]:
    """Resolve one Collection, or all collections when no collection is given."""
    if collection_slug:
        collection = s.scalar(select(Collection).where(Collection.slug == collection_slug))
        return [collection] if collection is not None else []

    if collection_id is not None:
        collection = s.get(Collection, collection_id)
        return [collection] if collection is not None else []

    return s.scalars(select(Collection)).all()
