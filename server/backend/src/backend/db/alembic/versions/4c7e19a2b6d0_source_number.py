"""Rename the episodes' dw_episode_number to source_number, also in saved templates.

Revision ID: 4c7e19a2b6d0
Revises: b5d81e3c7a26
Create Date: 2026-11-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from jinja2 import Environment, TemplateSyntaxError


revision = "4c7e19a2b6d0"
down_revision = "b5d81e3c7a26"
branch_labels = None
depends_on = None

_OLD_NAME = "dw_episode_number"
_NEW_NAME = "source_number"
_OLD_COMMENT = "Episode number exactly as returned by The Daily Wire"
_NEW_COMMENT = "The episode number as its Site writes it, such as 2460.10 on The Daily Wire; empty on most Sites"

# Every stored template that can name an episode's variables.
_TEMPLATE_COLUMNS = (
    ("local_media_profiles", "output_template"),
    ("local_media_profiles_collection", "episode_title_template"),
    ("local_media_profiles_collection", "episode_description_template"),
    ("existing_file_scans", "template"),
)


def _rename_variable(source: str, old: str, new: str) -> str:
    """Rename one variable in a Jinja template, leaving all other text, such as literal text, as it is."""
    try:
        tokens = list(Environment().lex(source))
    except TemplateSyntaxError:
        return source
    if "".join(value for _, _, value in tokens) != source:
        return source
    return "".join(new if kind == "name" and value == old else value for _, kind, value in tokens)


def _rename_in_templates(old: str, new: str) -> None:
    connection = op.get_bind()
    for table_name, column_name in _TEMPLATE_COLUMNS:
        table = sa.table(table_name, sa.column("id"), sa.column(column_name))
        column = table.c[column_name]
        rows = connection.execute(sa.select(table.c.id, column).where(column.like(f"%{old}%"))).all()
        for row_id, template in rows:
            renamed = _rename_variable(template, old, new)
            if renamed != template:
                connection.execute(table.update().where(table.c.id == row_id).values({column_name: renamed}))


def _rename_column(old: str, new: str, comment: str, existing_comment: str) -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.alter_column(old, new_column_name=new, existing_type=sa.String(), existing_nullable=True,
                           comment=comment, existing_comment=existing_comment)


def upgrade() -> None:
    _rename_column(_OLD_NAME, _NEW_NAME, _NEW_COMMENT, _OLD_COMMENT)
    _rename_in_templates(_OLD_NAME, _NEW_NAME)


def downgrade() -> None:
    _rename_in_templates(_NEW_NAME, _OLD_NAME)
    _rename_column(_NEW_NAME, _OLD_NAME, _OLD_COMMENT, _NEW_COMMENT)
