from sqlalchemy import UniqueConstraint

from backend.db.models import Season


def test_season_slug_uniqueness_is_scoped_to_collection():
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in Season.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("collection_id", "slug") in unique_columns
    assert ("collection_id", "index") in unique_columns
    assert Season.__table__.c.slug.unique is not True
