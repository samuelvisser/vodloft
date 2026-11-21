"""Each of a creator's accounts keeps its own banner, which its own collection shows as its background.

Revision ID: 250f37a05db0
Revises: 148e116c354b
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "250f37a05db0"
down_revision = "148e116c354b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creator_accounts",
        sa.Column("banner_path", sa.String(), nullable=True, comment="The account's own banner on its Site"),
    )
    # The creator's banner is that of their first account; a background migration looks the others up.
    op.execute(
        "UPDATE creator_accounts SET banner_path = "
        "(SELECT creators.banner_path FROM creators WHERE creators.id = creator_accounts.creator_id) "
        "WHERE id IN (SELECT MIN(earliest.id) FROM creator_accounts earliest GROUP BY earliest.creator_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("creator_accounts") as batch:
        batch.drop_column("banner_path")
