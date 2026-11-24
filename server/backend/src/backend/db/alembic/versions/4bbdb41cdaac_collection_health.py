"""Collections store their health: whether anything in them needs the user, and what.

Revision ID: 4bbdb41cdaac
Revises: 6ab9362820f3
Create Date: 2026-11-24

The count of downloads that wait to be moved becomes one kind of issue in a collection's health, which Home and the
Library read instead of working it out for every collection.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "4bbdb41cdaac"
down_revision = "6ab9362820f3"
branch_labels = None
depends_on = None

_collections = sa.table(
    "collections",
    sa.column("id", sa.Integer()),
    sa.column("moves_waiting", sa.Integer()),
    sa.column("healthy", sa.Boolean()),
    sa.column("health_issues", sa.JSON()),
)


def _drop_moves_waiting() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("moves_waiting")
    else:
        op.drop_column("collections", "moves_waiting")


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "healthy", sa.Boolean(), nullable=False, server_default=sa.true(),
        comment="Whether nothing in it needs the user, as its health_issues say",
    ))
    op.add_column("collections", sa.Column(
        "health_issues", sa.JSON(), nullable=False, server_default="{}",
        comment="What it needs the user for, by the kind of issue, with how many things each concerns, such as moves: 3 "
                "downloads that wait for its Move action. Kept up to date as VODLoft works on it, and set right by the "
                "nightly collection health check",
    ))
    op.create_index("ix_collections_healthy", "collections", ["healthy"])

    bind = op.get_bind()
    waiting = bind.execute(
        sa.select(_collections.c.id, _collections.c.moves_waiting).where(_collections.c.moves_waiting > 0)
    ).all()
    for collection_id, count in waiting:
        bind.execute(
            _collections.update().where(_collections.c.id == collection_id)
            .values(healthy=False, health_issues={"moves": count})
        )
    _drop_moves_waiting()


def downgrade() -> None:
    op.add_column("collections", sa.Column(
        "moves_waiting", sa.Integer(), nullable=False, server_default="0",
        comment="How many of its downloads its season settings put in another season, which wait for its Move action; "
                "kept up to date whenever its videos are placed, and checked every night",
    ))
    bind = op.get_bind()
    for collection_id, issues in bind.execute(
        sa.select(_collections.c.id, _collections.c.health_issues).where(_collections.c.healthy.is_(False))
    ).all():
        bind.execute(
            _collections.update().where(_collections.c.id == collection_id)
            .values(moves_waiting=int((issues or {}).get("moves", 0)))
        )
    op.drop_index("ix_collections_healthy", table_name="collections")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("health_issues")
            batch.drop_column("healthy")
    else:
        op.drop_column("collections", "health_issues")
        op.drop_column("collections", "healthy")
