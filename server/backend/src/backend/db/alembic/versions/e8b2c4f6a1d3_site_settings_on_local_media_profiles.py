"""Keep auto-generated subtitles and SponsorBlock on Local Media Profiles, per Site, instead of on Download Profiles.

Manual downloads have no Download Profile, so they could never use these settings. Each Local Media Profile
now keeps them per Site. A profile takes, for each Site, what most of its Download Profiles on that Site's
collections had. A Site without Download Profiles keeps following the Site's own settings.

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

# The Daily Wire shows neither setting.
_WITHOUT_SETTINGS = {"dailywire"}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def upgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "site_settings", sa.JSON(), nullable=False, server_default="{}",
            comment="Settings only some Sites show, such as YouTube's SponsorBlock, by Site key",
        ))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT download_profiles.local_media_profile_id, collections.site_key, download_profiles.auto_subtitles, "
        "download_profiles.sponsorblock_enabled, download_profiles.sponsorblock_segments "
        "FROM download_profiles JOIN collections ON collections.id = download_profiles.collection_id "
        "WHERE collections.site_key IS NOT NULL ORDER BY download_profiles.id"
    )).all()
    found: dict[int, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for profile_id, site_key, auto_subtitles, sponsorblock_enabled, segments in rows:
        if site_key in _WITHOUT_SETTINGS:
            continue
        choice = (auto_subtitles, bool(sponsorblock_enabled), json.dumps(_json(segments) or {}, sort_keys=True))
        found[profile_id][site_key][choice] += 1
    for profile_id, sites in found.items():
        settings = {}
        for site_key, choices in sorted(sites.items()):
            # The most common choice; on a tie, the one of the oldest Download Profile.
            (auto_subtitles, sponsorblock_enabled, segments), _count = choices.most_common(1)[0]
            settings[site_key] = {
                "auto_subtitles": auto_subtitles, "sponsorblock_enabled": sponsorblock_enabled,
                "sponsorblock_segments": json.loads(segments),
            }
        bind.execute(
            sa.text("UPDATE local_media_profiles SET site_settings = :settings WHERE id = :id"),
            {"settings": json.dumps(settings), "id": profile_id},
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
            comment="SponsorBlock segment type to keep, chapter or cut, for YouTube Collections",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("site_settings")
