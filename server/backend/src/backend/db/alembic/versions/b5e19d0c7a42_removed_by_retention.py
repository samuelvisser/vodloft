"""Media a Site removed itself, as it removes all its media after a while.

Revision ID: b5e19d0c7a42
Revises: 710584a17632
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5e19d0c7a42"
down_revision = "710584a17632"
branch_labels = None
depends_on = None

COMMENT = "The Site removed the media itself, as it removes all its media after a while (its retention)"


def upgrade() -> None:
    op.add_column(
        "media_items", sa.Column("removed_by_retention", sa.Boolean(), nullable=False, server_default=sa.false(), comment=COMMENT),
    )


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("removed_by_retention")
