from typing import Optional

from backend.db.models import Collection, Episode

from sqlalchemy.orm import Session


def get_collection_from_params(s: Session, *,
                         episode_id: Optional[int] = None,
                         episode_slug: Optional[str] = None,
                         collection_id: Optional[int] = None,
                         collection_slug: Optional[str] = None) -> Optional[Collection]:
    if collection_id is not None:
        return s.get(Collection, collection_id)
    if collection_slug is not None:
        return s.query(Collection).filter(Collection.slug == collection_slug).first()
    if episode_id is not None:
        episode = s.get(Episode, episode_id)
        return episode.collection if episode is not None else None
    if episode_slug is not None:
        episode = s.query(Episode).filter(Episode.slug == episode_slug).first()
        return episode.collection if episode is not None else None
    return None