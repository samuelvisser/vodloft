"""Episodes without usable media become episodes their Source no longer has.

An episode that had no usable media is deleted when it has no files. One with files keeps them: it is marked removed
from its Source, as published, and the Home page asks whether to keep it. It gets back the identifier it had before,
or a new aux identifier when another episode took that one.

Revision ID: 3564f2e6fe1c
Revises: 63dbd1de00d8
Create Date: 2026-11-18
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "3564f2e6fe1c"
down_revision = "63dbd1de00d8"
branch_labels = None
depends_on = None

_EPISODES = "media_items_episode"
_KEYS = ("no_usable_media.reason", "no_usable_media.since", "no_usable_media.previous_identifier")


def _meta(connection, parent_table: str, parent_id: int, key: str) -> str | None:
    return connection.execute(
        sa.text("SELECT value FROM metadata WHERE parent_table = :table AND parent_id = :id AND key = :key"),
        {"table": parent_table, "id": parent_id, "key": key},
    ).scalar()


def _set_collection_meta(connection, collection_id: int, key: str, value: str) -> None:
    updated = connection.execute(
        sa.text("UPDATE metadata SET value = :value WHERE parent_table = 'collections' AND parent_id = :id AND key = :key"),
        {"value": value, "id": collection_id, "key": key},
    ).rowcount
    if not updated:
        now = datetime.now(timezone.utc)
        connection.execute(
            sa.text(
                "INSERT INTO metadata (parent_table, parent_id, key, value, created_at, updated_at) "
                "VALUES ('collections', :id, :key, :value, :now, :now)"
            ),
            {"id": collection_id, "key": key, "value": value, "now": now},
        )


def _free(connection, collection_id: int, identifier: str) -> bool:
    return connection.execute(
        sa.text(f"SELECT 1 FROM {_EPISODES} WHERE collection_id = :collection AND episode_identifier = :identifier"),
        {"collection": collection_id, "identifier": identifier},
    ).first() is None


def _new_aux(connection, collection_id: int) -> str:
    numbers = [int(_meta(connection, "collections", collection_id, "ep_id.latest_aux_num") or 0)]
    for (identifier,) in connection.execute(
        sa.text(f"SELECT episode_identifier FROM {_EPISODES} WHERE collection_id = :collection AND episode_identifier LIKE 'aux.%'"),
        {"collection": collection_id},
    ):
        payload = identifier.partition(".")[2]
        if payload.isdigit():
            numbers.append(int(payload))
    number = max(numbers) + 1
    _set_collection_meta(connection, collection_id, "ep_id.latest_aux_num", str(number))
    return f"aux.{number}"


def _as_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _keep(connection, episode) -> None:
    identifier = episode.episode_identifier
    if identifier.startswith("not-usable."):
        previous = _meta(connection, _EPISODES, episode.id, "no_usable_media.previous_identifier")
        if previous and _free(connection, episode.collection_id, previous):
            identifier = previous
            published = _as_utc(episode.published_date)
            if previous.startswith("ep.") and episode.collection_identifier == "date_based" and published is not None:
                head = int(_meta(connection, "collections", episode.collection_id, "ep_id.latest_ep_date") or 0)
                _set_collection_meta(
                    connection, episode.collection_id, "ep_id.latest_ep_date", str(max(head, int(published.timestamp()))),
                )
        else:
            identifier = _new_aux(connection, episode.collection_id)
    connection.execute(
        sa.text(
            f"UPDATE {_EPISODES} SET publish_status = 'published_final', episode_identifier = :identifier, "
            "metadata_is_final = :false WHERE id = :id"
        ),
        {"identifier": identifier, "id": episode.id, "false": False},
    )
    connection.execute(sa.text("UPDATE media_items SET removed_from_source = :true WHERE id = :id"), {"true": True, "id": episode.id})
    connection.execute(
        sa.text("DELETE FROM metadata WHERE parent_table = :table AND parent_id = :id AND key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True),
        ),
        {"table": _EPISODES, "id": episode.id, "keys": list(_KEYS)},
    )


def _delete(connection, episode_id: int) -> None:
    connection.execute(
        sa.text("DELETE FROM metadata WHERE parent_table = :table AND parent_id = :id"),
        {"table": _EPISODES, "id": episode_id},
    )
    connection.execute(sa.text(f"DELETE FROM {_EPISODES} WHERE id = :id"), {"id": episode_id})
    connection.execute(sa.text("DELETE FROM media_items WHERE id = :id"), {"id": episode_id})


def upgrade() -> None:
    connection = op.get_bind()
    episodes = connection.execute(sa.text(
        f"SELECT e.id, e.collection_id, e.episode_identifier, e.published_date, c.episode_identifier AS collection_identifier "
        f"FROM {_EPISODES} e JOIN collections c ON c.id = e.collection_id "
        "WHERE e.publish_status = 'no_usable_media' ORDER BY e.id"
    )).all()
    for episode in episodes:
        has_files = connection.execute(
            sa.text("SELECT 1 FROM media_downloads WHERE media_item_id = :id"), {"id": episode.id},
        ).first() is not None
        if has_files:
            _keep(connection, episode)
        else:
            _delete(connection, episode.id)
    connection.execute(sa.text(
        "DELETE FROM metadata WHERE parent_table = 'collections' AND key = 'ep_id.latest_not_usable_num'"
    ))


def downgrade() -> None:
    # Deleted episodes cannot come back; the kept ones stay removed from their Source.
    pass
