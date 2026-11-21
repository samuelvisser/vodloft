"""A creator's name can be changed in VODLoft, and the collections of a creator take its name as their author.

Revision ID: ad2922b7ff06
Revises: 6943fdf59ef3
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ad2922b7ff06"
down_revision = "6943fdf59ef3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("creators", sa.Column(
        "title_from_user", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="The name was changed in VODLoft, so the Site's name no longer replaces it",
    ))
    op.execute(
        "UPDATE collections SET author_name = (SELECT creators.title FROM creators WHERE creators.id = collections.creator_id) "
        "WHERE creator_id IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("creators") as batch:
        batch.drop_column("title_from_user")
