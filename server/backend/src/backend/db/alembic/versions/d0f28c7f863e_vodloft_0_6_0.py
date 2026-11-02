"""Upgrade the VODLoft 0.5.0 schema to 0.6.0.

Revision ID: d0f28c7f863e
Revises: 817515eb8209
Create Date: 2026-11-01

The single release migration for 0.6.0. Shows become Collections: the tables,
columns, constraints and indexes are renamed, and every stored value that
named a show (profile type, metadata owner, task keys, operation kinds,
resource types, task arguments and output template variables) is rewritten to
its Collection name.

Episodes also store who uploaded them, for the episode_uploader template value,
and existing_file_scans keeps the files found on disk for a Collection.
"""
from __future__ import annotations

import json
import re

from alembic import op
from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError
import sqlalchemy as sa


revision = "d0f28c7f863e"
down_revision = "817515eb8209"
branch_labels = None
depends_on = None


# Shows become Collections ----------------------------------------------------

_TABLES = (
    ("shows", "collections"),
    ("show_local_assets", "collection_local_assets"),
    ("local_media_profiles_show", "local_media_profiles_collection"),
)

# (table, old index, new index, columns, unique) -- dropped before and created
# after the table and column renames.
_INDEXES = (
    ("shows", "collections", "ix_shows_slug", "ix_collections_slug", ["slug"], True),
    ("shows", "collections", "ix_shows_uuid", "ix_collections_uuid", ["uuid"], True),
    ("shows", "collections", "ix_shows_source_key", "ix_collections_source_key", ["source_key"], False),
    ("show_local_assets", "collection_local_assets", "ix_show_local_assets_show_id",
     "ix_collection_local_assets_collection_id", ["collection_id"], False),
    ("show_local_assets", "collection_local_assets", "ix_show_local_assets_local_media_profile_id",
     "ix_collection_local_assets_local_media_profile_id", ["local_media_profile_id"], False),
    ("custom_index_states", "custom_index_states", "ix_custom_index_states_show_id",
     "ix_custom_index_states_collection_id", ["collection_id"], False),
    ("media_items_episode", "media_items_episode", "ix_media_items_episode_show_publish_status",
     "ix_media_items_episode_collection_publish_status", ["collection_id", "publish_status"], False),
    ("media_items_episode", "media_items_episode", "ix_media_items_episode_show_published_id",
     "ix_media_items_episode_collection_published_id", ["collection_id", "published_date", "id"], False),
)

# table -> (column renames, unique constraint renames, foreign key renames)
# Unique constraints: (old name, new name, new columns)
# Foreign keys: (old name, new name, column, referred table, ondelete)
_TABLE_CHANGES = {
    "collections": (
        (),
        (("uq_shows_sharing_url", "uq_collections_sharing_url", ["sharing_url"]),),
        (("fk_shows_created_by_user_id_users", "fk_collections_created_by_user_id_users",
          "created_by_user_id", "users", "SET NULL"),),
    ),
    "collection_local_assets": (
        (("show_id", "collection_id"),),
        (("uq_show_local_asset_target", "uq_collection_local_asset_target",
          ["collection_id", "local_media_profile_id", "asset_type", "file_path"]),),
        (("fk_show_local_assets_show_id_shows", "fk_collection_local_assets_collection_id_collections",
          "collection_id", "collections", "CASCADE"),
         ("fk_show_local_assets_local_media_profile_id_local_media_profiles",
          "fk_collection_local_assets_local_media_profile_id_local_media_profiles",
          "local_media_profile_id", "local_media_profiles", "CASCADE")),
    ),
    "local_media_profiles_collection": (
        (("show_scope", "collection_scope"), ("download_show_assets", "download_collection_assets")),
        (),
        (("fk_local_media_profiles_show_id_local_media_profiles",
          "fk_local_media_profiles_collection_id_local_media_profiles", "id", "local_media_profiles", "CASCADE"),),
    ),
    "custom_index_states": (
        (("show_id", "collection_id"),),
        (("uq_custom_index_state_scope", "uq_custom_index_state_scope", ["collection_id", "local_media_profile_id"]),),
        (("fk_custom_index_states_show_id_shows", "fk_custom_index_states_collection_id_collections",
          "collection_id", "collections", "CASCADE"),),
    ),
    "download_profiles": (
        (("show_id", "collection_id"),),
        (),
        (("fk_download_profiles_show_id_shows", "fk_download_profiles_collection_id_collections",
          "collection_id", "collections", None),),
    ),
    "stream_profiles": (
        (("show_id", "collection_id"), ("overwrite_show_title", "overwrite_collection_title")),
        (),
        (("fk_stream_profiles_show_id_shows", "fk_stream_profiles_collection_id_collections",
          "collection_id", "collections", None),),
    ),
    "seasons": (
        (("show_id", "collection_id"),),
        (("uq_season_show_index", "uq_season_collection_index", ["collection_id", "index"]),
         ("uq_season_show_slug", "uq_season_collection_slug", ["collection_id", "slug"])),
        (("fk_seasons_show_id_shows", "fk_seasons_collection_id_collections", "collection_id", "collections", None),),
    ),
    "media_items_episode": (
        (("show_id", "collection_id"),),
        (("uq_episode_show_index", "uq_episode_collection_index", ["collection_id", "index"]),
         ("uq_unique_episode_identifier_per_show", "uq_unique_episode_identifier_per_collection",
          ["collection_id", "episode_identifier"]),
         ("uq_episode_show_source_slug", "uq_episode_collection_source_slug", ["collection_id", "source_slug"])),
        (("fk_episodes_show_id_shows", "fk_media_items_episode_collection_id_collections",
          "collection_id", "collections", None),),
    ),
}

