"""Each of a creator's accounts keeps its own picture, and the own collections of a creator on several Sites are named
after their Site.

Revision ID: 148e116c354b
Revises: 6007aa686523
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "148e116c354b"
down_revision = "6007aa686523"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creator_accounts",
        sa.Column("avatar_path", sa.String(), nullable=True, comment="The account's own picture on its Site"),
    )
    # The creator's picture is that of their first account; the others get theirs on the next daily look.
    op.execute(
        "UPDATE creator_accounts SET avatar_path = "
        "(SELECT creators.avatar_path FROM creators WHERE creators.id = creator_accounts.creator_id) "
        "WHERE id IN (SELECT MIN(earliest.id) FROM creator_accounts earliest GROUP BY earliest.creator_id)"
    )
    # On a creator with several accounts, each account's own collection still named after the creator alone takes its
    # Site's name after it, such as "for KING + COUNTRY YouTube".
    op.execute(
        "UPDATE collections SET title = title || ' ' || ("
        "SELECT MIN(sites.name) FROM creator_accounts account JOIN sites ON sites.key = account.site_key "
        "WHERE account.main_collection_id = collections.id) "
        "WHERE id IN ("
        "SELECT account.main_collection_id FROM creator_accounts account "
        "JOIN creators ON creators.id = account.creator_id "
        "WHERE account.main_collection_id IS NOT NULL AND collections.title = creators.title "
        "AND (SELECT COUNT(*) FROM creator_accounts other WHERE other.creator_id = account.creator_id) > 1)"
    )


def downgrade() -> None:
    with op.batch_alter_table("creator_accounts") as batch:
        batch.drop_column("avatar_path")
