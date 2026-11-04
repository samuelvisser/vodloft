"""Publish statuses every Source shares: dw_processing and published_with_countdown get neutral names.

Revision ID: b9dbb772c34e
Revises: 5b75b63e55f2
Create Date: 2026-11-04

A Source now names each publish status its own way, so the stored values no longer
speak of The Daily Wire. Every place that stores a publish status is rewritten:
episodes, episode downloads, download history, operations and episode metadata.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "b9dbb772c34e"
down_revision = "5b75b63e55f2"
branch_labels = None
depends_on = None


_RENAMED = {"dw_processing": "source_processing", "published_with_countdown": "published_preliminary"}
_METADATA_KEYS = {"ep_status.dw_processing.slug": "ep_status.source_processing.slug"}
# JSON columns, and the keys in them that hold a publish status.
_JSON_FIELDS = (
    ("media_download_history", "metadata", "started_publish_status"),
    ("task_operations", "context", "episode_publish_status"),
    ("task_operations", "result", "publish_status"),
)


def _rename_values(connection, renames: dict[str, str]) -> None:
    for old, new in renames.items():
        connection.execute(sa.text(
            "UPDATE media_items_episode SET publish_status = :new WHERE publish_status = :old"
        ), {"old": old, "new": new})
        connection.execute(sa.text(
            "UPDATE media_downloads_episode SET downloaded_publish_status = :new WHERE downloaded_publish_status = :old"
        ), {"old": old, "new": new})
    for table, column, key in _JSON_FIELDS:
        rows = connection.execute(sa.text(
            f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"
        )).all()
        for row_id, raw in rows:
            value = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(value, dict) and value.get(key) in renames:
                value[key] = renames[value[key]]
                connection.execute(sa.text(
                    f"UPDATE {table} SET {column} = :value WHERE id = :id"
                ), {"value": json.dumps(value), "id": row_id})


def _rename_keys(connection, renames: dict[str, str]) -> None:
    for old, new in renames.items():
        connection.execute(sa.text("UPDATE metadata SET key = :new WHERE key = :old"), {"old": old, "new": new})


def upgrade() -> None:
    connection = op.get_bind()
    _rename_values(connection, _RENAMED)
    _rename_keys(connection, _METADATA_KEYS)


def downgrade() -> None:
    connection = op.get_bind()
    _rename_values(connection, {new: old for old, new in _RENAMED.items()})
    _rename_keys(connection, {new: old for old, new in _METADATA_KEYS.items()})
