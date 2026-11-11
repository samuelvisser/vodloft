"""Offer Local Media Profiles per Site instead of per Source.

A profile now lists the Sites it is offered for, such as YouTube or The Daily Wire, and whether Sites VODLoft
sees later join that list. A profile offered for every Source gets every Site VODLoft knows and takes later
Sites too. A profile limited to some Sources gets the Sites of those Sources: yt-dlp stands for every Site that
is not The Daily Wire or NPO Start, and for the Sites VODLoft sees later.

Revision ID: d3a7f1c9e2b5
Revises: 80a8b55fb9d6
Create Date: 2026-11-10
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "d3a7f1c9e2b5"
down_revision = "80a8b55fb9d6"
branch_labels = None
depends_on = None

# The Sites VODLoft knows before it has anything from them: the ones a Source is made for, and YouTube, which
# yt-dlp takes an API key for. Only The Daily Wire's own Source downloads movies.
_SOURCE_SITES = {"dailywire": "dailywire", "npo": "npo"}
_BUILTIN_SITES = ("dailywire", "npo", "youtube")
_MOVIE_SITES = ("dailywire",)


def _keys(value) -> list[str] | None:
    if isinstance(value, str):
        value = json.loads(value)
    return value


def _sites_for(profile_type: str, source_keys: list[str] | None, known: list[str]) -> tuple[list[str], bool]:
    if source_keys is None:
        chosen, upcoming = known, True
    else:
        chosen = [site for site in known if site in {_SOURCE_SITES[key] for key in source_keys if key in _SOURCE_SITES}]
        upcoming = "ytdlp" in source_keys
        if upcoming:
            chosen = [site for site in known if site in chosen or site not in _SOURCE_SITES.values()]
    if profile_type == "movie":
        chosen = [site for site in chosen if site in _MOVIE_SITES]
    return chosen, upcoming


def upgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "site_keys", sa.JSON(), nullable=False, server_default="[]",
            comment="The Sites this profile is offered for",
        ))
        batch.add_column(sa.Column(
            "include_upcoming_sites", sa.Boolean(), nullable=False, server_default=sa.true(),
            comment="Sites VODLoft sees for the first time join the profile's Sites",
        ))

    bind = op.get_bind()
    recorded = bind.execute(sa.text("SELECT key FROM sites")).scalars().all()
    known = sorted({*_BUILTIN_SITES, *recorded})
    profiles = bind.execute(sa.text("SELECT id, type, source_keys FROM local_media_profiles")).all()
    for profile_id, profile_type, source_keys in profiles:
        chosen, upcoming = _sites_for(profile_type, _keys(source_keys), known)
        bind.execute(
            sa.text("UPDATE local_media_profiles SET site_keys = :sites, include_upcoming_sites = :upcoming WHERE id = :id"),
            {"sites": json.dumps(chosen), "upcoming": upcoming, "id": profile_id},
        )

    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("source_keys")


def downgrade() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "source_keys", sa.JSON(), nullable=True,
            comment="The Sources this profile is offered for; NULL offers it for every Source",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("include_upcoming_sites")
        batch.drop_column("site_keys")
