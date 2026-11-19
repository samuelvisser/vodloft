import pytest

from backend.utils.metadata_template import render_metadata_template, validate_metadata_template


def test_a_metadata_template_renders_the_text_as_it_is():
    values = {"title": "Q&A: Is AI \"conscious\"? 1/2", "date": "2026-08-30", "description": "Line one\nLine two"}
    # Nothing is made safe for a file name, and a description keeps its lines.
    assert render_metadata_template("{{ date }} - {{ title }}", values) == '2026-08-30 - Q&A: Is AI "conscious"? 1/2'
    assert render_metadata_template("{{ description }}\n\nFrom VODLoft", values) == "Line one\nLine two\n\nFrom VODLoft"


def test_a_metadata_template_only_takes_the_episodes_variables():
    assert validate_metadata_template("{{ collection_title }}: {{ title }}") == "{{ collection_title }}: {{ title }}"
    with pytest.raises(ValueError, match="Unsupported"):
        validate_metadata_template("{{ movie_title }}")
    with pytest.raises(ValueError, match="custom_index"):
        validate_metadata_template("{{ 'day' | custom_index }}")
    with pytest.raises(ValueError):
        validate_metadata_template("{{ title ")


def test_the_profile_refuses_a_broken_title_template_under_its_field():
    from pydantic import ValidationError

    from backend.services.local_media_profile_inputs import CollectionLocalMediaProfileInput

    with pytest.raises(ValidationError) as caught:
        CollectionLocalMediaProfileInput(
            name="x", output_template="/downloads/{{ title }}.ext", preferred_format="format_1080p",
            episode_title_template="{{ nope }}",
        )
    assert caught.value.errors()[0]["loc"] == ("episode_title_template",)
    blank = CollectionLocalMediaProfileInput(
        name="x", output_template="/downloads/{{ title }}.ext", preferred_format="format_1080p", episode_title_template="  ",
    )
    assert blank.episode_title_template is None
