"""Give imported seasons back their Source's slug, and merge the duplicate seasons that caused.

An import used to make every season slug unique across all of VODLoft, while a season
slug only has to be unique within its collection. The second imported show with an
"extras" season got "extras-2", the next "extras-3", and so on. Indexing finds a
collection's seasons by the Source's slug, so it did not recognise these seasons and
added the same season a second time.

A season is restored when the import created it, its slug ends in "-<n>" with n of 2 or
more, and either indexing already added a season of the same name under the plain slug,
or every slug the import would have tried before it (the plain slug, then "-2" up to
"-<n-1>") belongs to a season of another collection. A duplicate's episodes and Download
Profile choices move to the imported season and the duplicate is removed.

Revision ID: c89f1a5ea2ba
Revises: 4b8e1d27a6c3
Create Date: 2026-11-03
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op


revision = "c89f1a5ea2ba"
down_revision = "4b8e1d27a6c3"
branch_labels = None
depends_on = None

_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<number>\d+)$")


def upgrade() -> None:
    bind = op.get_bind()
    seasons = bind.execute(sa.text("SELECT id, collection_id, slug, name FROM seasons")).all()
    imported = set(bind.execute(sa.text(
        "SELECT entity_id FROM import_links WHERE kind = 'season' AND entity_id IS NOT NULL"
    )).scalars())
    collections_by_slug: dict[str, set[int]] = {}
    for _id, collection_id, slug, _name in seasons:
        collections_by_slug.setdefault(slug, set()).add(collection_id)

    for season_id, collection_id, slug, name in seasons:
        match = _SUFFIX.match(slug)
        if season_id not in imported or match is None or int(match["number"]) < 2:
            continue
        base = match["base"]
        duplicate = bind.execute(
            sa.text("SELECT id, name FROM seasons WHERE collection_id = :collection AND slug = :slug"),
            {"collection": collection_id, "slug": base},
        ).one_or_none()
        if duplicate is not None:
            if duplicate.name != name:
                continue
            _merge(bind, keep=season_id, remove=duplicate.id)
        else:
            tried = [base] + [f"{base}-{number}" for number in range(2, int(match["number"]))]
            if not all(collections_by_slug.get(candidate, set()) - {collection_id} for candidate in tried):
                continue
        bind.execute(sa.text("UPDATE seasons SET slug = :slug WHERE id = :id"), {"slug": base, "id": season_id})


def _merge(bind, *, keep: int, remove: int) -> None:
    ids = {"keep": keep, "remove": remove}
    bind.execute(sa.text("UPDATE media_items_episode SET season_id = :keep WHERE season_id = :remove"), ids)
    bind.execute(sa.text(
        "INSERT INTO download_profile_seasons (download_profile_id, season_id) "
        "SELECT download_profile_id, :keep FROM download_profile_seasons WHERE season_id = :remove "
        "AND download_profile_id NOT IN (SELECT download_profile_id FROM download_profile_seasons WHERE season_id = :keep)"
    ), ids)
    bind.execute(sa.text("DELETE FROM download_profile_seasons WHERE season_id = :remove"), ids)
    bind.execute(sa.text("DELETE FROM seasons WHERE id = :remove"), ids)


def downgrade() -> None:
    # The suffixed slugs were a mistake; there is nothing to restore.
    pass
