"""Collections decide what they hold, and creators only group them.

A creator no longer places its feeds and lists in collections. Each collection reads its own link, takes the feeds and
lists its own settings say, and checks duplicates only among its own seasons; a creator only groups channel collections
in the Library. So the creator's sections, the collections that gathered several of them, and what the creator did
with new lists go:

- A creator's own collection of an account stays in the creator, with the feeds and lists it has. It already followed
  the creator's choices for new lists, so it keeps them as its own.
- A collection made from one of the creator's lists leaves the creator: it is a playlist or album collection of its
  own now.
- A collection made from one feed, such as a channel's Shorts, stays in the creator.
- Any other collection that gathered some of an account's feeds and lists leaves the creator, as a collection of its
  own link. Creators never shipped, so such a collection is test data, which the user removes by hand.

A list a creator had put among the videos in no list, rather than in a season of its own, is switched off, as only a
season can hold a list now.

A collection says whether its link is a channel or a list (set in the background, as only its Source can tell) and
what its channel season holds: an existing one keeps the videos in no list there. Each list knows the Source that
reads it, so a collection of links can have lists of any Site.

Creators shipped in no release, so when 0.10.0 ships with one migration from 0.9.0, most of this goes: a 0.9.0
database has no creators to convert.

Revision ID: 295b85b20467
Revises: 0b8b8a447385
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "295b85b20467"
down_revision = "0b8b8a447385"
branch_labels = None
depends_on = None

# The keys of the section types that are lists, on every Site that had creators: a playlist, or an album.
_LIST_TYPES = ("list", "album", "playlist")


def _drop_column(batch, table: str, column: str) -> None:
    """Drop a column with its foreign key and index, whatever they are named: a migrated database has the names its
    migrations gave them, and a new PostgreSQL database those of the models' naming convention."""
    inspector = sa.inspect(op.get_bind())
    for key in inspector.get_foreign_keys(table):
        if key["constrained_columns"] == [column] and key.get("name"):
            batch.drop_constraint(key["name"], type_="foreignkey")
    for index in inspector.get_indexes(table):
        if index["column_names"] == [column]:
            batch.drop_index(index["name"])
    batch.drop_column(column)


def _leave_creators() -> None:
    """Take the collections made from one list, and the ones that gathered an account's feeds and lists beside its
    own collection, out of their creator."""
    bind = op.get_bind()
    mains = {row[0] for row in bind.execute(sa.text(
        "SELECT main_collection_id FROM creator_accounts WHERE main_collection_id IS NOT NULL"
    ))}
    lists = {row[0] for row in bind.execute(sa.text(
        "SELECT s.url FROM creator_sections s WHERE s.type IN :types"
    ).bindparams(sa.bindparam("types", expanding=True)), {"types": list(_LIST_TYPES)})}
    for collection_id, url, account_id in bind.execute(sa.text(
        "SELECT id, sharing_url, creator_account_id FROM collections WHERE creator_id IS NOT NULL"
    )).all():
        if collection_id in mains:
            continue
        if account_id is not None or url in lists:
            bind.execute(sa.text("UPDATE collections SET creator_id = NULL WHERE id = :id"), {"id": collection_id})


def _drop_creator_work() -> None:
    """The daily look at each creator, the moves of a creator's feeds and lists and the removal of a feed or list the
    user took out of the Library are gone, with what they stored; a collection that finds a new list says so by an
    event of its own."""
    bind = op.get_bind()
    for task in ("follow_creators", "remove_skipped_collection"):
        bind.execute(sa.text("DELETE FROM task_operation_targets WHERE task_key = :task"), {"task": task})
        for table in ("task_runs", "task_schedules"):
            bind.execute(sa.text(
                f"DELETE FROM {table} WHERE definition_id IN (SELECT id FROM task_definitions WHERE key = :task)"
            ), {"task": task})
        bind.execute(sa.text("DELETE FROM task_definitions WHERE key = :task"), {"task": task})
    moves = "SELECT id FROM task_operations WHERE kind = 'creator.move_sections'"
    bind.execute(sa.text(f"DELETE FROM task_operation_dependencies WHERE parent_operation_id IN ({moves})"))
    bind.execute(sa.text(f"UPDATE task_operation_dependencies SET child_operation_id = NULL WHERE child_operation_id IN ({moves})"))
    bind.execute(sa.text(f"DELETE FROM task_operation_runs WHERE operation_id IN ({moves})"))
    bind.execute(sa.text(f"DELETE FROM task_operation_targets WHERE operation_id IN ({moves})"))
    bind.execute(sa.text("DELETE FROM task_operations WHERE kind = 'creator.move_sections'"))
    bind.execute(sa.text("DELETE FROM task_operation_targets WHERE resource_type = 'creator'"))
    bind.execute(sa.text(
        "DELETE FROM notification_events WHERE event = 'creator_sections_found' AND url LIKE '/edit-creator/%'"
    ))
    for table in ("notification_rules", "notification_events"):
        bind.execute(sa.text(f"UPDATE {table} SET event = 'new_lists_found' WHERE event = 'creator_sections_found'"))
    bind.execute(sa.text(
        "UPDATE notification_rules SET default_key = 'new_lists_found' WHERE default_key = 'creator_sections_found'"
    ))


