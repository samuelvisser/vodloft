"""The note on Home that asks for an API key can be put off or turned off.

Revision ID: 6943fdf59ef3
Revises: a3c81e6f0d52
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "6943fdf59ef3"
down_revision = "a3c81e6f0d52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings", sa.Column(
        "api_key_note_after", sa.DateTime(timezone=True), nullable=True,
        comment="Until when Home does not ask for an API key, after Remind me later",
    ))
    op.add_column("settings", sa.Column(
        "api_key_note_off", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Home never asks for an API key",
    ))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("api_key_note_off")
        batch.drop_column("api_key_note_after")
