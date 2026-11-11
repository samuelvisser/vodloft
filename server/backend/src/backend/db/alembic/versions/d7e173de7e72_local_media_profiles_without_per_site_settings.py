"""Give a Local Media Profile one value for auto-generated subtitles and SponsorBlock instead of one per Site.

Only a database that ran an earlier version of revision e8b2c4f6a1d3, which kept these settings per Site in
``site_settings``, has anything to change: the others already have one value per profile. Auto-generated subtitles
take YouTube's value, or else the most common one among the profile's Sites; SponsorBlock takes YouTube's, the only
Site that has it.

Revision ID: d7e173de7e72
Revises: e8b2c4f6a1d3
Create Date: 2026-11-10
"""
from __future__ import annotations

import json
from collections import Counter

import sqlalchemy as sa
from alembic import op

revision = "d7e173de7e72"
down_revision = "e8b2c4f6a1d3"
branch_labels = None
depends_on = None

_SPONSORBLOCK_SITE = "youtube"
# What a profile without SponsorBlock settings for YouTube keeps, with SponsorBlock off.
_SEGMENTS = {
    "sponsor": "chapter", "selfpromo": "keep", "interaction": "keep", "intro": "chapter", "outro": "chapter",
    "preview": "keep", "filler": "keep", "hook": "keep", "music_offtopic": "keep", "poi_highlight": "chapter",
    "chapter": "keep",
}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _has_site_settings() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("local_media_profiles")
    return any(column["name"] == "site_settings" for column in columns)


def upgrade() -> None:
    if not _has_site_settings():
        return
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "auto_subtitles", sa.String(16), nullable=False, server_default="fallback",
            comment="Auto-generated subtitles: never, fallback (when there is no real one) or always",
        ))
        batch.add_column(sa.Column("sponsorblock_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), nullable=False, server_default="{}",
            comment="SponsorBlock segment type to keep, chapter or cut",
        ))

    bind = op.get_bind()
    for profile_id, site_settings in bind.execute(sa.text("SELECT id, site_settings FROM local_media_profiles")).all():
        sites = _json(site_settings) or {}
        youtube = sites.get(_SPONSORBLOCK_SITE)
        if youtube is not None:
            auto = youtube.get("auto_subtitles", "fallback")
        else:
            counts = Counter(values.get("auto_subtitles") for _key, values in sorted(sites.items()))
            counts.pop(None, None)
            auto = counts.most_common(1)[0][0] if counts else "fallback"
        if youtube is not None and youtube.get("sponsorblock_enabled") is not None:
            enabled = bool(youtube["sponsorblock_enabled"])
            segments = {**_SEGMENTS, **(youtube.get("sponsorblock_segments") or {})}
        else:
            enabled, segments = False, _SEGMENTS
        bind.execute(
            sa.text(
                "UPDATE local_media_profiles SET auto_subtitles = :auto, sponsorblock_enabled = :enabled, "
                "sponsorblock_segments = :segments WHERE id = :id"
            ),
            {"auto": auto, "enabled": enabled, "segments": json.dumps(segments), "id": profile_id},
        )

    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("site_settings")


def downgrade() -> None:
    # Revision e8b2c4f6a1d3 now keeps one value per profile too, so there is nothing to undo.
    pass
