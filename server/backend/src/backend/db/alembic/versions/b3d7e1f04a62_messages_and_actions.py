"""Messages and actions: destinations, rules, push devices, what was sent, and who added a Collection.

Existing installations get the default rules, which a new installation gets from the initial seed.

Revision ID: b3d7e1f04a62
Revises: e81f4c6a2b97
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b3d7e1f04a62"
down_revision = "e81f4c6a2b97"
branch_labels = None
depends_on = None

# The default rules as they were in this release: problems pushed to administrators, the daily summary off.
_DEFAULT_RULES = (
    ("download_failed", "download_failed", True, "now"),
    ("sign_in_needed", "sign_in_needed", True, "now"),
    ("disk_almost_full", "disk_almost_full", True, "now"),
    ("task_failing", "task_failing", True, "now"),
    ("update_available", "update_available", True, "now"),
    ("daily_summary", "everything", False, "daily"),
)


def upgrade() -> None:
    op.create_table(
        "notification_destinations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False, comment="apprise, jellyfin, emby, plex, webhook or script"),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("service", sa.String(64), nullable=False, comment="The Apprise service key, or the kind"),
        sa.Column("encrypted_config", sa.Text(), nullable=False, comment="The destination's settings as encrypted JSON"),
        sa.Column("masked", sa.String(255), nullable=False, comment="The destination, safe to show"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
            comment="Whose own rule this is; empty for a rule on Settings",
        ),
        sa.Column("personal", sa.Boolean(), nullable=False, comment="A person's own rule, from Account › Notifications"),
        sa.Column("default_key", sa.String(32), nullable=True, comment="Which default rule this is, if any"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("collection_scope", sa.String(16), nullable=False, comment="any, chosen or added (by this person)"),
        sa.Column("collection_ids", sa.JSON(), nullable=False),
        sa.Column("push", sa.Boolean(), nullable=False, comment="Push to administrators, or to the person of a personal rule"),
        sa.Column("destination_ids", sa.JSON(), nullable=False),
        sa.Column("delivery", sa.String(16), nullable=False, comment="now, grouped (per Collection) or daily"),
        sa.Column("summary_time", sa.String(5), nullable=False, comment="When a daily summary goes out"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_rules_user_id", "notification_rules", ["user_id"])
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
            comment="The person it is about, such as who asked for a Quick download",
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.String(512), nullable=True, comment="The page in VODLoft it is about"),
        sa.Column("data", sa.JSON(), nullable=False, comment="Details for actions, such as the file's folder"),
        sa.Column("dedupe_key", sa.String(255), nullable=True, comment="The same problem is sent again only after a day"),
    )
    op.create_index("ix_notification_events_event", "notification_events", ["event"])
    op.create_index("ix_notification_events_dedupe", "notification_events", ["dedupe_key", "occurred_at"])
    op.create_table(
        "push_vapid_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_private_key", sa.Text(), nullable=False),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
            comment="Whose device it is; empty when VODLoft has no user accounts",
        ),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_subscription", sa.Text(), nullable=False),
        sa.Column("device_name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("notification_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "destination_id", sa.Integer(), sa.ForeignKey("notification_destinations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "subscription_id", sa.Integer(), sa.ForeignKey("push_subscriptions.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
            comment="Who a push went to",
        ),
        sa.Column("group_key", sa.String(128), nullable=True, comment="Deliveries with the same key go out as one message"),
        sa.Column("status", sa.String(16), nullable=False, comment="PENDING, SENT, FAILED or CANCELED"),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_deliveries_event_id", "notification_deliveries", ["event_id"])
    op.create_index("ix_notification_deliveries_user_id", "notification_deliveries", ["user_id"])
    op.create_index("ix_notification_deliveries_pending", "notification_deliveries", ["status", "next_attempt_at"])

    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "added_by_id", sa.Integer(), nullable=True, comment="Who added the Collection, for their own notifications",
        ))
        batch.create_foreign_key("fk_collections_added_by_id_users", "users", ["added_by_id"], ["id"], ondelete="SET NULL")

    rules = sa.table(
        "notification_rules",
        sa.column("position", sa.Integer), sa.column("personal", sa.Boolean), sa.column("default_key", sa.String),
        sa.column("enabled", sa.Boolean), sa.column("event", sa.String), sa.column("collection_scope", sa.String),
        sa.column("collection_ids", sa.JSON), sa.column("push", sa.Boolean), sa.column("destination_ids", sa.JSON),
        sa.column("delivery", sa.String), sa.column("summary_time", sa.String),
    )
    op.bulk_insert(rules, [
        {
            "position": position, "personal": False, "default_key": key, "enabled": enabled, "event": event,
            "collection_scope": "any", "collection_ids": [], "push": True, "destination_ids": [], "delivery": delivery,
            "summary_time": "08:00",
        }
        for position, (key, event, enabled, delivery) in enumerate(_DEFAULT_RULES, start=1)
    ])


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_constraint("fk_collections_added_by_id_users", type_="foreignkey")
        batch.drop_column("added_by_id")
    op.drop_table("notification_deliveries")
    op.drop_table("push_subscriptions")
    op.drop_table("push_vapid_keys")
    op.drop_table("notification_events")
    op.drop_table("notification_rules")
    op.drop_table("notification_destinations")
