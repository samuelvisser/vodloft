"""Each creator section keeps the key of its Site's section type

A Site names every type of section its creators have, such as SoundCloud's feeds, albums, playlists and singles.
``creator_sections.kind_label``, the Site's word for a section, becomes ``type``, the key of the section's type, from
which VODLoft names it. The Daily Wire's shows and Bandcamp's albums get keys of their own, so the settings for what
happens with a new one move from the shared "list" key to "show" and "album".

Revision ID: 7d3b9e41a6c2
Revises: 9c3e1f5a7b20
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "7d3b9e41a6c2"
down_revision = "9c3e1f5a7b20"
branch_labels = None
depends_on = None

# The key each Site's sections of a kind got when this migration was written. A SoundCloud list is an album unless
# SoundCloud called it a playlist; a kind not listed for a Site keeps the kind's own name.
_TYPES = {
    "soundcloud": {"list": "album", "item": "single"},
    "bandcamp": {"list": "album", "item": "single"},
    "dailywire": {"item": "movie"},
}
_GENERIC = {"feed": "feed", "list": "list", "show": "show", "item": "item"}
# The Sites whose shows or albums had the shared "list" setting, and the key they have now.
_MOVED = {"dailywire": "show", "bandcamp": "album"}
_LABELS = {"feed": "Feed", "list": "Playlist", "playlist": "Playlist", "album": "Album", "show": "Show",
           "movie": "Movie", "single": "Single"}


def _type(site_key: str | None, kind: str, label: str | None) -> str:
    if site_key == "soundcloud" and kind == "list" and label == "Playlist":
        return "playlist"
    return _TYPES.get(site_key or "", {}).get(kind) or _GENERIC.get(kind, kind)


def _settings(value: str | dict | None) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value or {})


def _site_keys(bind) -> dict[int, set[str]]:
    sites: dict[int, set[str]] = {}
    for creator_id, site_key in bind.execute(sa.text("SELECT creator_id, site_key FROM creator_accounts")):
        sites.setdefault(creator_id, set()).add(site_key)
    return sites


def upgrade() -> None:
    with op.batch_alter_table("creator_sections") as batch:
        batch.add_column(sa.Column(
            "type", sa.String(), nullable=True,
            comment="The key of the Site's section type it is, such as feed, list or album",
        ))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT creator_sections.id, creator_accounts.site_key, creator_sections.kind, creator_sections.kind_label"
        " FROM creator_sections JOIN creator_accounts ON creator_accounts.id = creator_sections.account_id"
    )).all()
    for section_id, site_key, kind, label in rows:
        bind.execute(sa.text("UPDATE creator_sections SET type = :type WHERE id = :id"),
                     {"type": _type(site_key, kind, label), "id": section_id})
    bind.execute(sa.text("UPDATE creator_sections SET type = kind WHERE type IS NULL"))
    with op.batch_alter_table("creator_sections") as batch:
        batch.alter_column("type", existing_type=sa.String(), nullable=False)
        batch.drop_column("kind_label")

    sites = _site_keys(bind)
    for creator_id, value in bind.execute(sa.text("SELECT id, new_lists FROM creators")).all():
        settings = _settings(value)
        if "list" not in settings:
            continue
        keys = sites.get(creator_id, set())
        for site_key, key in _MOVED.items():
            if site_key in keys:
                settings.setdefault(key, settings["list"])
        # The setting stays where another Site of the creator still has playlists under the key.
        if keys and keys <= {*_MOVED, "soundcloud"}:
            del settings["list"]
        bind.execute(sa.text("UPDATE creators SET new_lists = :settings WHERE id = :id"),
                     {"settings": json.dumps(settings), "id": creator_id})
    for collection_id, site_key, value in bind.execute(sa.text("SELECT id, site_key, new_lists FROM collections")).all():
        settings = _settings(value)
        if site_key in _MOVED and "list" in settings:
            settings[_MOVED[site_key]] = settings.pop("list")
            bind.execute(sa.text("UPDATE collections SET new_lists = :settings WHERE id = :id"),
                         {"settings": json.dumps(settings), "id": collection_id})


def downgrade() -> None:
    bind = op.get_bind()
    sites = _site_keys(bind)
    for creator_id, value in bind.execute(sa.text("SELECT id, new_lists FROM creators")).all():
        settings = _settings(value)
        keys = sites.get(creator_id, set())
        moved = [settings.pop(key) for site_key, key in _MOVED.items()
                 if site_key in keys and key in settings and not (key == "album" and "soundcloud" in keys)]
        if moved:
            settings.setdefault("list", moved[0])
            bind.execute(sa.text("UPDATE creators SET new_lists = :settings WHERE id = :id"),
                         {"settings": json.dumps(settings), "id": creator_id})
    for collection_id, site_key, value in bind.execute(sa.text("SELECT id, site_key, new_lists FROM collections")).all():
        settings = _settings(value)
        if site_key in _MOVED and _MOVED[site_key] in settings:
            settings["list"] = settings.pop(_MOVED[site_key])
            bind.execute(sa.text("UPDATE collections SET new_lists = :settings WHERE id = :id"),
                         {"settings": json.dumps(settings), "id": collection_id})

    with op.batch_alter_table("creator_sections") as batch:
        batch.add_column(sa.Column("kind_label", sa.String(), nullable=True, comment="What the Site calls it, such as Playlist"))
    for section_id, type_ in bind.execute(sa.text("SELECT id, type FROM creator_sections")).all():
        bind.execute(sa.text("UPDATE creator_sections SET kind_label = :label WHERE id = :id"),
                     {"label": _LABELS.get(type_), "id": section_id})
    with op.batch_alter_table("creator_sections") as batch:
        batch.drop_column("type")
