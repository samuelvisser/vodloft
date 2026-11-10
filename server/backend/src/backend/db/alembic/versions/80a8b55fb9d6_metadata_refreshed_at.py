"""Remember when each episode and video was last looked up at its Source.

The metadata refresh sweep decides from it which items are due, so a restart no longer makes it look every
unsettled item up again. Existing items start without a time: those with a refresh point already behind them are
looked up once by the next sweep.

Revision ID: 80a8b55fb9d6
Revises: 4a35f3a5b8ed
Create Date: 2026-11-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "80a8b55fb9d6"
down_revision = "4a35f3a5b8ed"
branch_labels = None
depends_on = None

_COMMENT = "When VODLoft last looked the {} up at its Source, by a refresh or a manual Refresh now"


def upgrade() -> None:
    op.add_column("media_items_episode", sa.Column(
        "metadata_refreshed_at", sa.DateTime(timezone=True), nullable=True, comment=_COMMENT.format("episode"),
    ))
    op.add_column("media_items_video", sa.Column(
        "metadata_refreshed_at", sa.DateTime(timezone=True), nullable=True, comment=_COMMENT.format("video"),
    ))


def downgrade() -> None:
    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_column("metadata_refreshed_at")
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("metadata_refreshed_at")
