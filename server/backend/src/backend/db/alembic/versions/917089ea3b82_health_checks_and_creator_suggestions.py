"""The collection health check finds the creator behind collections, and the user can turn its checks off and put
off its suggestions.

Revision ID: 917089ea3b82
Revises: 4bbdb41cdaac
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op



revision = "917089ea3b82"
down_revision = "4bbdb41cdaac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "site_creator_ref", sa.String(), nullable=True,
        comment="The Site's id of the creator behind its link, as the collection health check found it, for suggesting "
                "to group a creator's collections; null when none was found or it has not been looked up",
    ))
    op.add_column("collections", sa.Column(
        "site_creator_url", sa.String(), nullable=True,
        comment="The link that site_creator_ref was looked up for: a link it no longer has is looked up again",
    ))
    op.create_index("ix_collections_site_creator_ref", "collections", ["site_creator_ref"])
    op.add_column("settings", sa.Column(
        "health_checks_off", sa.JSON(), nullable=False, server_default="[]",
        comment="The checks of the collection health check that the user turned off, by kind, such as creators",
    ))
    op.create_table(
        "health_dismissals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(), nullable=False, comment="The check that made the suggestion, such as creators"),
        sa.Column("subject", sa.String(), nullable=False, comment=(
            "What the suggestion is about, within its check, such as a creator's Site key and id: youtube:UC123"
        )),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True, comment=(
            "Until when it is put off, after which it shows again; null when dismissed for good"
        )),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "subject", name="uq_health_dismissal"),
    )


def downgrade() -> None:
    op.drop_table("health_dismissals")
    op.drop_index("ix_collections_site_creator_ref", table_name="collections")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("settings") as batch:
            batch.drop_column("health_checks_off")
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("site_creator_url")
            batch.drop_column("site_creator_ref")
    else:
        op.drop_column("settings", "health_checks_off")
        op.drop_column("collections", "site_creator_url")
        op.drop_column("collections", "site_creator_ref")
