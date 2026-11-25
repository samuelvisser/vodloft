"""While every list of a channel is in, the lists are seasons of their own or contents only, together.

Revision ID: 0421aa4848d2
Revises: 4b9e2d7c1a60
Create Date: 2026-11-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0421aa4848d2"
down_revision = "4b9e2d7c1a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "lists_as_seasons", sa.Boolean(), nullable=False, server_default=sa.true(),
        comment="While every list is in (link_seasons all): whether each list is a season of its own, or only adds its "
                "videos to the channel's own seasons, as a feed does",
    ))


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("lists_as_seasons")
    else:
        op.drop_column("collections", "lists_as_seasons")
