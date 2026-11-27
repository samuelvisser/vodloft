"""Attention states, and a severity on every event.

Revision ID: bcec37451c0d
Revises: c41e7d09b2a8
Create Date: 2026-11-27

What is true until someone fixes it, such as a destination that keeps failing, becomes a stored state that Home
shows. Every event records the severity of its kind, and installations get the default rule that pushes failing
destinations to administrators, which until now went out as "a task keeps failing".
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bcec37451c0d"
down_revision = "c41e7d09b2a8"
branch_labels = None
depends_on = None

_SEVERITIES = {
    "download_failed": "problem",
    "sign_in_needed": "problem",
    "task_failing": "problem",
    "disk_almost_full": "problem",
    "new_lists_found": "needs_you",
}
"""The severity of each kind that was stored before this migration; every other kind is news."""

_events = sa.table("notification_events", sa.column("event", sa.String()), sa.column("severity", sa.String()))
_rules = sa.table(
    "notification_rules",
    sa.column("id", sa.Integer()), sa.column("position", sa.Integer()), sa.column("user_id", sa.Integer()),
    sa.column("personal", sa.Boolean()), sa.column("default_key", sa.String()), sa.column("enabled", sa.Boolean()),
    sa.column("event", sa.String()), sa.column("collection_scope", sa.String()), sa.column("collection_ids", sa.JSON()),
    sa.column("push", sa.Boolean()), sa.column("destination_ids", sa.JSON()), sa.column("delivery", sa.String()),
    sa.column("summary_time", sa.String()),
)


def upgrade() -> None:
    op.create_table(
        "attention_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=32), nullable=False, comment="Its kind in the happenings registry"),
        sa.Column(
            "subject_key", sa.String(length=128), nullable=False,
            comment="What it is about, such as destination:4 or task:collection_health",
        ),
        sa.Column(
            "collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=True,
            comment="The collection it is about, if any",
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=True, comment="Where in VODLoft to fix it"),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("put_off_until", sa.DateTime(timezone=True), nullable=True, comment="Hidden from Home until then"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_attention_states_collection_id", "attention_states", ["collection_id"])
    op.create_index("ix_attention_states_resolved_at", "attention_states", ["resolved_at"])
    op.create_index(
        "uq_attention_states_open", "attention_states", ["kind", "subject_key"], unique=True,
        sqlite_where=sa.text("resolved_at IS NULL"), postgresql_where=sa.text("resolved_at IS NULL"),
    )

    op.add_column("notification_events", sa.Column(
        "severity", sa.String(length=16), nullable=True,
        comment="problem, needs_you or news: its kind's severity when it happened",
    ))
    bind = op.get_bind()
    bind.execute(_events.update().values(severity="news"))
    for event, severity in _SEVERITIES.items():
        bind.execute(_events.update().where(_events.c.event == event).values(severity=severity))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("notification_events", table_kwargs={"sqlite_autoincrement": True}) as batch:
            batch.alter_column("severity", existing_type=sa.String(length=16), nullable=False)
    else:
        op.alter_column("notification_events", "severity", existing_type=sa.String(length=16), nullable=False)

    # An installation that has its default rules gets the new one; a fresh one gets it from the initial seed.
    shared = _rules.c.personal.is_(False)
    has_defaults = bind.scalar(sa.select(sa.func.count()).select_from(_rules).where(
        shared, _rules.c.default_key.is_not(None),
    ))
    has_rule = bind.scalar(sa.select(sa.func.count()).select_from(_rules).where(
        shared, _rules.c.default_key == "destination_failing",
    ))
    if has_defaults and not has_rule:
        position = bind.scalar(sa.select(sa.func.max(_rules.c.position)).where(shared)) or 0
        bind.execute(_rules.insert().values(
            position=position + 1, user_id=None, personal=False, default_key="destination_failing", enabled=True,
            event="destination_failing", collection_scope="any", collection_ids=[], push=True, destination_ids=[],
            delivery="now", summary_time="08:00",
        ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(_rules.delete().where(_rules.c.event == "destination_failing"))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("notification_events", table_kwargs={"sqlite_autoincrement": True}) as batch:
            batch.drop_column("severity")
    else:
        op.drop_column("notification_events", "severity")
    op.drop_index("uq_attention_states_open", table_name="attention_states")
    op.drop_index("ix_attention_states_resolved_at", table_name="attention_states")
    op.drop_index("ix_attention_states_collection_id", table_name="attention_states")
    op.drop_table("attention_states")
