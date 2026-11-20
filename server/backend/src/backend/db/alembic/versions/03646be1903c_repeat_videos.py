"""A video in several seasons: a collection can give a video that belongs in several of its seasons an episode in
each, as an artist's albums each show every track they have. Music collections do, others keep one episode.

Revision ID: 03646be1903c
Revises: 4b9e1d7c2a60
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "03646be1903c"
down_revision = "4b9e1d7c2a60"
branch_labels = None
depends_on = None

COMMENT = (
    "What happens with a video that belongs in several of its seasons: one_season, an episode in the first, "
    "or each_season, an episode in each"
)
OLD = "uq_episode_collection_source_slug"
NEW = "uq_episode_season_source_slug"


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "repeat_videos", sa.String(), nullable=False, server_default="one_season", comment=COMMENT,
    ))
    op.execute("UPDATE collections SET repeat_videos = 'each_season' WHERE type = 'music'")
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_constraint(OLD, type_="unique")
        batch.create_unique_constraint(NEW, ["season_id", "source_slug"])


def downgrade() -> None:
    # Only one episode of each video can stay in a collection: the first one.
    extra = (
        "SELECT id FROM media_items_episode WHERE id NOT IN ("
        "SELECT MIN(id) FROM media_items_episode GROUP BY collection_id, source_slug)"
    )
    op.execute(f"DELETE FROM media_items WHERE id IN ({extra})")
    op.execute(f"DELETE FROM media_items_episode WHERE id IN ({extra})")
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_constraint(NEW, type_="unique")
        batch.create_unique_constraint(OLD, ["collection_id", "source_slug"])
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("repeat_videos")
