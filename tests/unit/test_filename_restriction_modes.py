from types import SimpleNamespace

import pytest
from yt_dlp.utils import sanitize_filename

from backend.utils.filenames import clean_component, clean_value

from backend.utils.output_template import resolve_movie_output_path
from config import get_settings
from config.settings.settings import AppSettings
from config.settings.submodels import DownloadSettings, FilenameRestrictionMode


def _movie(title: str = "Amélie: Test?") -> SimpleNamespace:
    return SimpleNamespace(
        slug="movie",
        title=title,
        extended_title=None,
        duration=7200,
        author_name="François",
        mature_rating="PG",
        meta_items=[],
    )


def _resolve(tmp_path, monkeypatch, mode: FilenameRestrictionMode, title: str = "Amélie: Test?") -> str:
    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "download_root", tmp_path)
    monkeypatch.setattr(settings.download_settings, "filename_restriction_mode", mode)

    path = resolve_movie_output_path(
        "/downloads/Fïlms: Collection/{{ title }}.ext",
        movie=_movie(title),
        extension="mp4",
    )
    return path.relative_to(tmp_path.resolve()).as_posix()


def test_filename_restriction_mode_defaults_to_windows():
    defaults = AppSettings.model_fields["download_settings"].get_default(call_default_factory=True)
    assert defaults.filename_restriction_mode == FilenameRestrictionMode.WINDOWS
    assert "ascii_only_filenames" not in DownloadSettings.model_fields


def test_unrestricted_mode_preserves_unicode_and_non_path_punctuation(tmp_path, monkeypatch):
    relative = _resolve(tmp_path, monkeypatch, FilenameRestrictionMode.UNRESTRICTED)
    assert relative == "Fïlms: Collection/Amélie: Test?.mp4"


def test_unrestricted_mode_does_not_allow_metadata_to_create_path_levels(tmp_path, monkeypatch):
    relative = _resolve(tmp_path, monkeypatch, FilenameRestrictionMode.UNRESTRICTED, title="Part 1/Part 2")
    assert relative == "Fïlms: Collection/Part 1⧸Part 2.mp4"


def test_windows_mode_preserves_unicode_and_uses_look_alikes_for_windows_invalid_characters(tmp_path, monkeypatch):
    relative = _resolve(tmp_path, monkeypatch, FilenameRestrictionMode.WINDOWS)
    assert relative == "Fïlms： Collection/Amélie： Test？.mp4"


def test_windows_mode_protects_reserved_device_names(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "download_root", tmp_path)
    monkeypatch.setattr(
        settings.download_settings,
        "filename_restriction_mode",
        FilenameRestrictionMode.WINDOWS,
    )

    path = resolve_movie_output_path(
        "/downloads/{{ title }}.ext",
        movie=_movie("CON"),
        extension="mp4",
    )
    assert path.relative_to(tmp_path.resolve()).as_posix() == "_CON.mp4"


def test_restricted_mode_uses_conservative_ascii_names(tmp_path, monkeypatch):
    relative = _resolve(tmp_path, monkeypatch, FilenameRestrictionMode.RESTRICTED)
    # Typed text keeps its spaces, as in yt-dlp; the title, a value, is restricted.
    assert relative == "Films - Collection/Amelie_-_Test.mp4"
    assert relative.isascii()


def test_windows_reserved_name_is_only_changed_for_concrete_download_filename(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "download_root", tmp_path)
    monkeypatch.setattr(
        settings.download_settings,
        "filename_restriction_mode",
        FilenameRestrictionMode.WINDOWS,
    )

    provisional = resolve_movie_output_path(
        "/downloads/{{ title }}.ext",
        movie=_movie("AUX"),
    )
    concrete = resolve_movie_output_path(
        "/downloads/{{ title }}.ext",
        movie=_movie("AUX"),
        extension="mp4",
    )

    assert provisional.relative_to(tmp_path.resolve()).as_posix() == "AUX.ext"
    assert concrete.relative_to(tmp_path.resolve()).as_posix() == "_AUX.mp4"


def test_windows_reserved_word_inside_filename_is_not_rewritten(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "download_root", tmp_path)
    monkeypatch.setattr(
        settings.download_settings,
        "filename_restriction_mode",
        FilenameRestrictionMode.WINDOWS,
    )

    path = resolve_movie_output_path(
        "/downloads/Episode - {{ title }}.ext",
        movie=_movie("AUX"),
        extension="mp4",
    )

    assert path.relative_to(tmp_path.resolve()).as_posix() == "Episode - AUX.mp4"


# Titles with every character the modes treat differently, compared with yt-dlp itself.
_YT_DLP_TITLES = [
    'Q&A: Is AI "conscious"? | Ep. 12/13',
    "Live at 10:30: the news",
    "Back\\slash <and> *stars*",
    "Amélie: Test?",
    "__init__ --flags..",
    "Ep 1 / 2 * 3",
]


@pytest.mark.parametrize("title", _YT_DLP_TITLES)
def test_windows_values_match_yt_dlp(title):
    assert clean_value(title, FilenameRestrictionMode.WINDOWS) == sanitize_filename(title)


