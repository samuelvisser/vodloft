"""Channels are creators.

What VODLoft added as a channel is a creator: who made the work, whatever each Site calls them, such as a host on The
Daily Wire or an artist on Bandcamp. The tables, their columns and the values VODLoft stored for channels take the
new name: the follow task, the resource type of its runs, the message about new sections and its page, the template
variables ``creator_title``, ``creator_handle`` and ``creator_kind``, and an import's choice to add creators.

Revision ID: 5fd4ae698d31
Revises: 8340278b15a0
Create Date: 2026-11-18
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "5fd4ae698d31"
down_revision = "8340278b15a0"
branch_labels = None
depends_on = None


_TEMPLATE_COLUMNS = (
    ("local_media_profiles", "output_template"),
    ("local_media_profiles_collection", "episode_title_template"),
    ("local_media_profiles_collection", "episode_description_template"),
)
_VARIABLES = ("title", "handle", "kind")
# Comments that name the creator, which only PostgreSQL keeps.
_COMMENTS = (
    ("collections", "link_seasons", sa.String(), "Whether the {}'s playlists are seasons: off, all or selected"),
    ("collections", "new_link_seasons", sa.String(),
     "What happens with a playlist the {} adds, when only selected playlists are seasons: ask, add or ignore"),
    ("collection_lists", "from_user", sa.Boolean(),
     "The user added the link, rather than it being one of the playlists of the collection's {}"),
)


def upgrade() -> None:
    _move("channel", "creator")


def downgrade() -> None:
    _move("creator", "channel")


def _move(old: str, new: str) -> None:
    bind = op.get_bind()
    olds, news = f"{old}s", f"{new}s"
    op.create_table(
        news,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False, comment=f"Id of the Source that looks the {new} up"),
        sa.Column("site_key", sa.String(), nullable=False),
        sa.Column("site_ref", sa.String(), nullable=False, comment=f"The Site's own id for the {new}"),
        sa.Column(
            "url", sa.String(), nullable=True,
            comment=f"The {new}'s page; empty when the Site has none, such as a Daily Wire host",
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True),
        sa.Column("banner_path", sa.String(), nullable=True),
        sa.Column("links", sa.JSON(), nullable=False, server_default="[]", comment=f"The {new}'s own links"),
        sa.Column("facts", sa.JSON(), nullable=False, server_default="[]", comment='Short facts, such as "1.2M subscribers"'),
        sa.Column("added_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "new_sections", sa.String(), nullable=False, server_default="ask",
            comment=f"What happens when the {new} adds a section: ask, season, own or ignore",
        ),
        sa.Column("genre", sa.String(), nullable=True, comment=f"Given to the {new}'s collections, for their NFO files"),
        sa.Column(
            "content_rating", sa.String(), nullable=True, comment=f"Given to the {new}'s collections, for their NFO files",
        ),
        sa.Column("main_collection_id", sa.Integer(), nullable=True, comment=f"The collection named after the {new}"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True, comment="When VODLoft last looked for new sections"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=f"pk_{news}"),
        sa.ForeignKeyConstraint(["site_key"], ["sites.key"], name=f"fk_{news}_site_key_sites"),
        sa.ForeignKeyConstraint(
            ["added_by_id"], ["users.id"], name=f"fk_{news}_added_by_id_users", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["main_collection_id"], ["collections.id"], name=f"fk_{news}_main_collection_id_collections",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("site_key", "site_ref", name=f"uq_{new}_site_ref"),
    )
    op.create_index(f"ix_{news}_uuid", news, ["uuid"], unique=True)
    op.create_index(f"ix_{news}_slug", news, ["slug"], unique=True)
    op.create_index(f"ix_{news}_site_key", news, ["site_key"])
    columns = (
        "id, uuid, slug, source_key, site_key, site_ref, url, title, handle, description, avatar_path, banner_path, links, "
        "facts, added_by_id, new_sections, genre, content_rating, main_collection_id, checked_at, created_at, updated_at"
    )
    bind.execute(sa.text(f"INSERT INTO {news} ({columns}) SELECT {columns} FROM {olds}"))

    op.create_table(
        f"{new}_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(f"{new}_id", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False, comment="The Site's own id for the section"),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, comment="feed, list, show or item"),
        sa.Column("role", sa.String(), nullable=False, server_default="main", comment="main, short or live"),
        sa.Column("kind_label", sa.String(), nullable=True, comment="What the Site calls it, such as Playlist"),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("access", sa.String(), nullable=True, comment="The key of the access the section needs"),
        sa.Column("site_position", sa.Integer(), nullable=False, server_default="0", comment="Where the Site lists it"),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="known",
            comment="known; new, found by the daily look and waiting for a choice; or ignored",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=f"pk_{new}_sections"),
        sa.ForeignKeyConstraint(
            [f"{new}_id"], [f"{news}.id"], name=f"fk_{new}_sections_{new}_id_{news}", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(f"{new}_id", "ref", name=f"uq_{new}_section_ref"),
    )
    op.create_index(f"ix_{new}_sections_{new}_id", f"{new}_sections", [f"{new}_id"])
    sections = (
        "ref, url, title, kind, role, kind_label, item_count, image_path, description, access, site_position, status, "
        "created_at"
    )
    bind.execute(sa.text(
        f"INSERT INTO {new}_sections (id, {new}_id, {sections}) SELECT id, {old}_id, {sections} FROM {old}_sections"
    ))
    if bind.dialect.name == "postgresql":
        # The copied ids are taken, so new rows start after them.
        for table in (news, f"{new}_sections"):
            bind.execute(sa.text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
            ))

    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(f"{new}_id", sa.Integer(), nullable=True, comment=f"The {new} it was added through"))
        batch.create_foreign_key(f"fk_collections_{new}_id_{news}", news, [f"{new}_id"], ["id"], ondelete="SET NULL")
        batch.create_index(f"ix_collections_{new}_id", [f"{new}_id"])
    bind.execute(sa.text(f"UPDATE collections SET {new}_id = {old}_id"))
    with op.batch_alter_table("collections") as batch:
        batch.drop_index(f"ix_collections_{old}_id")
        batch.drop_constraint(f"fk_collections_{old}_id_{olds}", type_="foreignkey")
        batch.drop_column(f"{old}_id")
    op.drop_table(f"{old}_sections")
    op.drop_table(olds)

    if bind.dialect.name == "postgresql":
        for table, column, type_, comment in _COMMENTS:
            op.alter_column(table, column, existing_type=type_, comment=comment.format(new))

    _rename_values(bind, old, new)


def _rename_values(bind, old: str, new: str) -> None:
    """The values VODLoft stored under the old name."""
    task, new_task = f"follow_{old}s", f"follow_{new}s"
    bind.execute(sa.text("UPDATE task_definitions SET key = :new WHERE key = :old"), {"old": task, "new": new_task})
    for definition_id, allowed in bind.execute(sa.text("SELECT id, allowed_resource_types FROM task_definitions")).all():
        types = json.loads(allowed) if isinstance(allowed, str) else allowed
        if types and old in types:
            bind.execute(
                sa.text("UPDATE task_definitions SET allowed_resource_types = :types WHERE id = :id"),
                {"types": json.dumps([new if item == old else item for item in types]), "id": definition_id},
            )
    # Runs and schedules keep the type's name; operations and their targets keep its value.
    for table in ("task_runs", "task_schedules"):
        bind.execute(
            sa.text(f"UPDATE {table} SET resource_type = :new WHERE resource_type = :old"),
            {"old": old.upper(), "new": new.upper()},
        )
    for table in ("task_operations", "task_operation_targets"):
        bind.execute(sa.text(f"UPDATE {table} SET resource_type = :new WHERE resource_type = :old"), {"old": old, "new": new})
    bind.execute(sa.text("UPDATE task_operations SET kind = :new WHERE kind = :old"), {"old": task, "new": new_task})
    bind.execute(
        sa.text(
            "UPDATE task_operation_targets SET task_key = :new, slot_key = REPLACE(REPLACE(slot_key, :old, :new), "
            ":old_type, :new_type) WHERE task_key = :old"
        ),
        {"old": task, "new": new_task, "old_type": f":{old}:", "new_type": f":{new}:"},
    )

    event, new_event = f"{old}_sections_found", f"{new}_sections_found"
    for table in ("notification_rules", "notification_events"):
        bind.execute(sa.text(f"UPDATE {table} SET event = :new WHERE event = :old"), {"old": event, "new": new_event})
    bind.execute(
        sa.text("UPDATE notification_rules SET default_key = :new WHERE default_key = :old"), {"old": event, "new": new_event},
    )
    for event_id, url, data in bind.execute(
        sa.text("SELECT id, url, data FROM notification_events WHERE event = :event"), {"event": new_event},
    ).all():
        details = json.loads(data) if isinstance(data, str) else dict(data or {})
        if old in details:
            details[new] = details.pop(old)
        if url and url.startswith(f"/{old}/"):
            url = f"/{new}/" + url[len(f"/{old}/"):]
        bind.execute(
            sa.text("UPDATE notification_events SET url = :url, data = :data WHERE id = :id"),
            {"url": url, "data": json.dumps(details), "id": event_id},
        )

    for table, column in _TEMPLATE_COLUMNS:
        for row_id, template in bind.execute(
            sa.text(f"SELECT id, {column} FROM {table} WHERE {column} LIKE :like"), {"like": f"%{old}_%"},
        ).all():
            changed = template
            for variable in _VARIABLES:
                changed = changed.replace(f"{old}_{variable}", f"{new}_{variable}")
            if changed != template:
                bind.execute(sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"), {"value": changed, "id": row_id})

    for run_id, options in bind.execute(sa.text("SELECT id, options FROM import_runs")).all():
        values = json.loads(options) if isinstance(options, str) else options
        if isinstance(values, dict) and f"as_{old}s" in values:
            values[f"as_{new}s"] = values.pop(f"as_{old}s")
            bind.execute(
                sa.text("UPDATE import_runs SET options = :options WHERE id = :id"), {"options": json.dumps(values), "id": run_id},
            )
