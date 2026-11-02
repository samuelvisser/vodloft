"""Which episodes: your own filter lines, keeping downloads, and retention from the download date.

Revision ID: 1c60d6815b6b
Revises: b918e345f620
Create Date: 2026-11-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "1c60d6815b6b"
down_revision = "b918e345f620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_profile_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "download_profile_id",
            sa.Integer(),
            sa.ForeignKey("download_profiles.id", ondelete="CASCADE", name="fk_download_profile_rules_download_profile_id_download_profiles"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, comment="Order of the line within the profile, from 0"),
        sa.Column("action", sa.String(16), nullable=False, comment="skip, only or keep"),
        sa.Column("field", sa.String(16), nullable=False, comment="title, description or duration"),
        sa.Column("pattern", sa.String(), nullable=True, comment="The regular expression of a title or description rule"),
        sa.Column("ignore_case", sa.Boolean(), nullable=False),
        sa.Column("duration_operator", sa.String(16), nullable=True, comment="shorter or longer, for a duration rule"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
    )
    op.create_index("ix_download_profile_rules_download_profile_id", "download_profile_rules", ["download_profile_id"])
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(
            sa.Column(
                "retention_from", sa.String(16), nullable=False, server_default="published",
                comment="Whether a date window deletes episodes N days after publication or after downloading",
            )
        )
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.add_column(
            sa.Column(
                "kept", sa.Boolean(), nullable=False, server_default="0",
                comment="Kept by hand: retention never deletes this download",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.drop_column("kept")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("retention_from")
    op.drop_index("ix_download_profile_rules_download_profile_id", table_name="download_profile_rules")
    op.drop_table("download_profile_rules")
