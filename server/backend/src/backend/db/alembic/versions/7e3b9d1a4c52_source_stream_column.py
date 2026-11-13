"""Stream profiles stream from any Source whose Site can stream, not only The Daily Wire.

``use_dw_stream`` becomes ``use_source_stream``; its values stay as they are.

Revision ID: 7e3b9d1a4c52
Revises: cbad9977fd7b
Create Date: 2026-11-05
"""
from __future__ import annotations

from alembic import op

revision = "7e3b9d1a4c52"
down_revision = "cbad9977fd7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stream_profiles") as batch:
        batch.alter_column(
            "use_dw_stream", new_column_name="use_source_stream",
            comment="Stream episodes straight from their Source when the collection's Site can stream",
        )


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles") as batch:
        batch.alter_column(
            "use_source_stream", new_column_name="use_dw_stream",
            comment="Use direct DW stream endpoints for stream",
        )
