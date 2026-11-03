"""The Download Profiles an import found on in the other program.

Revision ID: 4b8e1d27a6c3
Revises: 52898e635c27
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "4b8e1d27a6c3"
down_revision = "52898e635c27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.add_column(sa.Column(
            "download_profiles_on", sa.JSON(), nullable=False, server_default="[]",
            comment="The Download Profiles that were on in the other program, by id",
        ))


def downgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.drop_column("download_profiles_on")
