"""Pinchflat's "liquid-style" ``{{ name }}`` templates, expanded as Pinchflat does.

This mirrors ``Pinchflat.Downloading.OutputPathBuilder.build``: each
``{{ name }}`` becomes one of Pinchflat's custom values or, for any other
name, ``%(name)S``. Custom values are expanded one level deep, so a custom
value may use another value but not one that itself needs expanding. The
result is a plain yt-dlp output template.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from .grammar import TemplateSyntaxError

CUSTOM_VALUES: dict[str, str] = {
    "upload_year": "%(upload_date>%Y)S",
    "upload_month": "%(upload_date>%m)S",
    "upload_day": "%(upload_date>%d)S",
    "upload_yyyy_mm_dd": "%(upload_date>%Y-%m-%d)S",
    "season_from_date": "%(upload_date>%Y)S",
    "season_episode_from_date": "s%(upload_date>%Y)Se%(upload_date>%m%d)S",
    "season_episode_index_from_date": "s%(upload_date>%Y)Se%(upload_date>%m%d)S{{ media_upload_date_index }}",
    "artist_name": "%(artist,creator,uploader,uploader_id)S",
    "static_season__episode_by_index": "Season 1/s01e{{ media_playlist_index }}",
    "static_season__episode_by_date": "Season 1/s01e%(upload_date>%y%m%d)S",
    "season_by_year__episode_by_date": "Season %(upload_date>%Y)S/s%(upload_date>%Y)Se%(upload_date>%m%d)S",
    "season_by_year__episode_by_date_and_index": (
        "Season %(upload_date>%Y)S/s%(upload_date>%Y)Se%(upload_date>%m%d)S{{ media_upload_date_index }}"
    ),
}

# The values Pinchflat adds for each download, from the source and the media item.
ITEM_VALUES = (
    "media_item_id", "source_id", "media_profile_id",
    "source_custom_name", "source_collection_id", "source_collection_name", "source_collection_type",
    "media_playlist_index", "media_upload_date_index",
)
PSEUDO_FIELD_PREFIX = "__pinchflat_"
"""Item values become yt-dlp fields with this prefix, so the converter can see them."""

_INTERPOLATION = re.compile(r"\{\{[ \t\n\r]*([A-Za-z0-9_]+)[ \t\n\r]*\}\}")


def _render(template: str, variables: Mapping[str, str]) -> str:
    out: list[str] = []
    position = 0
    while position < len(template):
        start = template.find("{{", position)
        if start < 0:
            out.append(template[position:])
            break
        out.append(template[position:start])
        match = _INTERPOLATION.match(template, start)
        if match is None:
            # NimbleParsec finds neither an interpolation nor text here.
            raise TemplateSyntaxError("Pinchflat can't read this {{ }}; it takes one plain name", start)
        name = match.group(1)
        out.append(variables[name] if variables.get(name) is not None else f"%({name})S")
        position = match.end()
    return "".join(out)


def expand(template: str, item_values: Mapping[str, str | None] | None = None) -> str:
    """The yt-dlp template Pinchflat makes of ``template``.

    Without ``item_values``, each per-download value Pinchflat adds becomes a
    ``%(__pinchflat_<name>)s`` field instead of its value for one download.
    """
    if item_values is None:
        item_values = {name: f"%({PSEUDO_FIELD_PREFIX}{name})s" for name in ITEM_VALUES}
    combined: dict[str, str | None] = {**CUSTOM_VALUES, **item_values}
    expanded = {
        name: _render(value, combined) if value is not None else None
        for name, value in combined.items()
    }
    return _render(template, expanded)
