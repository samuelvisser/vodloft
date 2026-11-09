"""Give each Download Profile a choice for SponsorBlock's highlight, hook and viewer chapters.

VODLoft always marked the highlight as a chapter when SponsorBlock was on, so it starts as Chapter and downloads
stay as they were. VODLoft never asked for hooks and viewer chapters, so they start as Keep.

Revision ID: 4f7c2e9a1b38
Revises: 7d3e9b2c41fa
Create Date: 2026-11-09
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "4f7c2e9a1b38"
down_revision = "7d3e9b2c41fa"
branch_labels = None
depends_on = None

_ADDED = {"hook": "keep", "poi_highlight": "chapter", "chapter": "keep"}
_profiles = sa.table("download_profiles", sa.column("id", sa.Integer), sa.column("sponsorblock_segments", sa.JSON))


def _rewrite(change) -> None:
    connection = op.get_bind()
    for profile_id, segments in connection.execute(sa.select(_profiles.c.id, _profiles.c.sponsorblock_segments)).all():
        if isinstance(segments, str):
            segments = json.loads(segments)
        changed = change(dict(segments or {}))
        if changed != segments:
            connection.execute(
                _profiles.update().where(_profiles.c.id == profile_id).values(sponsorblock_segments=changed)
            )


def upgrade() -> None:
    _rewrite(lambda segments: {**_ADDED, **segments})


def downgrade() -> None:
    _rewrite(lambda segments: {key: value for key, value in segments.items() if key not in _ADDED})
