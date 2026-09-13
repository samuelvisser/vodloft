"""durable task system and application settings

Revision ID: 0004_task_system_and_settings
Revises: 0003_profile_alignment
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0004_task_system_and_settings"
down_revision = "0003_profile_alignment"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "task_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("allowed_resource_types", sa.JSON(), nullable=False),
        sa.Column("default_max_retries", sa.Integer(), nullable=True),
        sa.Column("tracks_progress", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_task_definitions_key", "task_definitions", ["key"])

    op.create_table(
        "task_operations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("total_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("canceled_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_task_operations_source", "task_operations", ["source"])
    op.create_index("ix_task_operations_status", "task_operations", ["status"])

    op.create_table(
        "task_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("task_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("registry_key", sa.String(length=255), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=False, server_default="system"),
        sa.Column("resource_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="cron"),
        sa.Column("trigger_args", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("coalesce", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("next_run_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("registry_key"),
    )
    op.create_index("ix_task_schedules_definition_id", "task_schedules", ["definition_id"])
    op.create_index("ix_task_schedules_source", "task_schedules", ["source"])
    op.create_index("ix_task_schedules_resource_type", "task_schedules", ["resource_type"])
    op.create_index("ix_task_schedules_resource_id", "task_schedules", ["resource_id"])
    op.create_index("ix_task_schedules_active", "task_schedules", ["active"])

    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("task_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("task_schedules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("task_operations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dedupe_key", sa.String(length=512), nullable=True),
        sa.Column("priority_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runtime_seconds", sa.Float(), nullable=True),
        *_timestamps(),
    )
    for column in ("definition_id", "schedule_id", "operation_id", "resource_type", "resource_id", "source", "status", "dedupe_key", "priority_at"):
        op.create_index(f"ix_task_runs_{column}", "task_runs", [column])


    op.add_column("media_downloads", sa.Column("task_run_id", sa.Integer(), nullable=True))
    op.create_index("ix_media_downloads_task_run_id", "media_downloads", ["task_run_id"])

    op.create_table(
        "application_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alembic_version_num", sa.String(length=64), nullable=True),
        sa.Column("auth_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("admin_username", sa.String(length=128), nullable=False, server_default="admin"),
        sa.Column("admin_password_hash", sa.Text(), nullable=True),
        sa.Column("session_secret", sa.String(length=255), nullable=False),
        sa.Column("rss_token", sa.String(length=255), nullable=False),
        sa.Column("rss_item_limit", sa.Integer(), nullable=False, server_default="200"),
        *_timestamps(),
        sa.UniqueConstraint("rss_token"),
    )

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "application_settings",
            sa.column("id", sa.Integer()),
            sa.column("onboarding_completed", sa.Boolean()),
            sa.column("auth_enabled", sa.Boolean()),
            sa.column("admin_username", sa.String()),
            sa.column("session_secret", sa.String()),
            sa.column("rss_token", sa.String()),
            sa.column("rss_item_limit", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [{
            "id": 1,
            "onboarding_completed": False,
            "auth_enabled": False,
            "admin_username": "admin",
            "session_secret": secrets.token_urlsafe(48),
            "rss_token": secrets.token_urlsafe(32),
            "rss_item_limit": 200,
            "created_at": now,
            "updated_at": now,
        }],
    )


def downgrade() -> None:
    op.drop_table("application_settings")
    op.drop_index("ix_media_downloads_task_run_id", table_name="media_downloads")
    op.drop_column("media_downloads", "task_run_id")
    for column in ("priority_at", "dedupe_key", "status", "source", "resource_id", "resource_type", "operation_id", "schedule_id", "definition_id"):
        op.drop_index(f"ix_task_runs_{column}", table_name="task_runs")
    op.drop_table("task_runs")
    for name in ("active", "resource_id", "resource_type", "source", "definition_id"):
        op.drop_index(f"ix_task_schedules_{name}", table_name="task_schedules")
    op.drop_table("task_schedules")
    op.drop_index("ix_task_operations_status", table_name="task_operations")
    op.drop_index("ix_task_operations_source", table_name="task_operations")
    op.drop_table("task_operations")
    op.drop_index("ix_task_definitions_key", table_name="task_definitions")
    op.drop_table("task_definitions")
