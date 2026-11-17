"""Movie Local Media Profiles become Video Local Media Profiles.

One Video profile type keeps single videos, and movies with their extras. Every Movie profile moves to it and keeps
its own Sites: it stops taking Sites VODLoft sees for the first time, since those only have single videos. A Movie
profile that has the same template and format as a Video profile gets a Jinja comment at the end of its template,
which names no file differently, so the two stay apart.

Revision ID: 409629042e13
Revises: 2f7a91c4d8e3
Create Date: 2026-11-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "409629042e13"
down_revision = "2f7a91c4d8e3"
branch_labels = None
depends_on = None

_KEPT_APART = "{# kept apart from {name} #}"


def upgrade() -> None:
    bind = op.get_bind()
    profiles = sa.table(
        "local_media_profiles",
        sa.column("id", sa.Integer), sa.column("type", sa.String), sa.column("name", sa.String),
        sa.column("output_template", sa.String), sa.column("preferred_format", sa.String),
        sa.column("include_upcoming_sites", sa.Boolean),
    )
    video_keys = {
        (row.output_template, row.preferred_format): row.name
        for row in bind.execute(sa.select(profiles).where(profiles.c.type == "video"))
    }
    for row in bind.execute(sa.select(profiles).where(profiles.c.type == "movie")).all():
        clash = video_keys.get((row.output_template, row.preferred_format))
        if clash is not None:
            bind.execute(
                profiles.update().where(profiles.c.id == row.id)
                .values(output_template=row.output_template + _KEPT_APART.replace("{name}", clash.replace("#}", "")))
            )

    bind.execute(sa.text("INSERT INTO local_media_profiles_video (id) SELECT id FROM local_media_profiles_movie"))
    bind.execute(
        profiles.update().where(profiles.c.type == "movie").values(type="video", include_upcoming_sites=False)
    )
    op.drop_table("local_media_profiles_movie")


def downgrade() -> None:
    # Former Movie profiles cannot be told apart again, so they stay Video profiles.
    op.create_table(
        "local_media_profiles_movie",
        sa.Column("id", sa.Integer(), sa.ForeignKey("local_media_profiles.id", ondelete="CASCADE"), primary_key=True),
    )
