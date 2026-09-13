import pytest

from backend.services.templates import ensure_unique_output_template, preview_output_template, validate_output_template


def test_output_template_must_stay_under_downloads() -> None:
    with pytest.raises(ValueError, match="start with /downloads/"):
        validate_output_template("/tmp/%(title)s.%(ext)s")
    with pytest.raises(ValueError, match="traverse"):
        validate_output_template("/downloads/channel/../escape/%(title)s.%(ext)s")


def test_output_template_requires_extension_placeholder() -> None:
    with pytest.raises(ValueError, match="ext"):
        validate_output_template("/downloads/%(title)s.mkv")


def test_duplicate_safe_template_adds_video_id_once() -> None:
    template = "/downloads/%(uploader)s/%(title)s.%(ext)s"
    normalized = ensure_unique_output_template(template)
    assert normalized == "/downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s"
    assert ensure_unique_output_template(normalized) == normalized


def test_output_template_preview_uses_normalized_template() -> None:
    preview = preview_output_template("/downloads/%(uploader)s/%(title)s.%(ext)s")
    assert preview == "/downloads/Example Channel/Example Video [dQw4w9WgXcQ].mkv"
