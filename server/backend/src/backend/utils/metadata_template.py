"""A Collection profile's own title and description for an episode's NFO and embedded metadata.

They are Jinja templates over the same variables as the output template. Unlike a path, the text is
used as it renders: nothing is made safe for a file name, and a description may run over several lines.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from jinja2 import TemplateError, Template
from jinja2.exceptions import SecurityError, UndefinedError

from .output_template import (
    COLLECTION_OUTPUT_TEMPLATE_FIELDS,
    COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    episode_output_template_values,
    output_template_custom_index_keys,
    output_template_fields,
    validate_output_template_fields,
)
from .output_template_jinja import create_output_template_environment

if TYPE_CHECKING:
    from backend.db.models import Episode

logger = logging.getLogger(__name__)

METADATA_TEMPLATE_FIELDS = COLLECTION_OUTPUT_TEMPLATE_FIELDS | {"description"}
"""The output template's variables, and the episode's description, which is too long for a path."""

TITLE_TEMPLATE_MAX_LENGTH = 1000
DESCRIPTION_TEMPLATE_MAX_LENGTH = 4000


def validate_metadata_template(template: str) -> str:
    """The template, when it only uses the episode's variables; a ValueError says what is wrong."""
    validate_output_template_fields(
        template,
        allowed_fields=METADATA_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    )
    if output_template_custom_index_keys(template):
        raise ValueError("custom_index numbers files, so it only works in the output template")
    return template


@lru_cache(maxsize=128)
def _compiled(template: str) -> tuple[Template, frozenset[str]]:
    return create_output_template_environment().from_string(template), output_template_fields(template)


def render_metadata_template(template: str, values: dict[str, str]) -> str:
    """The template filled in with ``values``; a ValueError when it can't be."""
    try:
        compiled, fields = _compiled(template)
        return compiled.render({field: values.get(field, "") for field in METADATA_TEMPLATE_FIELDS | fields}).strip()
    except (SecurityError, UndefinedError, TemplateError, TypeError, ArithmeticError) as exc:
        raise ValueError(f"Could not render Jinja template: {exc}") from exc


def episode_metadata_text(episode: "Episode", profile) -> tuple[str | None, str | None]:
    """The title and description the profile gives the episode's metadata, or None where it keeps the site's.

    A template that renders empty, or can't render, keeps the site's text, so an episode never loses its title.
    """
    title_template = getattr(profile, "episode_title_template", None)
    description_template = getattr(profile, "episode_description_template", None)
    if not title_template and not description_template:
        return None, None
    values = {**episode_output_template_values(episode), "description": episode.description or ""}

    def render(template: str | None) -> str | None:
        if not template:
            return None
        try:
            return render_metadata_template(template, values) or None
        except ValueError as exc:
            logger.warning("Keeping the site's text for episode %s: %s", episode.id, exc)
            return None

    title = render(title_template)
    return (" ".join(title.split()) if title else None), render(description_template)