_PRIMARY_KEYS = (
    ("collections", "pk_shows", "pk_collections"),
    ("collection_local_assets", "pk_show_local_assets", "pk_collection_local_assets"),
    ("local_media_profiles_collection", "pk_local_media_profiles_show", "pk_local_media_profiles_collection"),
)

_TASK_KEYS = (
    ("rename_show_profile_files", "rename_collection_profile_files"),
    ("rescan_quick_checked_shows", "rescan_quick_checked_collections"),
    ("delete_show_downloads_worker", "delete_collection_downloads_worker"),
    ("reconcile_show_assets", "reconcile_collection_assets"),
)

_OPERATION_KINDS = (
    "index", "sync", "download_all", "refresh_metadata", "rename_files", "delete_downloads", "redownload_episodes",
)

_DEFAULT_PROFILES = (
    ("vodloft-shows-video", "vodloft-collections-video", "VODLoft Shows (Video)", "VODLoft Collections (Video)"),
    ("vodloft-shows-audio", "vodloft-collections-audio", "VODLoft Shows (Audio)", "VODLoft Collections (Audio)"),
)

# Output template variables that named the show.
_TEMPLATE_NAMES = {"show": "collection", "show_title": "collection_title"}
_TEMPLATE_PREFIXES = (("meta_show_", "meta_collection_"),)

# JSON keys in task arguments, results and contexts: a "show" or "shows" part
# of a snake_case key, such as show_id or shows_scanned.
_JSON_KEY_PART = re.compile(r"(?<![a-z])show(s?)(?![a-z])")
_TASK_JSON_COLUMNS = (
    ("task_runs", "meta"),
    ("task_runs", "result"),
    ("task_schedules", "trigger_args"),
    ("task_operations", "result"),
    ("task_operations", "context"),
    ("task_operation_targets", "task_kwargs"),
    ("task_operation_dependencies", "context"),
    ("media_download_history", "metadata"),
)


def _renamed_key(key: str, *, reverse: bool) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", key) or "no_show" in key:
        return key
    if reverse:
        return re.sub(r"(?<![a-z])collection(s?)(?![a-z])", lambda match: "show" + match.group(1), key)
    return _JSON_KEY_PART.sub(lambda match: "collection" + match.group(1), key)


def _renamed_json(value, *, reverse: bool):
    old, new = ("collection", "show") if reverse else ("show", "collection")
    if isinstance(value, dict):
        renamed = {}
        for key, item in value.items():
            new_key = _renamed_key(key, reverse=reverse) if isinstance(key, str) else key
            item = _renamed_json(item, reverse=reverse)
            if new_key in {"resource_type", "resourceType"} and item == old:
                item = new
            renamed[new_key] = item
        return renamed
    if isinstance(value, list):
        return [_renamed_json(item, reverse=reverse) for item in value]
    return value


