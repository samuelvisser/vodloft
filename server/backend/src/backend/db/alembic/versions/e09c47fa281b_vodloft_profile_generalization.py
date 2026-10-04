"""Generalize inherited Local Media Profiles once and retire old schedules.

Revision ID: e09c47fa281b
Revises: d48fa9032e61
"""
import json
import re
from alembic import op
import sqlalchemy as sa
from jinja2 import meta
from jinja2.sandbox import ImmutableSandboxedEnvironment

revision = "e09c47fa281b"
down_revision = "d48fa9032e61"
branch_labels = None
depends_on = None

_renames = {"show": "collection", "show_title": "collection", "season": "group", "season_name": "group",
    "season_index": "group", "season_number": "group", "episode": "upstream_id", "episode_title": "title",
    "dw_episode_number": "episode_number", "episode_identifier": "upstream_id", "episode_label": "episode_number",
    "episode_published_date": "published_date", "movie_slug": "upstream_id", "movie_title": "title",
    "movie_extended_title": "title", "movie_author": "author", "movie_duration_seconds": "duration",
    "slug": "upstream_id", "extended_title": "title", "duration_seconds": "duration"}
_fields = {"domain", "title", "id", "upstream_id", "media_type", "collection", "group", "episode_number",
           "published_date", "author", "duration", "movie_year"}


def _template(value):
    # Replace variable tokens only inside Jinja expressions, leaving literal
    # folder names and quoted text intact.
    def expression(match):
        tokens = re.split(r"('(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")", match.group())
        for index in range(0, len(tokens), 2):
            tokens[index] = re.sub(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", lambda name:
                _renames.get(name.group(), name.group()), tokens[index])
        return "".join(tokens)
    converted = re.sub(r"{{.*?}}|{%.*?%}", expression, value, flags=re.S)
    try:
        ast = ImmutableSandboxedEnvironment().parse(converted)
        if meta.find_undeclared_variables(ast) - _fields or "custom_index" in converted:
            return value, "Review the inherited template: it uses fields outside the normalized media contract."
    except Exception:
        return value, "Review the inherited template before enabling acquisition."
    return converted, None


def upgrade():
    connection = op.get_bind()
    op.drop_index("uq_local_media_profiles_type_output_template_preferred_format", table_name="local_media_profiles")
    op.create_index("uq_local_media_profiles_type_output_template_preferred_format", "local_media_profiles",
        ["type", "output_template", "preferred_format"], unique=True,
        sqlite_where=sa.text("type <> 'domain'"), postgresql_where=sa.text("type <> 'domain'"))
    profiles = connection.execute(sa.text("SELECT id, type, output_template FROM local_media_profiles WHERE type IN ('show', 'movie')")).mappings().all()
    if profiles:
        domain_id = connection.execute(sa.text("SELECT id FROM vodloft_domains WHERE hostname='dailywire.com'")).scalar()
        if not domain_id:
            connection.execute(sa.text("INSERT INTO vodloft_domains(hostname, display_name) VALUES ('dailywire.com', 'The Daily Wire')"))
            domain_id = connection.execute(sa.text("SELECT id FROM vodloft_domains WHERE hostname='dailywire.com'")).scalar()
        for profile in profiles:
            template, impairment = _template(profile["output_template"])
            connection.execute(sa.text("""INSERT INTO local_media_profiles_domain
                (id,domain_id,applicable_kinds,enabled,delivery_target_ids,representation,impairment)
                VALUES (:id,:domain,:kinds,:enabled,'[]','{}',:impairment)"""),
                {"id": profile["id"], "domain": domain_id,
                 "kinds": json.dumps(["video"] if profile["type"] == "show" else ["movie", "movie_extra"]),
                 "enabled": not bool(impairment), "impairment": impairment})
            connection.execute(sa.text("UPDATE local_media_profiles SET type='domain',output_template=:template WHERE id=:id"),
                {"id": profile["id"], "template": template})
    # These persisted task definitions belong to the previous media model.
    # Collection automation is converted by a background migration before work
    # resumes; old schedules must not race that conversion.
    connection.execute(sa.text("UPDATE task_schedules SET active=0"))


def downgrade():
    # Profile generalization is a one-way data migration. Schema rollback does
    # not discard normalized profiles or the preserved historical child rows.
    pass
