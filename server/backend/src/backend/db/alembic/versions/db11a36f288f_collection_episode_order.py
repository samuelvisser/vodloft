"""A Collection chooses which way its episodes are listed.

Seasonal Collections start each season at its first episode and every other Collection lists its
newest episode first, the order the Collection page already showed.

Revision ID: db11a36f288f
Revises: 28c70478078a
Create Date: 2026-11-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "db11a36f288f"
down_revision = "28c70478078a"
branch_labels = None
depends_on = None

_COMMENT = "Which way the episodes are listed, within each season for a seasonal Collection: newest_first or oldest_first"


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("episode_order", sa.String(), nullable=True, comment=_COMMENT))
    op.execute(sa.text(
        "UPDATE collections SET episode_order = CASE WHEN episode_identifier = 'seasonal' THEN 'oldest_first' ELSE 'newest_first' END"
    ))
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("episode_order", existing_type=sa.String(), nullable=False, existing_comment=_COMMENT)


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("episode_order")
