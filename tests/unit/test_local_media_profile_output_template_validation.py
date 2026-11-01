from __future__ import annotations

import pytest
from pydantic import ValidationError


def _collection_profile_payload(output_template: str) -> dict[str, str]:
    return {
        "type": "collection",
        "name": "Jinja preamble",
        "outputTemplate": output_template,
        "preferredFormat": "format_audio_only",
    }


def test_output_template_allows_non_outputting_jinja_before_downloads() -> None:
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    output_template = (
        "{% set folder = collection_title ~ '-' ~ year %}"
        "/downloads/{{ folder }}/{{ episode_title }}.ext"
    )

    profile = CollectionLocalMediaProfileAPICreate.model_validate(
        _collection_profile_payload(output_template)
    )

    assert profile.output_template == output_template


def test_output_template_allows_captured_set_block_before_downloads() -> None:
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    output_template = (
        "{% set folder %}{{ collection_title }}{% endset %}"
        "/downloads/{{ folder }}/{{ episode_title }}.ext"
    )

    profile = CollectionLocalMediaProfileAPICreate.model_validate(
        _collection_profile_payload(output_template)
    )

    assert profile.output_template == output_template


def test_output_template_rejects_literal_text_before_downloads() -> None:
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    output_template = (
        "prefix{% set folder = collection_title %}"
        "/downloads/{{ folder }}/{{ episode_title }}.ext"
    )

    with pytest.raises(ValidationError, match="must start with '/downloads/'"):
        CollectionLocalMediaProfileAPICreate.model_validate(
            _collection_profile_payload(output_template)
        )


def test_output_template_rejects_conditional_text_before_downloads() -> None:
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    output_template = (
        "{% if year %}prefix{% endif %}"
        "/downloads/{{ collection_title }}/{{ episode_title }}.ext"
    )

    with pytest.raises(ValidationError, match="must start with '/downloads/'"):
        CollectionLocalMediaProfileAPICreate.model_validate(
            _collection_profile_payload(output_template)
        )


def test_output_template_still_has_to_end_with_ext_on_save() -> None:
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    output_template = (
        "/downloads/{{ collection_title }}/{{ episode_title }}.ext"
        "{% if year %}-{{ year }}{% endif %}"
    )

    with pytest.raises(ValidationError, match="must end with '.ext'"):
        CollectionLocalMediaProfileAPICreate.model_validate(
            _collection_profile_payload(output_template)
        )
