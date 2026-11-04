"""Sites: the website a collection or video is on, whichever Source fetches it.

Revision ID: 2bd0eb5fe4a6
Revises: c89f1a5ea2ba
Create Date: 2026-11-04

A Site, such as YouTube or The Daily Wire, can span several domains and can be
fetched by more than one Source. Collections and videos remember their Site, and a
collection also the Site's own id for it, so the same collection is added only once
per Site. The Source to ask first for a site's links moves from a domain to its Site.

Existing data changes with it:
- Collections and videos of The Daily Wire and NPO Start Sources get their Site here,
  and a collection keeps its slug as the Site's id. yt-dlp's need yt-dlp to tell their
  Site, so a background migration fills those in.
- A preferred Source for dailywire.com or npo.nl becomes the preferred Source of
  that Site.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "2bd0eb5fe4a6"
down_revision = "c89f1a5ea2ba"
branch_labels = None
depends_on = None


# The Sites of the Sources made for one site, and the domains they had preferences on.
_NAMED_SITES = {
    "dailywire": ("The Daily Wire", "dailywire.com"),
    "npo": ("NPO Start", "npo.nl"),
}


def upgrade() -> None:
    sites = op.create_table(
        "sites",
        sa.Column("key", sa.String(), nullable=False, comment="The Site's key, as the sources package tells it"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False, comment="The domains of the Site VODLoft has seen"),
        sa.Column(
            "preferred_source_key", sa.String(), nullable=True,
            comment="The Source asked first for links on this Site, when several Sources handle it",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_sites")),
    )
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "site_key", sa.String(), nullable=True,
            comment="The Site the collection is on; filled in the background for older collections",
        ))
        batch.add_column(sa.Column("site_ref", sa.String(), nullable=True, comment="The Site's own id for the collection"))
        batch.create_foreign_key("fk_collections_site_key_sites", "sites", ["site_key"], ["key"])
        batch.create_index("ix_collections_site_key", ["site_key"])
        batch.create_unique_constraint("uq_collections_site_key", ["site_key", "site_ref"])
    with op.batch_alter_table("media_items_video") as batch:
        batch.add_column(sa.Column(
            "site_key", sa.String(), nullable=True,
            comment="The Site the video is on; filled in the background for older videos",
        ))
        batch.create_foreign_key("fk_media_items_video_site_key_sites", "sites", ["site_key"], ["key"])
        batch.create_index("ix_media_items_video_site_key", ["site_key"])

    connection = op.get_bind()
    preferences = dict(connection.execute(sa.text("SELECT domain, source_key FROM source_domain_preferences")).all())
    rows = []
    for key, (name, domain) in _NAMED_SITES.items():
        used = connection.execute(sa.text(
            "SELECT 1 FROM collections WHERE source_key = :key "
            "UNION SELECT 1 FROM media_items WHERE source_key = :key AND type = 'video'"
        ), {"key": key}).first()
        if used is not None or domain in preferences:
            rows.append({"key": key, "name": name, "domains": [domain], "preferred_source_key": preferences.get(domain)})
    if rows:
        op.bulk_insert(sites, rows)
    for row in rows:
        connection.execute(
            sa.text("UPDATE collections SET site_key = :key, site_ref = slug WHERE source_key = :key"),
            {"key": row["key"]},
        )
        connection.execute(
            sa.text(
                "UPDATE media_items_video SET site_key = :key WHERE id IN "
                "(SELECT id FROM media_items WHERE source_key = :key AND type = 'video')"
            ),
            {"key": row["key"]},
        )
    op.drop_table("source_domain_preferences")


def downgrade() -> None:
    op.create_table(
        "source_domain_preferences",
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("domain", name=op.f("pk_source_domain_preferences")),
    )
    connection = op.get_bind()
    for key, (_name, domain) in _NAMED_SITES.items():
        connection.execute(
            sa.text(
                "INSERT INTO source_domain_preferences (domain, source_key) "
                "SELECT :domain, preferred_source_key FROM sites WHERE key = :key AND preferred_source_key IS NOT NULL"
            ),
            {"key": key, "domain": domain},
        )
    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_index("ix_media_items_video_site_key")
        batch.drop_constraint("fk_media_items_video_site_key_sites", type_="foreignkey")
        batch.drop_column("site_key")
    with op.batch_alter_table("collections") as batch:
        batch.drop_constraint("uq_collections_site_key", type_="unique")
        batch.drop_index("ix_collections_site_key")
        batch.drop_constraint("fk_collections_site_key_sites", type_="foreignkey")
        batch.drop_column("site_ref")
        batch.drop_column("site_key")
    op.drop_table("sites")
