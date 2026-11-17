"""Following channels: what happens when a channel adds a section, the genre and rating its collections get, and
sections the daily look found.

Revision ID: 4737d5b6dd34
Revises: 22986fb7a6b8
Create Date: 2026-11-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "4737d5b6dd34"
down_revision = "22986fb7a6b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch:
        batch.add_column(sa.Column(
            "new_sections", sa.String(), nullable=False, server_default="ask",
            comment="What happens when the channel adds a section: ask, main, own or ignore",
        ))
        batch.add_column(sa.Column("genre", sa.String(), nullable=True, comment="Given to the channel's collections, for their NFO files"))
        batch.add_column(sa.Column(
            "content_rating", sa.String(), nullable=True, comment="Given to the channel's collections, for their NFO files",
        ))
        batch.add_column(sa.Column(
            "main_collection_id", sa.Integer(), nullable=True, comment="The collection named after the channel",
        ))
        batch.create_foreign_key(
            "fk_channels_main_collection_id_collections", "collections", ["main_collection_id"], ["id"], ondelete="SET NULL",
        )
        batch.add_column(sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True, comment="When VODLoft last looked for new sections"))
    # Existing channels: the collection that has a link to the channel's Videos, or one named after the channel.
    op.execute(sa.text(
        "UPDATE channels SET main_collection_id = (SELECT collections.id FROM collections"
        " WHERE collections.channel_id = channels.id AND collections.title = channels.title ORDER BY collections.id LIMIT 1)"
    ))
    with op.batch_alter_table("channel_sections") as batch:
        batch.add_column(sa.Column(
            "status", sa.String(), nullable=False, server_default="known",
            comment="known; new, found by the daily look and waiting for a choice; or ignored",
        ))


    # Installations that have their rules already get the new default one: a channel's new sections, pushed to
    # administrators. A new database gets it with the other defaults from the initial seed.
    bind = op.get_bind()
    present = bind.execute(sa.text("SELECT default_key FROM notification_rules WHERE personal = :personal"), {"personal": False}).scalars().all()
    if present and "channel_sections_found" not in present:
        position = bind.execute(sa.text("SELECT MAX(position) FROM notification_rules WHERE personal = :personal"), {"personal": False}).scalar()
        rules = sa.table(
            "notification_rules",
            sa.column("position", sa.Integer), sa.column("personal", sa.Boolean), sa.column("default_key", sa.String),
            sa.column("enabled", sa.Boolean), sa.column("event", sa.String), sa.column("collection_scope", sa.String),
            sa.column("collection_ids", sa.JSON), sa.column("push", sa.Boolean), sa.column("destination_ids", sa.JSON),
            sa.column("delivery", sa.String), sa.column("summary_time", sa.String),
        )
        op.bulk_insert(rules, [{
            "position": (position or 0) + 1, "personal": False, "default_key": "channel_sections_found", "enabled": True,
            "event": "channel_sections_found", "collection_scope": "any", "collection_ids": [], "push": True,
            "destination_ids": [], "delivery": "now", "summary_time": "08:00",
        }])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM notification_rules WHERE default_key = 'channel_sections_found'"))
    with op.batch_alter_table("channel_sections") as batch:
        batch.drop_column("status")
    with op.batch_alter_table("channels") as batch:
        batch.drop_column("checked_at")
        batch.drop_constraint("fk_channels_main_collection_id_collections", type_="foreignkey")
        batch.drop_column("main_collection_id")
        batch.drop_column("content_rating")
        batch.drop_column("genre")
        batch.drop_column("new_sections")