def _rename_template_variables(source: str, *, reverse: bool) -> str:
    """Rename the show variables in one output template, leaving all other text as it is."""
    names = {new: old for old, new in _TEMPLATE_NAMES.items()} if reverse else _TEMPLATE_NAMES
    prefixes = tuple((new, old) for old, new in _TEMPLATE_PREFIXES) if reverse else _TEMPLATE_PREFIXES
    environment = Environment()
    try:
        tokens = list(environment.lex(source))
    except TemplateSyntaxError:
        return source
    if "".join(value for _, _, value in tokens) != source:
        return source
    parts = []
    for _, kind, value in tokens:
        if kind == "name":
            if value in names:
                value = names[value]
            else:
                for old, new in prefixes:
                    if value.startswith(old):
                        value = new + value[len(old):]
        parts.append(value)
    return "".join(parts)


def _rename_schema(*, reverse: bool) -> None:
    def pick(old, new):
        return (new, old) if reverse else (old, new)

    for old_table, new_table, old, new, _columns, _unique in _INDEXES:
        current_table = new_table if reverse else old_table
        op.drop_index(pick(old, new)[0], table_name=current_table)
    for old, new in _TABLES:
        op.rename_table(*pick(old, new))
    for table, (columns, uniques, foreign_keys) in _TABLE_CHANGES.items():
        if reverse:
            table = next((old for old, new in _TABLES if new == table), table)
        renamed_columns = dict(pick(old, new) for old, new in columns)
        with op.batch_alter_table(table, recreate="always") as batch:
            for current, wanted in renamed_columns.items():
                batch.alter_column(current, new_column_name=wanted)
            for old_name, new_name, _columns in uniques:
                batch.drop_constraint(pick(old_name, new_name)[0], type_="unique")
            for old_name, new_name, *_rest in foreign_keys:
                batch.drop_constraint(pick(old_name, new_name)[0], type_="foreignkey")
        old_columns = {new: old for old, new in columns}
        with op.batch_alter_table(table, recreate="always") as batch:
            for old_name, new_name, new_columns in uniques:
                wanted_columns = [old_columns.get(column, column) for column in new_columns] if reverse else new_columns
                batch.create_unique_constraint(pick(old_name, new_name)[1], wanted_columns)
            for old_name, new_name, column, referred, ondelete in foreign_keys:
                if reverse:
                    column = old_columns.get(column, column)
                    referred = next((old for old, new in _TABLES if new == referred), referred)
                batch.create_foreign_key(pick(old_name, new_name)[1], referred, [column], ["id"], ondelete=ondelete)
    for table, old, new in _PRIMARY_KEYS:
        if reverse:
            table = next((old_table for old_table, new_table in _TABLES if new_table == table), table)
        current, wanted = pick(old, new)
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(current, type_="primary")
            batch.create_primary_key(wanted, ["id"])
    current_default, wanted_default = pick("show", "collection")
    with op.batch_alter_table("local_media_profiles", recreate="always") as batch:
        batch.alter_column(
            "type", existing_type=sa.String(), existing_nullable=False,
            server_default=wanted_default, existing_server_default=current_default,
        )
    for old_table, new_table, old, new, columns, unique in _INDEXES:
        if reverse:
            old_columns = {new_column: old_column for change in _TABLE_CHANGES.values() for old_column, new_column in change[0]}
            columns = [old_columns.get(column, column) for column in columns]
        op.create_index(pick(old, new)[1], old_table if reverse else new_table, columns, unique=unique)


