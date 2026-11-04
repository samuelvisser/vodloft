"""Metadata refresh schedules per Site, and for single videos.

Revision ID: 5b75b63e55f2
Revises: 2bd0eb5fe4a6
Create Date: 2026-11-04

Each Site follows the system schedule, a schedule of its own, or none, while VODLoft
looks its new items up again. The Daily Wire and YouTube have schedules of their own:
The Daily Wire keeps the intervals every Site had until now, and a background
migration copies a schedule the user set in the config file to it. Single videos get
the flag episodes already have; the videos VODLoft has are done.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "5b75b63e55f2"
down_revision = "2bd0eb5fe4a6"
branch_labels = None
depends_on = None


# The schedules the sources package gives these Sites.
_OWN_SCHEDULES = {
    "dailywire": "15m,30m,1h,3h,6h,24h,3d",
    "youtube": "30m,2h,6h,24h,3d,7d,14d",
}


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(sa.Column(
            "refresh_mode", sa.String(), nullable=False, server_default="system",
            comment="Which schedule the Site's items follow while their metadata is looked up again: off, system or own",
        ))
        batch.add_column(sa.Column(
            "refresh_intervals", sa.String(), nullable=True,
            comment="The Site's own refresh schedule, such as 30m,2h,24h, used when refresh_mode is own",
        ))
    with op.batch_alter_table("media_items_video") as batch:
        batch.add_column(sa.Column(
            "metadata_is_final", sa.Boolean(), nullable=False, server_default="1",
            comment="False while VODLoft still looks the video up again after publication",
        ))
    connection = op.get_bind()
    for key, intervals in _OWN_SCHEDULES.items():
        connection.execute(
            sa.text("UPDATE sites SET refresh_mode = 'own', refresh_intervals = :intervals WHERE key = :key"),
            {"key": key, "intervals": intervals},
        )


def downgrade() -> None:
    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_column("metadata_is_final")
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("refresh_intervals")
        batch.drop_column("refresh_mode")
