"""Remember which Source the user prefers for a domain that several Sources claim.

Revision ID: f7b2d4e6a913
Revises: e3c9a7b5d214
Create Date: 2026-10-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f7b2d4e6a913"
down_revision = "e3c9a7b5d214"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_domain_preferences",
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column(
            "source_key", sa.String(), nullable=False,
            comment="Id of the preferred Source, as registered in sources",
        ),
        sa.PrimaryKeyConstraint("domain", name=op.f("pk_source_domain_preferences")),
    )


def downgrade() -> None:
    op.drop_table("source_domain_preferences")