def upgrade() -> None:
    _leave_creators()
    _drop_creator_work()
    op.drop_table("creator_section_items")
    op.drop_table("creator_sections")

    channel_season = sa.Column(
        "channel_season", sa.String(), nullable=False, server_default="unlisted",
        comment="What the channel season holds: everything, every video of the feeds, or unlisted, those in no list",
    )
    kind = sa.Column(
        "kind", sa.String(), nullable=False, server_default="channel",
        comment="What its own link is: channel, a creator's page of all their uploads, or list, one list or no link",
    )
    with op.batch_alter_table("collections") as batch:
        _drop_column(batch, "collections", "creator_account_id")
        batch.add_column(kind)
        batch.add_column(channel_season)
    with op.batch_alter_table("creator_accounts") as batch:
        _drop_column(batch, "creator_accounts", "main_collection_id")
        batch.drop_column("checked_at")
    with op.batch_alter_table("creators") as batch:
        batch.drop_column("new_lists")
        batch.drop_column("title_from_user")

    # A list whose videos joined the other seasons, as a creator placed it, is switched off: the videos of its channel's
    # feeds stay in the channel season.
    op.execute("UPDATE collection_lists SET enabled = false WHERE as_season = false")
    with op.batch_alter_table("collection_lists") as batch:
        batch.drop_column("as_season")
        batch.add_column(sa.Column(
            "source_key", sa.String(), nullable=True, comment="Id of the Source that reads the list, as registered in sources",
        ))
        batch.add_column(sa.Column("site_key", sa.String(), nullable=True, comment="The Site the list is on"))
        batch.create_foreign_key("fk_collection_lists_site_key_sites", "sites", ["site_key"], ["key"])
    op.execute(
        "UPDATE collection_lists SET source_key = (SELECT c.source_key FROM collections c WHERE c.id = collection_lists.collection_id), "
        "site_key = (SELECT c.site_key FROM collections c WHERE c.id = collection_lists.collection_id)"
    )
    with op.batch_alter_table("collection_lists") as batch:
        batch.alter_column("source_key", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("collection_lists") as batch:
        batch.drop_constraint("fk_collection_lists_site_key_sites", type_="foreignkey")
        batch.drop_column("site_key")
        batch.drop_column("source_key")
        batch.add_column(sa.Column(
            "as_season", sa.Boolean(), nullable=False, server_default="1",
            comment="Whether the list is a season of its own, or its videos join the collection's other seasons",
        ))
    with op.batch_alter_table("creators") as batch:
        batch.add_column(sa.Column(
            "new_lists", sa.JSON(), nullable=False, server_default="{}",
            comment="What happens when the creator adds a list, by Site and type of list: ask, season, own or ignore",
        ))
        batch.add_column(sa.Column(
            "title_from_user", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="The name was changed in VODLoft, so the Site's name no longer replaces it",
        ))
    with op.batch_alter_table("creator_accounts") as batch:
        batch.add_column(sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True, comment="When VODLoft last looked for new sections"))
        batch.add_column(sa.Column(
            "main_collection_id", sa.Integer(), nullable=True,
            comment="The collection named after the creator that takes this account's uploads",
        ))
        batch.create_foreign_key(
            "fk_creator_accounts_main_collection_id_collections", "collections", ["main_collection_id"], ["id"],
            ondelete="SET NULL", use_alter=True,
        )
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("channel_season")
        batch.drop_column("kind")
        batch.add_column(sa.Column("creator_account_id", sa.Integer(), nullable=True))
        batch.create_index("ix_collections_creator_account_id", ["creator_account_id"])
        batch.create_foreign_key(
            "fk_collections_creator_account_id", "creator_accounts", ["creator_account_id"], ["id"], ondelete="SET NULL",
        )
    # The creators' sections are not made again: the next daily look at each creator found them.
    op.create_table(
        "creator_sections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("creator_accounts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("access", sa.String(), nullable=True),
        sa.Column("site_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="known"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("account_id", "ref", name="uq_creator_section_ref"),
    )
    op.create_table(
        "creator_section_items",
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("creator_sections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_slug", sa.String(), primary_key=True),
    )
