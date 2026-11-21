"""Media a Site removes itself after a while counts as removed by the Site's retention from a time on, not by a flag.

Revision ID: 6007aa686523
Revises: b5e19d0c7a42
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "6007aa686523"
down_revision = "b5e19d0c7a42"
branch_labels = None
depends_on = None

COMMENT = (
    "While the Source no longer has the media: from when its Site's retention may have removed it, the least time "
    "the Site keeps media after publication, less a little leeway"
)
OLD_COMMENT = "The Site removed the media itself, as it removes all its media after a while (its retention)"


def upgrade() -> None:
    op.add_column("media_items", sa.Column("retention_due_at", sa.DateTime(timezone=True), nullable=True, comment=COMMENT))
    # Media already counted as removed by its Site's retention was due by then.
    op.execute("UPDATE media_items SET retention_due_at = updated_at WHERE removed_by_retention")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("removed_by_retention")


def downgrade() -> None:
    op.add_column(
        "media_items",
        sa.Column("removed_by_retention", sa.Boolean(), nullable=False, server_default=sa.false(), comment=OLD_COMMENT),
    )
    op.execute(
        "UPDATE media_items SET removed_by_retention = TRUE "
        "WHERE removed_from_source AND retention_due_at IS NOT NULL AND retention_due_at <= CURRENT_TIMESTAMP"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("retention_due_at")
