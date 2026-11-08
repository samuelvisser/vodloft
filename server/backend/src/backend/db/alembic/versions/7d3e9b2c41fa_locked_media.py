"""Media items say which access they need, and when VODLoft checks whether locked media opened up.

``needs_subscription`` only knew one paid subscription per Source. It becomes ``access``, the key of
the Source's Access the media needs, such as NPO Plus, a Daily Wire membership level or a YouTube
channel membership. ``access_refused_at`` remembers that the Source refused a download for lack of
it, and ``access_check_at`` and ``access_checks`` plan the checks for media that opens up later.

Revision ID: 7d3e9b2c41fa
Revises: a0eceaa70db5
Create Date: 2026-11-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7d3e9b2c41fa"
down_revision = "a0eceaa70db5"
branch_labels = None
depends_on = None

# What needs_subscription meant on each Source that set it.
_ACCESS_BY_SOURCE = {"npo": "npo_plus", "dailywire": "INSIDER", "ytdlp": "members"}


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "access", sa.String(40), nullable=True,
            comment="Key of the Source's Access the media needs, such as NPO Plus or a channel membership",
        ))
        batch.add_column(sa.Column(
            "access_refused_at", sa.DateTime(), nullable=True,
            comment="When the Source last refused to give VODLoft the media for lack of its access",
        ))
        batch.add_column(sa.Column(
            "access_check_at", sa.DateTime(), nullable=True,
            comment="When VODLoft next checks whether locked media opened up",
        ))
        batch.add_column(sa.Column(
            "access_checks", sa.Integer(), nullable=False, server_default="0",
            comment="How often VODLoft checked whether the locked media opened up",
        ))
        batch.create_index("ix_media_items_access_check_at", ["access_check_at"])
    for source_key, access in _ACCESS_BY_SOURCE.items():
        op.execute(sa.text(
            "UPDATE media_items SET access = :access WHERE needs_subscription AND source_key = :source_key"
        ).bindparams(access=access, source_key=source_key))
    # A download the Source refused for lack of a subscription was kept from retrying by hand. The
    # media now stays locked by its access instead, so the download may come back once it opens up.
    op.execute(sa.text("""
        UPDATE media_downloads SET automatic_retry_suppressed = :suppressed
        WHERE automatic_retry_suppressed
          AND media_item_id IN (SELECT id FROM media_items WHERE needs_subscription)
          AND artifact_status = 'absent'
    """).bindparams(suppressed=False))
    # Elsewhere the Source refused a download: check soon whether the media opened up since.
    op.execute(
        "UPDATE media_items SET access_refused_at = CURRENT_TIMESTAMP, access_check_at = CURRENT_TIMESTAMP "
        "WHERE needs_subscription AND source_key <> 'npo'"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("needs_subscription")


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "needs_subscription", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="The Source only gives the media to a paying account, such as NPO Plus",
        ))
    op.execute("UPDATE media_items SET needs_subscription = (access IS NOT NULL)")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_index("ix_media_items_access_check_at")
        batch.drop_column("access_checks")
        batch.drop_column("access_check_at")
        batch.drop_column("access_refused_at")
        batch.drop_column("access")
