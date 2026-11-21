"""A collection's slug has nothing that can't be a part of a link to its page.

A collection made from a creator's album or playlist took the album's id on its Site as its slug, which on SoundCloud and
Bandcamp is the album's path, slashes and all, so the link to its page led nowhere. Such a slug now becomes one made
from it, as a new collection gets.

Revision ID: 0b8b8a447385
Revises: a4318a92a5ca
Create Date: 2026-11-21
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op


revision = "0b8b8a447385"
down_revision = "a4318a92a5ca"
branch_labels = None
depends_on = None

_NOT_IN_LINKS = re.compile(r"[/\\?#%\s]")


def _slugify(text: str) -> str:
    out = []
    for ch in text.strip().lower():
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        elif ch.isspace() or ch in "/\\":
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, slug FROM collections")).all()
    taken = {slug for _id, slug in rows}
    for collection_id, slug in rows:
        if not _NOT_IN_LINKS.search(slug):
            continue
        base = _slugify(slug) or "collection"
        new, suffix = base, 2
        while new in taken:
            new, suffix = f"{base}-{suffix}", suffix + 1
        taken.add(new)
        bind.execute(sa.text("UPDATE collections SET slug = :slug WHERE id = :id"), {"slug": new, "id": collection_id})


def downgrade() -> None:
    # The old slugs led nowhere, so they are not made again.
    pass
