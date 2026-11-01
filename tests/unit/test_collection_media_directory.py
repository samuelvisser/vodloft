from __future__ import annotations

import re

from jinja2.sandbox import SandboxedEnvironment
import pytest

from backend.utils.collection_media_directory import infer_collection_media_directory


def _resolve(template, *, values=None, seasons=(), sanitizer=lambda value: value):
    context = {
        "collection": "my-collection", "collection_title": "My Show", "season_number": "1",
        "season_name": "Introduction", "season_index": "1", "season_type": "normal",
        "episode": "first", "episode_title": "First", "title": "First",
        "episode_type": "ep", "year": "2026", "date": "2026-09-27",
        "meta_collection_folder": "Custom Collection",
    }
    context.update(values or {})
    environment = SandboxedEnvironment()
    environment.finalize = lambda value: "".join(
        character for character in str(value if value is not None else "").replace("/", "_").replace("\\", "_")
        if ord(character) >= 32
    )

    def no_index_assignment(_key):
        raise AssertionError("Root inference must not allocate or simulate an episode index")

    environment.filters["custom_index"] = no_index_assignment
    return infer_collection_media_directory(
        template, context, environment=environment,
        sanitize_component=sanitizer, season_names=seasons,
    )


@pytest.mark.parametrize(("template", "expected"), [
    ("/downloads/TV/{{ collection_title }}/Season {{ season_number }}/{{ title }}.ext", "/downloads/TV/My Show"),
    ("/downloads/Podcasts/{{ collection_title }}/{{ date }} - {{ title }}.ext", "/downloads/Podcasts/My Show"),
    ("/downloads/{{ collection }}/{{ year }}/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/{{ season_name }}/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/Season 01/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/S.01/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/Extras/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/audio/{{ title }}.ext", "/downloads/my-collection/audio"),
    ("/downloads/TV/My Show/Season 01/{{ title }}.ext", "/downloads/TV/My Show"),
    ("/downloads/{{ meta_collection_folder }}/{{ title }}.ext", "/downloads/Custom Collection"),
    ("{% set name = collection_title|lower %}/downloads/{{ name }}/{{ title }}.ext", "/downloads/my show"),
    ("{% set name %}{{ collection_title|upper }}{% endset %}/downloads/{{ name }}/{{ title }}.ext", "/downloads/MY SHOW"),
    ("{% macro folder(value) %}{{ value|upper }}{% endmacro %}/downloads/{{ folder(collection) }}/{{ title }}.ext", "/downloads/MY-COLLECTION"),
    ("{% with name = collection_title %}/downloads/{{ name }}/{{ title }}.ext{% endwith %}", "/downloads/My Show"),
    ("/downloads/{{ collection }}/{% if year %}{{ year }}/{% endif %}{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/{% if episode_type == 'aux' %}Extras/{% else %}Episodes/{% endif %}{{ title }}.ext", "/downloads/my-collection"),
    ("{% if episode_type == 'aux' %}{% set section = 'Extras' %}{% else %}{% set section = 'Episodes' %}{% endif %}/downloads/{{ collection }}/{{ section }}/{{ title }}.ext", "/downloads/my-collection"),
    ("{% set section = 'order'|custom_index %}/downloads/{{ collection }}/{{ section }}/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{{ collection }}/{{ 'order'|custom_index }}/{{ title }}.ext", "/downloads/my-collection"),
    ("/downloads/{% if meta_collection_folder %}{{ meta_collection_folder }}{% else %}{{ collection }}{% endif %}/{{ title }}.ext", "/downloads/Custom Collection"),
    ("{% if episode_type == 'aux' %}/downloads/Extras/{{ collection }}/{% else %}/downloads/Shows/{{ collection }}/{% endif %}{{ title }}.ext", None),
    ("/downloads/{{ year }}/{{ collection }}/{{ title }}.ext", None),
    ("/downloads/TV/{{ title }}.ext", None),
    ("/downloads/{{ title }}.ext", None),
    ("/downloads/{{ collection_title|random }}/{{ title }}.ext", None),
    ("/downloads/../{{ collection }}/{{ title }}.ext", None),
    ("/outside/{{ collection }}/{{ title }}.ext", None),
    ("{% include 'external.jinja' %}", None),
])
def test_semantic_collection_roots(template, expected):
    result = _resolve(template)
    assert result.path == expected
    assert bool(result.reason) is (expected is None)


def test_single_episode_does_not_make_a_season_or_date_the_collection_root():
    template = "/downloads/{{ collection }}/{{ season_number }}/{{ year }}/{{ title }}.ext"
    first = _resolve(template, values={"season_number": "1", "year": "2026"})
    future = _resolve(template, values={"season_number": "7", "year": "2032"})
    assert first.path == future.path == "/downloads/my-collection"


def test_known_literal_season_name_is_not_a_collection_directory():
    assert _resolve("/downloads/{{ collection }}/Introduction/{{ title }}.ext", seasons=("Introduction",)).path == "/downloads/my-collection"


def test_full_path_components_are_sanitized_after_jinja_filters():
    result = _resolve(
        "/downloads/{{ collection_title|replace(':', '-') }}/{{ title }}.ext",
        values={"collection_title": "Host: My Show?"},
        sanitizer=lambda value: re.sub(r'[<>:"/\\|?*]', "_", value),
    )
    assert result.path == "/downloads/Host- My Show_"


def test_collection_metadata_cannot_inject_path_structure_or_annotations():
    result = _resolve("/downloads/{{ collection_title }}/{{ title }}.ext", values={"collection_title": "My/Show\x01"})
    assert result.path == "/downloads/My_Show"


def test_custom_metadata_fallback_uses_real_collection_values():
    result = _resolve(
        "/downloads/{% if meta_collection_folder %}{{ meta_collection_folder }}{% else %}{{ collection }}{% endif %}/{{ title }}.ext",
        values={"meta_collection_folder": ""},
    )
    assert result.path == "/downloads/my-collection"


def test_many_variable_directories_keep_only_the_proven_collection_prefix():
    template = "/downloads/{{ collection }}/" + "{% if year %}a{% else %}b{% endif %}/" * 7 + "{{ title }}.ext"
    result = _resolve(template)
    assert result.path == "/downloads/my-collection"


def test_invalid_collection_expression_reports_reason_without_traceback():
    result = _resolve("/downloads/{{ collection }}/{{ 1 / 0 }}/{{ title }}.ext")
    assert result.path is None
    assert result.reason


def test_complex_filename_conditions_do_not_limit_a_clear_collection_root():
    filename = "{% if year %}a{% else %}b{% endif %}" * 12 + "{{ title }}.ext"
    assert _resolve("/downloads/{{ collection }}/" + filename).path == "/downloads/my-collection"


def test_filename_only_assignment_branches_are_not_evaluated():
    helpers = "{% if year %}{% set label = title %}{% else %}{% set label = episode %}{% endif %}" * 12
    assert _resolve(helpers + "/downloads/{{ collection }}/{{ label }}.ext").path == "/downloads/my-collection"


def test_repeated_collection_name_can_still_be_a_known_literal_season():
    assert _resolve("/downloads/{{ collection_title }}/My Show/{{ title }}.ext", seasons=("My Show",)).path == "/downloads/My Show"


def test_filename_trimming_does_not_confuse_equal_output_nodes():
    template = "/downloads/{{ collection }}/a/{% if year %}b{% else %}c{% endif %}/fixed/{{ title }}.ext"
    assert _resolve(template).path == "/downloads/my-collection/a"