@pytest.mark.parametrize("title", _YT_DLP_TITLES)
def test_restricted_values_match_yt_dlp(title):
    assert clean_value(title, FilenameRestrictionMode.RESTRICTED) == sanitize_filename(title, restricted=True)


def test_unrestricted_values_only_change_slashes_and_control_characters():
    assert clean_value('Q&A: "x"? | a/b\\c\nd', FilenameRestrictionMode.UNRESTRICTED) == 'Q&A: "x"? | a⧸b\\cd'


def test_restricted_transliterates_letters_yt_dlp_drops():
    assert clean_value("ß Æ Łódź — “quote”… 2×3", FilenameRestrictionMode.RESTRICTED) == "ss_AE_Lodz_-_quote..._2x3"


def test_typed_template_text_follows_the_mode():
    assert clean_component("Season 1: Specials", FilenameRestrictionMode.WINDOWS) == "Season 1： Specials"
    assert clean_component("Season 1: Specials", FilenameRestrictionMode.RESTRICTED) == "Season 1 - Specials"
    assert clean_component("Séason 01 [x] * y", FilenameRestrictionMode.RESTRICTED) == "Season 01 [x] _ y"
    assert clean_component("Season 1: Specials", FilenameRestrictionMode.UNRESTRICTED) == "Season 1: Specials"


def test_restricted_name_with_nothing_ascii_left_is_no_ascii_file_name(tmp_path, monkeypatch):
    relative = _resolve(tmp_path, monkeypatch, FilenameRestrictionMode.RESTRICTED, title="東京物語")
    assert relative == "Films - Collection/no_ascii_file_name.mp4"
    assert clean_component("東京物語", FilenameRestrictionMode.RESTRICTED) == "no_ascii_file_name"


def test_second_no_ascii_file_in_a_folder_is_numbered_and_keeps_its_number(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import backend.db.models  # noqa: F401
    from backend.db import Base
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.no_ascii_names import settle_no_ascii_name

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = EpisodeMediaDownload(type="episode", media_item_id=1, local_media_profile_id=1,
                                     artifact_status="absent", file_path=str(tmp_path / "no_ascii_file_name.mp4"))
        second = EpisodeMediaDownload(type="episode", media_item_id=2, local_media_profile_id=1,
                                      artifact_status="absent", file_path=str(tmp_path / "x.ext"))
        session.add_all([first, second])
        session.flush()

        destination = tmp_path / "no_ascii_file_name.mp4"
        assert settle_no_ascii_name(first, destination) == destination
        numbered = settle_no_ascii_name(second, destination)
        assert numbered == tmp_path / "no_ascii_file_name_2.mp4"

        second.file_path = str(numbered)
        session.flush()
        assert settle_no_ascii_name(second, destination) == numbered
        assert settle_no_ascii_name(second, tmp_path / "Plain.mp4") == tmp_path / "Plain.mp4"
    engine.dispose()


@pytest.mark.parametrize(("mode", "expected"), [
    (FilenameRestrictionMode.UNRESTRICTED, []),
    (FilenameRestrictionMode.WINDOWS, [":", "?"]),
    (FilenameRestrictionMode.RESTRICTED, [":", "?"]),
])
def test_editor_is_told_which_typed_characters_the_mode_replaces(mode, expected):
    from backend.utils.output_template import typed_characters_the_mode_replaces

    template = "/downloads/Season {{ year }}: Specials?/{{ title | replace(':', '') }}.ext"
    assert typed_characters_the_mode_replaces(template, mode) == expected


def test_restricted_mode_names_a_converted_pinchflat_template_like_pinchflat(tmp_path, monkeypatch):
    """Pinchflat's restrict_filenames, like yt-dlp's, restricts the values and leaves typed text alone."""
    relative = _resolve(tmp_path, monkeypatch, FilenameRestrictionMode.RESTRICTED, title="Is AI conscious? Ep. 12")
    assert relative == "Films - Collection/Is_AI_conscious_Ep._12.mp4"
    assert clean_component("Mike_Winger - 2025-06-26 - Bethel_Insider.mp4", FilenameRestrictionMode.RESTRICTED,
                           extension="mp4") == "Mike_Winger - 2025-06-26 - Bethel_Insider.mp4"


def test_as_typed_names_a_value_like_typed_text(tmp_path, monkeypatch):
    from backend.utils.output_template import (
        COLLECTION_OUTPUT_TEMPLATE_FIELDS, prepare_output_template, rendering_with_filename_mode,
    )

    prepared = prepare_output_template(
        "/downloads/{{ collection_title | as_typed }}/{{ collection_title }} - {{ title }}.ext",
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
    )
    with rendering_with_filename_mode(FilenameRestrictionMode.RESTRICTED):
        rendered = prepared.render({"collection_title": "Mike Winger/Q&A", "title": "Is AI conscious?"})
    # It still can't add a folder level.
    assert rendered == "/downloads/Mike Winger⧸Q&A/Mike_Winger_Q_A - Is_AI_conscious.ext"
