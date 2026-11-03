"""yt-dlp and Pinchflat output templates, converted to VODLoft templates.

The differential tests render each converted template with VODLoft and the
original with yt-dlp, from the same YouTube video, and expect the same path.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from yt_dlp import YoutubeDL

from backend.utils.output_template import (
    COLLECTION_OUTPUT_TEMPLATE_FIELDS,
    finalize_output_path,
    render_output_template,
    validate_output_template_fields,
    validate_output_template_path_requirements,
)
from config import get_settings
from config.settings.submodels import FilenameRestrictionMode
from importer.ytdlp_templates import (
    ConversionOptions,
    FieldValue,
    TemplateSyntaxError,
    convert_pinchflat,
    convert_ytdlp,
    expand,
    parse,
)

VIDEO = {
    "id": "dQw4w9WgXcQ",
    "display_id": "dQw4w9WgXcQ",
    "title": 'Rick: "Never" Gonna Give You Up?',
    "fulltitle": 'Rick: "Never" Gonna Give You Up?',
    "upload_date": "20240305",
    "timestamp": 1709650800,
    "uploader": "Rick Astley",
    "channel": "Rick Astley Channel",
    "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
    "playlist": "Greatest Hits",
    "playlist_title": "Greatest Hits",
    "playlist_id": "PL1234",
    "playlist_index": 3,
    "n_entries": 12,
    "__last_playlist_index": 12,
    "duration": 213,
    "ext": "mp4",
    "extractor": "youtube",
    "extractor_key": "Youtube",
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
}
# Ordinals, as the resolver hands them out: the first upload of the day, the first download.
INDEXES = {"playlist": 3, "day": 1, "autonumber": 1}


def _vodloft_values(video: dict) -> dict[str, object]:
    date = video["upload_date"]
    values = {field: "" for field in COLLECTION_OUTPUT_TEMPLATE_FIELDS}
    values.update({
        "title": video["title"],
        "episode_title": video["title"],
        "episode_site_id": video["id"],
        "episode_uploader": video.get("uploader") or "",
        "collection_author": video["channel"],
        "collection_title": video["playlist_title"],
        "collection_site_id": video["channel_id"],
        "duration_seconds": str(video["duration"]),
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "datetime": f"{date[:4]}-{date[4:6]}-{date[6:]} 15:00:00",
        "time": "15:00:00",
        "year": date[:4], "month": date[4:6], "day": date[6:],
        "hour": "15", "minute": "00", "second": "00",
    })
    return values


def _render_vodloft(template: str, video: dict, monkeypatch, tmp_path) -> str:
    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "download_root", tmp_path)
    monkeypatch.setattr(settings.download_settings, "filename_restriction_mode", FilenameRestrictionMode.WINDOWS)
    validate_output_template_fields(template, allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS)
    validate_output_template_path_requirements(template, allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS)
    rendered = render_output_template(
        template,
        _vodloft_values(video),
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        custom_index_resolver=lambda key, _group=(): INDEXES[key],
    )
    return finalize_output_path(rendered, video["ext"]).removeprefix("/downloads/")


def _render_ytdlp(template: str, video: dict) -> str:
    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        ydl._num_downloads = 1  # As for the first video of a run.
        return ydl.evaluate_outtmpl(template, dict(video), sanitize=True).lstrip("/")


SAME_PATH = [
    "%(title)s [%(id)s].%(ext)s",
    "%(title).20s [%(id)s].%(ext)s",
    "%(uploader)s/%(upload_date)s - %(title)s.%(ext)s",
    "%(upload_date>%Y)s/%(upload_date>%m-%d)s %(title)s.%(ext)s",
    "%(playlist_index)s - %(title)s.%(ext)s",
    "%(playlist_index)03d - %(title)s.%(ext)s",
    "%(artist,uploader|Unknown)s/%(title)s.%(ext)s",
    "%(series|No series)s/%(title)s.%(ext)s",
    "%(duration)d seconds/%(title)s.%(ext)s",
    "%(title&Titled|Untitled)s/%(id)s.%(ext)s",
    "%(title&[{}]|Untitled)s.%(ext)s",
    "100%% %(title)s.%(ext)s",
    "%(extractor)s/%(id)s.%(ext)s",
    "%(title)10.5s.%(ext)s",
    "%(autonumber)s %(title)s.%(ext)s",
]


@pytest.mark.parametrize("template", SAME_PATH)
def test_converted_template_names_files_as_yt_dlp(template, monkeypatch, tmp_path):
    report = convert_ytdlp(template)

    assert report.output_template is not None, report.lines()
    assert _render_vodloft(report.output_template, VIDEO, monkeypatch, tmp_path) == _render_ytdlp(template, VIDEO)


@pytest.mark.parametrize("template", [
    "/{{ source_custom_name }}/{{ upload_yyyy_mm_dd }} {{ title }}/{{ title }} [{{ id }}].{{ ext }}",
    "/shows/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}",
    "/{{ source_custom_name }}/{{ static_season__episode_by_index }} - {{ title }}.{{ ext }}",
    "/{{ source_custom_name }}/{{ static_season__episode_by_date }} - {{ title }}.{{ ext }}",
])
def test_converted_pinchflat_template_names_files_as_pinchflat(template, monkeypatch, tmp_path):
    item_values = {
        "media_item_id": "1", "source_id": "1", "media_profile_id": "1",
        "source_custom_name": VIDEO["playlist_title"], "source_collection_id": VIDEO["playlist_id"],
        "source_collection_name": VIDEO["playlist_title"], "source_collection_type": "playlist",
        "media_playlist_index": "03", "media_upload_date_index": "99",
    }
    report = convert_pinchflat(template)

    assert report.output_template is not None, report.lines()
    expected = _render_ytdlp(expand(template, item_values), VIDEO)
    assert _render_vodloft(report.output_template, VIDEO, monkeypatch, tmp_path) == expected


def test_pinchflat_expansion_matches_pinchflat():
    # Pinchflat's own OutputPathBuilder tests.
    assert expand("/videos/{{ title }}.{{ ext }}", {}) == "/videos/%(title)S.%(ext)S"
    assert expand("/videos/{{ upload_year }}.{{ ext }}", {}) == "/videos/%(upload_date>%Y)S.%(ext)S"
    assert expand("/videos/{{ custom }}.{{ ext }}", {"custom": "test"}) == "/videos/test.%(ext)S"
    assert expand("/videos/%(title)s.%(ext)s", {}) == "/videos/%(title)s.%(ext)s"
    assert expand("{{ season_episode_index_from_date }}.{{ ext }}", {"media_upload_date_index": "99"}) == (
        "s%(upload_date>%Y)Se%(upload_date>%m%d)S99.%(ext)S"
    )


def test_pinchflat_values_become_collection_values_and_custom_indexes():
    report = convert_pinchflat(
        "/shows/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }}.{{ ext }}"
    )

    assert report.output_template == (
        "/downloads/shows/{{ collection_title | as_typed }}/Season {{ year }}/s{{ year }}e{{ date | strftime('%m%d') }}"
        "{{ '%02d' | format('day' | custom_index(per=date, start=99, step=-1)) }} - {{ title }}.ext"
    )
    assert [(index.key, index.keep_numbers) for index in report.custom_indexes] == [("day", True)]
    assert report.support == "close"


def test_a_playlist_names_each_video_after_its_own_channel():
    template = "/Video/{{ channel }} - {{ title }}.{{ ext }}"

    assert convert_pinchflat(template, ConversionOptions(collection_type="channel")).output_template == (
        "/downloads/Video/{{ collection_author or 'NA' }} - {{ title }}.ext"
    )
    for options in (ConversionOptions(collection_type="playlist"), ConversionOptions(for_playlists=True)):
        assert convert_pinchflat(template, options).output_template == (
            "/downloads/Video/{{ episode_uploader or 'NA' }} - {{ title }}.ext"
        )


def test_volatile_and_format_fields_are_reported_not_converted():
    report = convert_ytdlp("%(title)s %(view_count)s %(height)sp.%(ext)s")

    assert report.output_template == "/downloads/{{ title }} NA NAp.ext"
    unsupported = {part.source: part.reason for part in report.parts if part.support == "unsupported"}
    assert "changes all the time" in unsupported["%(view_count)s"]
    assert "format of each download" in unsupported["%(height)s"]
    assert report.support == "unsupported"


def test_known_format_values_are_filled_in():
    report = convert_ytdlp("%(title)s %(height)sp.%(ext)s", ConversionOptions(format_values={"height": "1080"}))

    assert report.output_template == "/downloads/{{ title }} 1080p.ext"


def test_fields_an_option_file_makes_are_used():
    options = ConversionOptions(extra_fields={"plex_title": FieldValue("title | upper", always=True)})

    assert convert_ytdlp("[%(plex_title)S].%(ext)s", options).output_template == "/downloads/[{{ title | upper }}].ext"


def test_missing_extension_is_added_and_reported():
    report = convert_ytdlp("%(title)s")

    assert report.output_template == "/downloads/{{ title }}.ext"
    assert any(part.result == ".ext" and part.support == "close" for part in report.parts)


def test_literal_jinja_braces_stay_text():
    report = convert_ytdlp("{%(title)s} {{x}} {%%.%(ext)s")

    assert report.output_template is not None, report.lines()
    assert report.output_template.startswith("/downloads/{{ '{' }}{{ title }}}")


def test_invalid_templates_are_errors_not_templates():
    with pytest.raises(TemplateSyntaxError):
        parse("%(title")
    assert convert_ytdlp("%(title)").output_template is None
    assert convert_pinchflat("{{ title | upcase }}.{{ ext }}").output_template is None
    assert convert_ytdlp("%(view_count)s.%(ext)s").output_template == "/downloads/NA.ext"


def test_na_placeholder_option():
    report = convert_ytdlp("%(series)s - %(title)s.%(ext)s", ConversionOptions(na_placeholder=""))

    assert report.output_template == "/downloads/ - {{ title }}.ext"


def test_importer_does_not_depend_on_the_application():
    root = Path(__file__).resolve().parents[2] / "server" / "importer" / "src" / "importer"
    forbidden = ("backend", "controller", "task_manager", "downloader", "sources", "config")
    violations = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            )
            violations += [f"{path.name}: {name}" for name in names if name.split(".")[0] in forbidden]
    assert violations == []
