"""Keep auto-generated subtitles and SponsorBlock on Local Media Profiles instead of on Download Profiles.

Manual downloads have no Download Profile, so they could never use these settings. Each Local Media Profile
now keeps them, and they apply on the Sites that have them. A profile takes what most of its Download Profiles
on those Sites had.

Revision ID: e8b2c4f6a1d3
Revises: d3a7f1c9e2b5
Create Date: 2026-11-10
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import sqlalchemy as sa
from alembic import op

revision = "e8b2c4f6a1d3"
down_revision = "d3a7f1c9e2b5"
branch_labels = None
depends_on = None

# Neither The Daily Wire nor NPO Start has auto-generated subtitles; only YouTube has SponsorBlock.
_WITHOUT_AUTO_SUBTITLES = {"dailywire", "npo"}
_SPONSORBLOCK_SITE = "youtube"
# What a profile without YouTube Download Profiles keeps, with SponsorBlock off.
_SEGMENTS = {
    "sponsor": "chapter", "selfpromo": "keep", "interaction": "keep", "intro": "chapter", "outro": "chapter",
    "preview": "keep", "filler": "keep", "hook": "keep", "music_offtopic": "keep", "poi_highlight": "chapter",
    "chapter": "keep",
}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def upgrade() -> None:
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
    rows = bind.execute(sa.text(
        "SELECT download_profiles.local_media_profile_id, collections.site_key, download_profiles.auto_subtitles, "
        "download_profiles.sponsorblock_enabled, download_profiles.sponsorblock_segments "
        "FROM download_profiles JOIN collections ON collections.id = download_profiles.collection_id "
        "ORDER BY download_profiles.id"
    )).all()
    auto_subtitles: dict[int, Counter] = defaultdict(Counter)
    sponsorblock: dict[int, Counter] = defaultdict(Counter)
    for profile_id, site_key, auto, enabled, segments in rows:
        if site_key not in _WITHOUT_AUTO_SUBTITLES:
            auto_subtitles[profile_id][auto] += 1
        if site_key == _SPONSORBLOCK_SITE:
            sponsorblock[profile_id][(bool(enabled), json.dumps(_json(segments) or {}, sort_keys=True))] += 1

    for (profile_id,) in bind.execute(sa.text("SELECT id FROM local_media_profiles")).all():
        # The most common choice; on a tie, the one of the oldest Download Profile.
        auto = auto_subtitles[profile_id].most_common(1)[0][0] if auto_subtitles[profile_id] else "fallback"
        if sponsorblock[profile_id]:
            enabled, segments = sponsorblock[profile_id].most_common(1)[0][0]
            segments = {**_SEGMENTS, **json.loads(segments)}
        else:
            enabled, segments = False, _SEGMENTS
        bind.execute(
            sa.text(
                "UPDATE local_media_profiles SET auto_subtitles = :auto, sponsorblock_enabled = :enabled, "
                "sponsorblock_segments = :segments WHERE id = :id"
            ),
            {"auto": auto, "enabled": enabled, "segments": json.dumps(segments), "id": profile_id},
        )

    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("auto_subtitles")
        batch.drop_column("sponsorblock_enabled")
        batch.drop_column("sponsorblock_segments")


def downgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "auto_subtitles", sa.String(16), nullable=False, server_default="fallback",
            comment="YouTube's auto-generated subtitles: never, fallback (when there is no real one) or always",
        ))
        batch.add_column(sa.Column("sponsorblock_enabled", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), nullable=False, server_default="{}",
            comment="SponsorBlock segment type to keep, chapter or cut out, for YouTube Collections",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("sponsorblock_segments")
        batch.drop_column("sponsorblock_enabled")
        batch.drop_column("auto_subtitles")