def _rename_values(*, reverse: bool) -> None:
    def pick(old, new):
        return (new, old) if reverse else (old, new)

    connection = op.get_bind()

    def update(statement: str, old, new) -> None:
        current, wanted = pick(old, new)
        connection.execute(sa.text(statement).bindparams(current=current, wanted=wanted))

    update("UPDATE local_media_profiles SET type = :wanted WHERE type = :current", "show", "collection")
    for old, new in _TABLES:
        update("UPDATE metadata SET parent_table = :wanted WHERE parent_table = :current", old, new)

    for old_slug, new_slug, old_name, new_name in _DEFAULT_PROFILES:
        for column, old, new in (("slug", old_slug, new_slug), ("name", old_name, new_name)):
            current, wanted = pick(old, new)
            taken = connection.execute(sa.text(
                f"SELECT 1 FROM local_media_profiles WHERE {column} = :wanted"
            ).bindparams(wanted=wanted)).first()
            if taken is None:
                update(f"UPDATE local_media_profiles SET {column} = :wanted WHERE {column} = :current", old, new)

    rows = connection.execute(sa.text("SELECT id, output_template FROM local_media_profiles")).all()
    for profile_id, template in rows:
        renamed = _rename_template_variables(template, reverse=reverse)
        if renamed != template:
            connection.execute(sa.text(
                "UPDATE local_media_profiles SET output_template = :template WHERE id = :id"
            ).bindparams(template=renamed, id=profile_id))

    for old, new in _TASK_KEYS:
        update("UPDATE task_definitions SET key = :wanted WHERE key = :current", old, new)
        update("UPDATE task_operation_targets SET task_key = :wanted WHERE task_key = :current", old, new)
    current_type, wanted_type = pick("show", "collection")
    definitions = connection.execute(sa.text("SELECT id, allowed_resource_types FROM task_definitions")).all()
    for definition_id, allowed in definitions:
        values = json.loads(allowed) if isinstance(allowed, str) else allowed
        if isinstance(values, list) and current_type in values:
            values = [wanted_type if value == current_type else value for value in values]
            connection.execute(sa.text(
                "UPDATE task_definitions SET allowed_resource_types = :value WHERE id = :id"
            ).bindparams(value=json.dumps(values), id=definition_id))
    for table in ("task_runs", "task_schedules"):
        update(f"UPDATE {table} SET resource_type = :wanted WHERE resource_type = :current", "SHOW", "COLLECTION")
    for table in ("task_operations", "task_operation_targets"):
        update(f"UPDATE {table} SET resource_type = :wanted WHERE resource_type = :current", "show", "collection")
    for kind in _OPERATION_KINDS:
        update("UPDATE task_operations SET kind = :wanted WHERE kind = :current", f"show.{kind}", f"collection.{kind}")

    for table, column in _TASK_JSON_COLUMNS:
        rows = connection.execute(sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).all()
        for row_id, raw in rows:
            value = json.loads(raw) if isinstance(raw, str) else raw
            renamed = _renamed_json(value, reverse=reverse)
            if renamed != value:
                connection.execute(sa.text(
                    f"UPDATE {table} SET {column} = :value WHERE id = :id"
                ).bindparams(value=json.dumps(renamed), id=row_id))


# Template additions -----------------------------------------------------------

def _add_episode_uploader() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "author_name", sa.String(), nullable=True, comment="Who uploaded the episode, as the Source names them",
        ))


def _drop_episode_uploader() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("author_name")


# Existing files -------------------------------------------------------------

def _create_existing_file_scans() -> None:
    op.create_table(
        "existing_file_scans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "local_media_profile_id", sa.Integer(),
            sa.ForeignKey("local_media_profiles.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("folder", sa.Text(), nullable=False, comment="The scanned folder, as a /downloads/ path"),
        sa.Column("template", sa.Text(), nullable=True, comment="The old layout's template, to read names with"),
        sa.Column("status", sa.String(16), nullable=False, comment="waiting, scanning, ready, failed or finished"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column(
            "held_download_profile_ids", sa.JSON(), nullable=False,
            comment="Download Profiles switched on again when the scan is finished",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("collection_id", "local_media_profile_id", name="uq_existing_file_scan_scope"),
    )
    op.create_index("ix_existing_file_scans_collection_id", "existing_file_scans", ["collection_id"])
    op.create_index("ix_existing_file_scans_local_media_profile_id", "existing_file_scans", ["local_media_profile_id"])


def upgrade() -> None:
    _rename_schema(reverse=False)
    _rename_values(reverse=False)
    _add_episode_uploader()
    _create_existing_file_scans()


def downgrade() -> None:
    op.drop_table("existing_file_scans")
    _drop_episode_uploader()
    _rename_values(reverse=True)
    _rename_schema(reverse=True)
