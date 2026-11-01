from __future__ import annotations


def test_output_template_expression_spacing_is_canonicalized_on_profile_input() -> None:
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    profile = CollectionLocalMediaProfileAPICreate.model_validate({
        "type": "collection",
        "name": "Canonical spacing",
        "outputTemplate": "/downloads/{{collection_title}}/{{  episode_title  }}.ext",
        "preferredFormat": "format_audio_only",
    })

    assert profile.output_template == "/downloads/{{ collection_title }}/{{ episode_title }}.ext"


def test_output_template_spacing_normalizer_preserves_non_print_jinja() -> None:
    from backend.utils.output_template_formatting import normalize_output_template_expression_spacing

    template = (
        "{% set literal = '{{ untouched }}' %}"
        "{# {{ untouched }} #}"
        "{% raw %}{{ untouched }}{% endraw %}"
        "/downloads/{{collection_title}}/{{- episode_title -}}.ext"
    )

    assert normalize_output_template_expression_spacing(template) == (
        "{% set literal = '{{ untouched }}' %}"
        "{# {{ untouched }} #}"
        "{% raw %}{{ untouched }}{% endraw %}"
        "/downloads/{{ collection_title }}/{{- episode_title -}}.ext"
    )


def test_old_show_variables_point_to_their_collection_names():
    import pytest
    from backend.utils.output_template import validate_output_template_fields

    with pytest.raises(ValueError, match=r"\{\{ show_title \}\} is now \{\{ collection_title \}\}"):
        validate_output_template_fields(
            "/downloads/{{ show_title }}/{{ title }}.ext",
            allowed_fields=frozenset({"collection_title", "title"}),
        )
