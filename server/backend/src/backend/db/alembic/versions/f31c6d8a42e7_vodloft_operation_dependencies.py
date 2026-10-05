"""Add composable TaskOperation dependencies and aggregate completion progress.

Revision ID: f31c6d8a42e7
Revises: 6e7a9d13c2f0
"""
from alembic import op
import sqlalchemy as sa


revision = "f31c6d8a42e7"
down_revision = "6e7a9d13c2f0"
branch_labels = None
depends_on = None


def _upgrade_operation_dependencies() -> None:
    op.add_column(
        "task_operations",
        sa.Column(
            "completion_progress",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
    )
    op.execute(sa.text("""
        UPDATE task_operations
        SET completion_progress = CASE
            WHEN status IN ('SUCCEEDED', 'FAILED', 'PARTIAL', 'CANCELED') THEN 100
            ELSE COALESCE(progress, 0)
        END
    """))

    op.create_table(
        "task_operation_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "parent_operation_id",
            sa.String(length=36),
            sa.ForeignKey("task_operations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_operation_id",
            sa.String(length=36),
            sa.ForeignKey("task_operations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slot_key", sa.String(length=255), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("1")),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cancel_policy", sa.String(length=32), nullable=False, server_default="detach"),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "parent_operation_id",
            "slot_key",
            name="uq_task_operation_dependencies_parent_slot",
        ),
        sa.UniqueConstraint(
            "parent_operation_id",
            "child_operation_id",
            name="uq_task_operation_dependencies_parent_child",
        ),
    )
    op.create_index(
        "ix_task_operation_dependencies_parent_operation_id",
        "task_operation_dependencies",
        ["parent_operation_id"],
    )
    op.create_index(
        "ix_task_operation_dependencies_child_operation_id",
        "task_operation_dependencies",
        ["child_operation_id"],
    )
    op.create_index(
        "ix_task_runs_definition_status_resource_started_id",
        "task_runs",
        ["definition_id", "status", "resource_type", "resource_id", "started_at", "id"],
    )


def _downgrade_operation_dependencies() -> None:
    op.drop_index(
        "ix_task_runs_definition_status_resource_started_id",
        table_name="task_runs",
    )
    op.drop_index(
        "ix_task_operation_dependencies_child_operation_id",
        table_name="task_operation_dependencies",
    )
    op.drop_index(
        "ix_task_operation_dependencies_parent_operation_id",
        table_name="task_operation_dependencies",
    )
    op.drop_table("task_operation_dependencies")
    with op.batch_alter_table("task_operations") as batch:
        batch.drop_column("completion_progress")


def upgrade() -> None:
    _upgrade_operation_dependencies()


def downgrade() -> None:
    _downgrade_operation_dependencies()
