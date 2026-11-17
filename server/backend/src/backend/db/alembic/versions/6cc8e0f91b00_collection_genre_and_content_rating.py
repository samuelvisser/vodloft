"""Add a genre and a content rating to Collections, for the NFO files media servers read.

Revision ID: 6cc8e0f91b00
Revises: b54038f5c9f6
Create Date: 2026-11-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "6cc8e0f91b00"
down_revision = "b54038f5c9f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collections", sa.Column("genre", sa.String(), nullable=True, comment="The show's genre in its NFO files"))
    op.add_column("collections", sa.Column(
        "content_rating", sa.String(), nullable=True, comment="The show's content rating in its NFO files, such as TV-14",
    ))


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("content_rating")
        batch.drop_column("genre")
