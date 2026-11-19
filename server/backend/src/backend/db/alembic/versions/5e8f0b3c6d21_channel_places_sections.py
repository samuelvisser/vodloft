"""The channel alone places its sections.

A Daily Wire show is a section of its own kind, show, rather than a list with seasons. The channel's one setting for
new sections says season instead of main. A channel's own collection takes its lists from the channel: it no longer
waits for a choice about a playlist itself, as the channel asks about it instead, and the channel decides which of
its playlists are seasons, so the collection only has the ones it was given.

Revision ID: 5e8f0b3c6d21
Revises: c47d2a91e5b8
Create Date: 2026-11-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "5e8f0b3c6d21"
down_revision = "c47d2a91e5b8"
branch_labels = None
depends_on = None

_OWN_LISTS = "SELECT main_collection_id FROM channels WHERE main_collection_id IS NOT NULL"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE channel_sections SET kind = 'show' WHERE kind = 'list' AND has_seasons"))
    with op.batch_alter_table("channel_sections") as batch:
        batch.drop_column("has_seasons")
        batch.alter_column("kind", existing_type=sa.String(), existing_nullable=False, comment="feed, list, show or item")
    bind.execute(sa.text("UPDATE channels SET new_sections = 'season' WHERE new_sections = 'main'"))
    with op.batch_alter_table("channels") as batch:
        batch.alter_column(
            "new_sections", existing_type=sa.String(), existing_nullable=False, existing_server_default="ask",
            comment="What happens when the channel adds a section: ask, season, own or ignore",
        )
    # A playlist the channel's own collection was waiting on waits on the channel page instead.
    bind.execute(sa.text(
        "UPDATE channel_sections SET status = 'new' WHERE kind = 'list' AND EXISTS ("
        "SELECT 1 FROM collection_lists JOIN channels ON channels.main_collection_id = collection_lists.collection_id "
        "WHERE channels.id = channel_sections.channel_id AND collection_lists.ref = channel_sections.ref "
        "AND collection_lists.status = 'new')"
    ))
    bind.execute(sa.text(
        f"UPDATE collection_lists SET status = 'known', enabled = false WHERE status = 'new' AND collection_id IN ({_OWN_LISTS})"
    ))
    # Every playlist was a season: the ones it has stay seasons, and new ones are the channel's to place.
    bind.execute(sa.text(
        f"UPDATE collection_lists SET enabled = true WHERE collection_id IN "
        f"(SELECT id FROM collections WHERE link_seasons = 'all' AND id IN ({_OWN_LISTS}))"
    ))
    bind.execute(sa.text(f"UPDATE collections SET link_seasons = 'selected' WHERE link_seasons = 'all' AND id IN ({_OWN_LISTS})"))
    for action, follows in (("ask", "ask"), ("season", "add"), ("own", "ignore"), ("ignore", "ignore")):
        bind.execute(sa.text(
            "UPDATE collections SET new_link_seasons = :follows WHERE id IN "
            "(SELECT main_collection_id FROM channels WHERE new_sections = :action)"
        ), {"follows": follows, "action": action})


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("channel_sections") as batch:
        batch.add_column(sa.Column("has_seasons", sa.Boolean(), nullable=False, server_default="0"))
        batch.alter_column("kind", existing_type=sa.String(), existing_nullable=False, comment="feed, list or item")
    bind.execute(sa.text("UPDATE channel_sections SET kind = 'list', has_seasons = true WHERE kind = 'show'"))
    bind.execute(sa.text("UPDATE channels SET new_sections = 'main' WHERE new_sections = 'season'"))
    with op.batch_alter_table("channels") as batch:
        batch.alter_column(
            "new_sections", existing_type=sa.String(), existing_nullable=False, existing_server_default="ask",
            comment="What happens when the channel adds a section: ask, main, own or ignore",
        )
