"""A Collection chooses which way its episodes are listed.

Podcasts list their newest episode first and series their first episode first, the order RSS feeds
already gave podcast apps. A seasonal Collection orders the episodes of each season.

Revision ID: db11a36f288f
Revises: d6346ad993ee
Create Date: 2026-11-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "db11a36f288f"
down_revision = "d6346ad993ee"
branch_labels = None
depends_on = None

_COMMENT = "Which way the episodes are listed, within each season for a seasonal Collection: newest_first or oldest_first"


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("episode_order", sa.String(), nullable=True, comment=_COMMENT))
    op.execute(sa.text(
        "UPDATE collections SET episode_order = CASE WHEN type = 'podcast' THEN 'newest_first' ELSE 'oldest_first' END"
    ))
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("episode_order", existing_type=sa.String(), nullable=False, existing_comment=_COMMENT)


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("episode_order")
