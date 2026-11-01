"""Remember who asked for each operation.

Revision ID: c0844e0acfe7
Revises: 6719db3d610f
Create Date: 2026-11-01

With user accounts on, people without access to Tasks only see the
operations they asked for. Existing operations have no requester.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c0844e0acfe7"
down_revision = "6719db3d610f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_operations") as batch:
        batch.add_column(sa.Column(
            "requested_by_user_id", sa.Integer(), nullable=True,
            comment="The user whose request created this operation; null for VODLoft's own work or without user accounts",
        ))
        batch.create_index(batch.f("ix_task_operations_requested_by_user_id"), ["requested_by_user_id"], unique=False)
        batch.create_foreign_key(
            batch.f("fk_task_operations_requested_by_user_id_users"), "users",
            ["requested_by_user_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("task_operations") as batch:
        batch.drop_constraint(batch.f("fk_task_operations_requested_by_user_id_users"), type_="foreignkey")
        batch.drop_index(batch.f("ix_task_operations_requested_by_user_id"))
        batch.drop_column("requested_by_user_id")
