"""Upgrade the VODLoft 0.3.1 schema to 0.4.0.

Revision ID: e6a2c9d4f817
Revises: c41e7a9d3f58
Create Date: 2026-10-28

The single release migration for 0.4.0. It adds the quick download history,
a subtitle mode on Local Media Profiles, and moves the global episode scans
from show 0 to no resource (both ported from WireLoft 1.2.5).
It keeps the revision of the last 0.4.0 prerelease migration, so a database
that already ran both prerelease migrations stays at the current head.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e6a2c9d4f817"
down_revision = "c41e7a9d3f58"
branch_labels = None
depends_on = None


# Quick download history ------------------------------------------------------
# What was downloaded, from where, as what, and how each one ended.


def _upgrade_quick_download_history() -> None:
    op.create_table(
        "quick_download_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quick_download_id", sa.String(), nullable=False, comment="Id of the quick download's ready folder"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False, comment="Id of the Source, as registered in sources"),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False, comment="The choice as people read it, such as 'Video · 1080p MP4'"),
        sa.Column("choice", sa.JSON(), nullable=False, comment="The choice, to download it again the same way"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome", sa.String(), nullable=False,
            comment="working, ready, downloaded, expired, discarded, canceled, failed or refused",
        ),
        sa.Column("message", sa.String(), nullable=True, comment="Why it failed or was refused"),
        sa.Column("owner", sa.String(), nullable=True, comment="The user who asked for it, once VODLoft has users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quick_download_history")),
        sa.UniqueConstraint("quick_download_id", name=op.f("uq_quick_download_history_quick_download_id")),
    )
    op.create_index("ix_quick_download_history_started_at", "quick_download_history", ["started_at"])



def _downgrade_quick_download_history() -> None:
    op.drop_index("ix_quick_download_history_started_at", table_name="quick_download_history")
    op.drop_table("quick_download_history")


# Local Media Profile subtitles ----------------------------------------------
# Movie profiles and show profiles that cover series save subtitles as sidecar
# files on their next download; podcast-only show profiles and single-video
# profiles get none.


def _upgrade_subtitle_mode() -> None:
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



def _downgrade_subtitle_mode() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("subtitle_mode")


# Global episode scans --------------------------------------------------------
# Find new episodes and the full re-scan used show 0 for "all shows"; they now
# run without a resource.

_GLOBAL_SCAN_TASK_KEYS = "('fetch_new_episodes', 'rescan_quick_checked_shows')"


def _set_global_scan_resource_id(old: str, new: str) -> None:
    op.execute(sa.text(f"""
        UPDATE task_runs
        SET resource_id = {new}
        WHERE resource_id {old}
          AND definition_id IN (
              SELECT id FROM task_definitions WHERE key IN {_GLOBAL_SCAN_TASK_KEYS}
          )
    """))
    op.execute(sa.text(f"""
        UPDATE task_operation_targets
        SET resource_id = {new}
        WHERE resource_id {old} AND task_key IN {_GLOBAL_SCAN_TASK_KEYS}
    """))


def _upgrade_global_scan_resource() -> None:
    _set_global_scan_resource_id("= 0", "NULL")


def _downgrade_global_scan_resource() -> None:
    _set_global_scan_resource_id("IS NULL", "0")


# Release migration -----------------------------------------------------------


def upgrade() -> None:
    _upgrade_quick_download_history()
    _upgrade_subtitle_mode()
    _upgrade_global_scan_resource()


def downgrade() -> None:
    _downgrade_global_scan_resource()
    _downgrade_subtitle_mode()
    _downgrade_quick_download_history()
