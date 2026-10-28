"""Give Local Media Profiles a subtitle mode: none, embedded, sidecar files, or both.

Revision ID: e6a2c9d4f817
Revises: b93d5e7a1c42
Create Date: 2026-10-28

Ported from WireLoft 1.2.5. Movie profiles and show profiles that cover series
save subtitles as sidecar files on their next download; podcast-only show
profiles and single-video profiles get none.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e6a2c9d4f817"
down_revision = "b93d5e7a1c42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "local_media_profiles",
        sa.Column("subtitle_mode", sa.String(length=24), nullable=False, server_default="no_subtitles"),
    )
    op.execute(sa.text("""
        UPDATE local_media_profiles
        SET subtitle_mode = 'sidecar'
        WHERE type = 'movie' OR (type = 'show' AND id IN (
            SELECT id FROM local_media_profiles_show
            WHERE show_scope IN ('series', 'both')
        ))
    """))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.alter_column(
            "subtitle_mode",
            existing_type=sa.String(length=24),
            existing_nullable=False,
            server_default="sidecar",
        )


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("subtitle_mode")
