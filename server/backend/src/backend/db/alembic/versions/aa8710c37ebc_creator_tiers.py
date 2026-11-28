"""Tiers creators set up themselves on a Site, such as Patreon's, each with an id of VODLoft's own. Media that needs
one points to it.

Media that pointed to a Patreon pledge by its amount (keys starting with ``pledge-``) needs any patron's access
until VODLoft looks it up again.

Revision ID: aa8710c37ebc
Revises: 3106a907fdd4
Create Date: 2026-11-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "aa8710c37ebc"
down_revision = "3106a907fdd4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_tiers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("site_key", sa.String(), nullable=False, comment="The key of the Site the tier is on"),
        sa.Column("site_tier_id", sa.String(), nullable=False, comment="The Site's own id of the tier"),
        sa.Column("name", sa.String(), nullable=True, comment="What the creator calls the tier; None until VODLoft learns it"),
        sa.Column("amount", sa.String(), nullable=True, comment='What the tier costs, as people write it, such as "$5"'),
        sa.Column(
            "rank", sa.Integer(), nullable=True,
            comment="Where the tier stands among the creator's tiers, such as its price in cents: a tier gives what a lower one gives",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_creator_tiers"),
        sa.UniqueConstraint("site_key", "site_tier_id", name="uq_creator_tiers_site_key"),
        sqlite_autoincrement=True,
    )
    column = sa.Column(
        "creator_tier_id", sa.Integer(), nullable=True,
        comment="The creator's tier the media needs, when ``access`` is a tier creators on the Site set up themselves",
    )
    if op.get_bind().dialect.name == "sqlite":
        # SQLite adds a reference by rebuilding the table, which keeps its AUTOINCREMENT id.
        with op.batch_alter_table("media_items", recreate="always", table_kwargs={"sqlite_autoincrement": True}) as batch:
            batch.add_column(column)
            batch.create_foreign_key(
                "fk_media_items_creator_tier_id_creator_tiers", "creator_tiers", ["creator_tier_id"], ["id"], ondelete="SET NULL",
            )
    else:
        op.add_column("media_items", column)
        op.create_foreign_key(
            "fk_media_items_creator_tier_id_creator_tiers", "media_items", "creator_tiers", ["creator_tier_id"], ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_media_items_creator_tier_id", "media_items", ["creator_tier_id"])
    op.execute("UPDATE media_items SET access = 'members' WHERE access LIKE 'pledge-%'")


def downgrade() -> None:
    op.drop_index("ix_media_items_creator_tier_id", table_name="media_items")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("media_items", recreate="always", table_kwargs={"sqlite_autoincrement": True}) as batch:
            batch.drop_constraint("fk_media_items_creator_tier_id_creator_tiers", type_="foreignkey")
            batch.drop_column("creator_tier_id")
    else:
        op.drop_constraint("fk_media_items_creator_tier_id_creator_tiers", "media_items", type_="foreignkey")
        op.drop_column("media_items", "creator_tier_id")
    op.drop_table("creator_tiers")
