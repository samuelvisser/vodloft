from types import SimpleNamespace

from backend.utils.name_length import (
    MAX_NAME_BYTES, SIDECAR_RESERVE_BYTES, fit_name, note_filled_value, tracking_output_names,
)
from backend.utils.output_template import resolve_movie_output_path
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode


def _movie(title: str, author: str = "Author") -> SimpleNamespace:
    return SimpleNamespace(
        slug="movie", title=title, extended_title=None, duration=7200, author_name=author,
        mature_rating="PG", meta_items=[],
    )


def _resolve(tmp_path, monkeypatch, template: str, title: str, author: str = "Author") -> str:
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    path = resolve_movie_output_path(
        template, movie=_movie(title, author), extension="mp4", filename_mode=FilenameRestrictionMode.UNRESTRICTED,
    )
    return path.relative_to(tmp_path.resolve()).as_posix()


def _stem_limit() -> int:
    return MAX_NAME_BYTES - SIDECAR_RESERVE_BYTES


def test_a_name_that_fits_stays_the_same(tmp_path, monkeypatch):
    title = "x" * _stem_limit()
    assert _resolve(tmp_path, monkeypatch, "/downloads/{{ title }}.ext", title) == f"{title}.mp4"


def test_a_long_title_is_shortened_and_the_typed_text_kept(tmp_path, monkeypatch):
    title = "🎵" * 100  # 400 bytes
    relative = _resolve(tmp_path, monkeypatch, "/downloads/Show/{{ title }} [abc123].ext", title)
    folder, name = relative.split("/")
    assert folder == "Show"
    assert name.endswith(" [abc123].mp4")
    stem = name.removesuffix(".mp4")
    assert len(stem.encode()) <= _stem_limit()
    # Never cut inside a letter.
    assert set(stem.removesuffix(" [abc123]")) == {"🎵"}


def test_the_longest_value_is_shortened_first(tmp_path, monkeypatch):
    relative = _resolve(
        tmp_path, monkeypatch, "/downloads/{{ author }} - {{ title }}.ext", "t" * 300, author="Some Channel",
    )
    assert relative.startswith("Some Channel - ttt")
    assert len(relative.removesuffix(".mp4").encode()) == _stem_limit()


def test_a_long_folder_name_keeps_to_the_limit_itself(tmp_path, monkeypatch):
    relative = _resolve(tmp_path, monkeypatch, "/downloads/{{ title }}/movie.ext", "f" * 300)
    folder, name = relative.split("/")
    assert len(folder.encode()) == MAX_NAME_BYTES
    assert name == "movie.mp4"


def test_typed_text_alone_too_long_is_cut_at_the_end():
    assert fit_name("a" * 300) == "a" * MAX_NAME_BYTES
    with tracking_output_names() as names:
        assert fit_name("b" * 300 + ".mp4", extension="mp4") == "b" * _stem_limit() + ".mp4"
    assert names.shortened == ["b" * 300 + ".mp4"]


def test_a_shortened_value_does_not_end_in_a_space_or_dash():
    with tracking_output_names():
        value = "word " * 60
        note_filled_value(value)
        fitted = fit_name(f"{value}.mp4", extension="mp4")
    assert not fitted.removesuffix(".mp4").endswith((" ", "-"))
