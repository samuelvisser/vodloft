"""A creator can have accounts on several Sites.

What tied a creator to one Site, such as their YouTube channel, moves to an account of theirs: the Site and its id
for them, their page and handle, the collection named after them that takes the account's uploads, and when VODLoft
last looked at it. Each section belongs to an account. Every creator gets one account, with what they had.

Revision ID: a3c81e6f0d52
Revises: 5fd4ae698d31
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a3c81e6f0d52"
down_revision = "5fd4ae698d31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "creator_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False, comment="Id of the Source that looks the account up"),
        sa.Column("site_key", sa.String(), nullable=False),
        sa.Column("site_ref", sa.String(), nullable=False, comment="The Site's own id for the account"),
        sa.Column(
            "url", sa.String(), nullable=True,
            comment="The account's page; empty when the Site has none, such as a Daily Wire host",
        ),
        sa.Column("handle", sa.String(), nullable=True),
        sa.Column(
            "main_collection_id", sa.Integer(), nullable=True,
            comment="The collection named after the creator that takes this account's uploads",
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True, comment="When VODLoft last looked for new sections"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_creator_accounts"),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], name="fk_creator_accounts_creator_id_creators", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["site_key"], ["sites.key"], name="fk_creator_accounts_site_key_sites"),
        sa.ForeignKeyConstraint(
            ["main_collection_id"], ["collections.id"], name="fk_creator_accounts_main_collection_id_collections",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("site_key", "site_ref", name="uq_creator_account_site_ref"),
    )
    op.create_index("ix_creator_accounts_creator_id", "creator_accounts", ["creator_id"])
    op.create_index("ix_creator_accounts_site_key", "creator_accounts", ["site_key"])
    # One account per creator, with the creator's id, so each section finds its account by the creator it had.
    bind.execute(sa.text(
        "INSERT INTO creator_accounts (id, creator_id, source_key, site_key, site_ref, url, handle, main_collection_id, "
        "checked_at, created_at) SELECT id, id, source_key, site_key, site_ref, url, handle, main_collection_id, "
        "checked_at, created_at FROM creators"
    ))
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('creator_accounts', 'id'), "
            "COALESCE((SELECT MAX(id) FROM creator_accounts), 0) + 1, false)"
        ))

    with op.batch_alter_table("creator_sections") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
    bind.execute(sa.text("UPDATE creator_sections SET account_id = creator_id"))
    with op.batch_alter_table("creator_sections") as batch:
        batch.alter_column("account_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("uq_creator_section_ref", type_="unique")
        batch.drop_index("ix_creator_sections_creator_id")
        batch.drop_constraint("fk_creator_sections_creator_id_creators", type_="foreignkey")
        batch.drop_column("creator_id")
        batch.create_foreign_key(
            "fk_creator_sections_account_id_creator_accounts", "creator_accounts", ["account_id"], ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_creator_sections_account_id", ["account_id"])
        batch.create_unique_constraint("uq_creator_section_ref", ["account_id", "ref"])

    with op.batch_alter_table("creators") as batch:
        batch.drop_constraint("uq_creator_site_ref", type_="unique")
        batch.drop_index("ix_creators_site_key")
        batch.drop_constraint("fk_creators_site_key_sites", type_="foreignkey")
        batch.drop_constraint("fk_creators_main_collection_id_collections", type_="foreignkey")
        for column in ("source_key", "site_key", "site_ref", "url", "handle", "main_collection_id", "checked_at"):
            batch.drop_column(column)


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("creators") as batch:
        batch.add_column(sa.Column("source_key", sa.String(), nullable=True, comment="Id of the Source that looks the creator up"))
        batch.add_column(sa.Column("site_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("site_ref", sa.String(), nullable=True, comment="The Site's own id for the creator"))
        batch.add_column(sa.Column(
            "url", sa.String(), nullable=True,
            comment="The creator's page; empty when the Site has none, such as a Daily Wire host",
        ))
        batch.add_column(sa.Column("handle", sa.String(), nullable=True))
        batch.add_column(sa.Column("main_collection_id", sa.Integer(), nullable=True, comment="The collection named after the creator"))
        batch.add_column(sa.Column(
            "checked_at", sa.DateTime(timezone=True), nullable=True, comment="When VODLoft last looked for new sections",
        ))
    # A creator with accounts on several Sites becomes one creator for each further account.
    first = {
        creator_id: account_id for creator_id, account_id in bind.execute(sa.text(
            "SELECT creator_id, MIN(id) FROM creator_accounts GROUP BY creator_id"
        )).all()
    }
    accounts = bind.execute(sa.text(
        "SELECT a.id, a.creator_id, a.source_key, a.site_key, a.site_ref, a.url, a.handle, a.main_collection_id, "
        "a.checked_at, c.slug FROM creator_accounts a JOIN creators c ON c.id = a.creator_id ORDER BY a.id"
    )).all()
    owner: dict[int, int] = {}
    for account in accounts:
        values = {
            "source_key": account.source_key, "site_key": account.site_key, "site_ref": account.site_ref,
            "url": account.url, "handle": account.handle, "main_collection_id": account.main_collection_id,
            "checked_at": account.checked_at,
        }
        if first[account.creator_id] == account.id:
            bind.execute(sa.text(
                "UPDATE creators SET source_key = :source_key, site_key = :site_key, site_ref = :site_ref, url = :url, "
                "handle = :handle, main_collection_id = :main_collection_id, checked_at = :checked_at WHERE id = :id"
            ), {**values, "id": account.creator_id})
            owner[account.id] = account.creator_id
            continue
        bind.execute(sa.text(
            "INSERT INTO creators (uuid, slug, title, description, avatar_path, banner_path, links, facts, added_by_id, "
            "new_sections, genre, content_rating, created_at, updated_at, source_key, site_key, site_ref, url, handle, "
            "main_collection_id, checked_at) SELECT :uuid, :slug, title, description, avatar_path, banner_path, links, "
            "facts, added_by_id, new_sections, genre, content_rating, created_at, updated_at, :source_key, :site_key, "
            ":site_ref, :url, :handle, :main_collection_id, :checked_at FROM creators WHERE id = :id"
        ), {**values, "id": account.creator_id, "uuid": f"account-{account.id}", "slug": f"{account.slug}-{account.id}"})
        new_id = bind.execute(sa.text("SELECT id FROM creators WHERE uuid = :uuid"), {"uuid": f"account-{account.id}"}).scalar_one()
        owner[account.id] = new_id
        if account.main_collection_id is not None:
            bind.execute(
                sa.text("UPDATE collections SET creator_id = :new WHERE id = :collection"),
                {"new": new_id, "collection": account.main_collection_id},
            )
    with op.batch_alter_table("creators") as batch:
        for column in ("source_key", "site_key", "site_ref"):
            batch.alter_column(column, existing_type=sa.String(), nullable=False)
        batch.create_foreign_key("fk_creators_site_key_sites", "sites", ["site_key"], ["key"])
        batch.create_foreign_key(
            "fk_creators_main_collection_id_collections", "collections", ["main_collection_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_creators_site_key", ["site_key"])
        batch.create_unique_constraint("uq_creator_site_ref", ["site_key", "site_ref"])

    with op.batch_alter_table("creator_sections") as batch:
        batch.add_column(sa.Column("creator_id", sa.Integer(), nullable=True))
    for account_id, creator_id in owner.items():
        bind.execute(
            sa.text("UPDATE creator_sections SET creator_id = :creator WHERE account_id = :account"),
            {"creator": creator_id, "account": account_id},
        )
    with op.batch_alter_table("creator_sections") as batch:
        batch.alter_column("creator_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("uq_creator_section_ref", type_="unique")
        batch.drop_index("ix_creator_sections_account_id")
        batch.drop_constraint("fk_creator_sections_account_id_creator_accounts", type_="foreignkey")
        batch.drop_column("account_id")
        batch.create_foreign_key(
            "fk_creator_sections_creator_id_creators", "creators", ["creator_id"], ["id"], ondelete="CASCADE",
        )
        batch.create_index("ix_creator_sections_creator_id", ["creator_id"])
        batch.create_unique_constraint("uq_creator_section_ref", ["creator_id", "ref"])
    op.drop_index("ix_creator_accounts_site_key", "creator_accounts")
    op.drop_index("ix_creator_accounts_creator_id", "creator_accounts")
    op.drop_table("creator_accounts")
