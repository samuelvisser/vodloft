"""The Daily Wire only offers 480p, 720p and 1080p.

Local Media Profiles only for The Daily Wire, which includes every movie profile, and RSS stream
profiles of Daily Wire collections, move to the nearest of those resolutions. They already
downloaded these, as the Daily Wire has no others.

A profile whose output template another profile of its type already uses at that resolution
would download the same files, so it is merged into that profile: its downloads, Download Profiles
and everything else it holds move there, except where that profile already holds the same.

Revision ID: 688634d39f23
Revises: 7e3b9d1a4c52
Create Date: 2026-11-05
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "688634d39f23"
down_revision = "7e3b9d1a4c52"
branch_labels = None
depends_on = None

_PROFILE_FORMATS = {
    "format_360p": "format_480p",
    "format_1440p": "format_1080p",
    "format_4k": "format_1080p",
    "format_8k": "format_1080p",
}
# A stream profile picks between downloads at 1080p and 720p.
_STREAM_FORMATS = {
    "format_360p": "format_720p",
    "format_480p": "format_720p",
    "format_1440p": "format_1080p",
    "format_4k": "format_1080p",
    "format_8k": "format_1080p",
}
# Tables that hold one row per Collection and profile, by the columns that make a row unique with the profile.
_SCOPED = {
    "custom_index_states": ("collection_id",),
    "existing_file_scans": ("collection_id",),
    "collection_local_assets": ("collection_id", "asset_type", "file_path"),
    "import_steps": ("run_id", "collection_id"),
}
_PROFILE_TYPE_TABLES = ("local_media_profiles_collection", "local_media_profiles_movie", "local_media_profiles_video")
_DOWNLOAD_TYPE_TABLES = (
    "media_downloads_episode", "media_downloads_movie", "media_downloads_movie_extra", "media_downloads_video",
)


def _only_dailywire(profile_type: str, source_keys) -> bool:
    if profile_type == "movie":
        return True  # Only The Daily Wire has movies.
    if isinstance(source_keys, str):
        source_keys = json.loads(source_keys)
    return source_keys == ["dailywire"]


def _delete_download(bind, download_id: int) -> None:
    for table in ("media_download_assets", "media_download_history"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE media_download_id = :id"), {"id": download_id})
    for table in _DOWNLOAD_TYPE_TABLES:
        bind.execute(sa.text(f"DELETE FROM {table} WHERE id = :id"), {"id": download_id})
    bind.execute(sa.text("DELETE FROM media_downloads WHERE id = :id"), {"id": download_id})


def _merge(bind, duplicate: int, keeper: int) -> None:
    """Move everything of the duplicate profile to the keeper and delete it."""
    params = {"duplicate": duplicate, "keeper": keeper}
    keeper_sources = bind.execute(
        sa.text("SELECT source_keys FROM local_media_profiles WHERE id = :keeper"), params,
    ).scalar()
    if isinstance(keeper_sources, str):
        keeper_sources = json.loads(keeper_sources)
    if keeper_sources is not None and "dailywire" not in keeper_sources:
        bind.execute(
            sa.text("UPDATE local_media_profiles SET source_keys = :keys WHERE id = :keeper"),
            {**params, "keys": json.dumps(["dailywire", *keeper_sources])},
        )

    for (download_profile_id, collection_id) in bind.execute(sa.text(
            "SELECT id, collection_id FROM download_profiles WHERE local_media_profile_id = :duplicate"), params).all():
        kept = bind.execute(sa.text(
            "SELECT id FROM download_profiles WHERE local_media_profile_id = :keeper AND collection_id = :collection"),
            {**params, "collection": collection_id},
        ).scalar()
        if kept is None:
            bind.execute(sa.text("UPDATE download_profiles SET local_media_profile_id = :keeper WHERE id = :id"),
                         {**params, "id": download_profile_id})
            continue
        moved = {"old": download_profile_id, "new": kept}
        bind.execute(sa.text("UPDATE media_downloads_episode SET download_profile_id = :new WHERE download_profile_id = :old"), moved)
        bind.execute(sa.text("UPDATE import_steps SET download_profile_id = :new WHERE download_profile_id = :old"), moved)
        bind.execute(sa.text("DELETE FROM download_profile_filters WHERE download_profile_id = :old"), moved)
        bind.execute(sa.text("DELETE FROM download_profiles WHERE id = :old"), moved)

    for (download_id, media_item_id) in bind.execute(sa.text(
            "SELECT id, media_item_id FROM media_downloads WHERE local_media_profile_id = :duplicate"), params).all():
        held = bind.execute(sa.text(
            "SELECT 1 FROM media_downloads WHERE local_media_profile_id = :keeper AND media_item_id = :media"),
            {**params, "media": media_item_id},
        ).first()
        if held:
            _delete_download(bind, download_id)
        else:
            bind.execute(sa.text("UPDATE media_downloads SET local_media_profile_id = :keeper WHERE id = :id"),
                         {**params, "id": download_id})

    for table, columns in _SCOPED.items():
        same = " AND ".join(f"kept.{column} = {table}.{column}" for column in columns)
        bind.execute(sa.text(
            f"DELETE FROM {table} WHERE local_media_profile_id = :duplicate AND EXISTS ("
            f"SELECT 1 FROM {table} AS kept WHERE kept.local_media_profile_id = :keeper AND {same})"
        ), params)
        bind.execute(sa.text(f"UPDATE {table} SET local_media_profile_id = :keeper WHERE local_media_profile_id = :duplicate"), params)

    for table in _PROFILE_TYPE_TABLES:
        bind.execute(sa.text(f"DELETE FROM {table} WHERE id = :duplicate"), params)
    bind.execute(sa.text("DELETE FROM local_media_profiles WHERE id = :duplicate"), params)


def upgrade() -> None:
    bind = op.get_bind()
    profiles = bind.execute(sa.text(
        "SELECT id, type, output_template, preferred_format, source_keys FROM local_media_profiles ORDER BY id"
    )).all()
    for (profile_id, profile_type, template, preferred, source_keys) in profiles:
        target = _PROFILE_FORMATS.get(preferred)
        if target is None or not _only_dailywire(profile_type, source_keys):
            continue
        keeper = bind.execute(sa.text(
            "SELECT id FROM local_media_profiles WHERE type = :type AND output_template = :template "
            "AND preferred_format = :format AND id != :id"
        ), {"type": profile_type, "template": template, "format": target, "id": profile_id}).scalar()
        if keeper is None:
            bind.execute(sa.text("UPDATE local_media_profiles SET preferred_format = :format WHERE id = :id"),
                         {"format": target, "id": profile_id})
        else:
            _merge(bind, profile_id, keeper)

    for old, new in _STREAM_FORMATS.items():
        bind.execute(sa.text(
            "UPDATE stream_profiles SET preferred_format = :new WHERE preferred_format = :old AND collection_id IN ("
            "SELECT id FROM collections WHERE source_key = 'dailywire')"
        ), {"old": old, "new": new})


def downgrade() -> None:
    # Every resolution was allowed before, so the profiles stay valid as they are.
    pass
