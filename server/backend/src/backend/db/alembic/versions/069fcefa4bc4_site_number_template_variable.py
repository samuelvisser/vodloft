"""The template variable source_number is called site_number: every Site that numbers its episodes fills it, not only
The Daily Wire. Saved output, NFO and existing-file scan templates name the new variable; only the variable is
renamed, not literal text, so every file keeps its name.

Revision ID: 069fcefa4bc4
Revises: 927c19d4a79c
Create Date: 2026-11-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from jinja2 import Environment, TemplateSyntaxError

revision = "069fcefa4bc4"
down_revision = "927c19d4a79c"
branch_labels = None
depends_on = None

_OLD = "source_number"
_NEW = "site_number"

# Every stored template that can name an episode's variables.
_TEMPLATE_COLUMNS = (
    ("local_media_profiles", "output_template"),
    ("local_media_profiles_collection", "episode_title_template"),
    ("local_media_profiles_collection", "episode_description_template"),
    ("existing_file_scans", "template"),
)


def upgrade() -> None:
    _rename_in_templates(_OLD, _NEW)


def downgrade() -> None:
    _rename_in_templates(_NEW, _OLD)


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
