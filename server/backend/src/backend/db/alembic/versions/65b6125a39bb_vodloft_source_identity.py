"""Store each episode's slug at its Source in a column, and name every item's Source.

Episodes of a show whose Source lists them kept the Source's own slug in the
"source.slug" metadata key, because their VODLoft slug gets a prefix when
another show's episode already has it. The slug now has its own column, unique
within the show. Every other episode's slug at its Source is its slug.

Shows and media items no longer fall back to The Daily Wire when their Source
is left out.

Revision ID: 65b6125a39bb
Revises: a23bae59a781
Create Date: 2026-10-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "65b6125a39bb"
down_revision = "a23bae59a781"
branch_labels = None
depends_on = None


_SOURCE_SLUG_META_KEY = "source.slug"
_EPISODE_META_TABLE = "media_items_episode"
_SOURCE_SLUG_UNIQUE = "uq_episode_show_source_slug"
_DAILYWIRE = "dailywire"


def _source_key_default(server_default: str | None) -> None:
    for table in ("shows", "media_items"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "source_key",
                existing_type=sa.String(),
                existing_nullable=False,
                server_default=server_default,
            )


def upgrade() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "source_slug",
            sa.String(),
            nullable=True,
            comment="The episode's own slug at its Source. It is the slug, unless another show's episode already had that",
        ))
    op.execute(sa.text(
        "UPDATE media_items_episode SET source_slug = COALESCE("
        "(SELECT value FROM metadata WHERE metadata.parent_table = :parent_table "
        "AND metadata.parent_id = media_items_episode.id AND metadata.key = :key), slug)"
    ).bindparams(parent_table=_EPISODE_META_TABLE, key=_SOURCE_SLUG_META_KEY))
    op.execute(sa.text(
        "DELETE FROM metadata WHERE parent_table = :parent_table AND key = :key"
    ).bindparams(parent_table=_EPISODE_META_TABLE, key=_SOURCE_SLUG_META_KEY))
    with op.batch_alter_table("media_items_episode") as batch:
        batch.alter_column("source_slug", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint(_SOURCE_SLUG_UNIQUE, ["show_id", "source_slug"])
    _source_key_default(None)


def downgrade() -> None:
    _source_key_default(_DAILYWIRE)
    op.execute(sa.text(
        "INSERT INTO metadata (parent_table, parent_id, key, value) "
        "SELECT :parent_table, id, :key, source_slug FROM media_items_episode WHERE source_slug != slug"
    ).bindparams(parent_table=_EPISODE_META_TABLE, key=_SOURCE_SLUG_META_KEY))
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_constraint(_SOURCE_SLUG_UNIQUE, type_="unique")
        batch.drop_column("source_slug")
