"""yt-dlp option files as Pinchflat passes them, and their effect on converted templates."""
from __future__ import annotations

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor.metadataparser import MetadataParserPP

from backend.utils.output_template import COLLECTION_OUTPUT_TEMPLATE_FIELDS
from importer.ytdlp_templates import (
    COMMAND_LINE,
    ConversionOptions,
    MetadataAction,
    OptionError,
    OptionFile,
    convert_pinchflat,
    convert_ytdlp,
    load_options,
    options_from,
    pinchflat_option_files,
)
from importer.ytdlp_templates.convert import VODLOFT_VARIABLES

from test_ytdlp_template_conversion import VIDEO, _render_vodloft

PINCHFLAT_ARGS = [
    "--no-progress", "--force-overwrites",
    "--parse-metadata", "%(upload_date>%Y-%m-%d)s:(?P<meta_date>.+)",
    "--write-subs", "--convert-subs", "srt",
    "-f", "bv*+ba/b",
    "-o", "/downloads/%(title)s.%(ext)s",
]
PLEX_TITLE = (
    '--parse-metadata "%(title)s:%(plex_title)s"\n'
    '--replace-in-metadata plex_title "\\[" "("\n'
    '--replace-in-metadata plex_title "\\]" ")"\n'
    '--replace-in-metadata plex_title "(?<=\\d)\\s*[xX]\\s*(?=\\d)" "-by-"\n'
)


def _render_ytdlp(template: str, video: dict, actions: tuple[MetadataAction, ...]) -> str:
    info = dict(video)
    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        parser = MetadataParserPP(ydl, [
            (MetadataParserPP.Actions.INTERPRET if action.kind == "interpret" else MetadataParserPP.Actions.REPLACE,
             *action.arguments)
            for action in actions
        ])
        parser.to_screen = lambda *args, **kwargs: None
        _files, info = parser.run(info)
        return ydl.evaluate_outtmpl(template, info, sanitize=True).lstrip("/")


def test_vodloft_variables_match_the_collection_template_variables():
    assert VODLOFT_VARIABLES == COLLECTION_OUTPUT_TEMPLATE_FIELDS


def test_pinchflat_passes_files_base_first_and_skips_missing_or_empty_ones(tmp_path):
    (tmp_path / "base-config.txt").write_text("-f worst\n")
    (tmp_path / "media-profile-3-config.txt").write_text("-f best\n")
    (tmp_path / "source-7-config.txt").write_text("")
    (tmp_path / "media-profile-4-config.txt").write_text("-f other\n")

    files = pinchflat_option_files(tmp_path, media_profile_id=3, source_id=7, media_item_id=9)

    assert [file.name for file in files] == ["base-config.txt", "media-profile-3-config.txt"]


def test_base_config_wins_over_the_media_profile_file_and_the_command_line_over_both():
    files = (
        OptionFile("base", "base-config.txt", "-f worst\n--restrict-filenames\n"),
        OptionFile("media_profile", "media-profile-3-config.txt", "-f best\n--no-restrict-filenames\n"),
    )

    option_set = load_options(files)
    assert option_set.effective("format") == "worst"
    assert option_set.effective("restrictfilenames") is True
    handling = {(report.option.origin, report.option.flag): report.handling for report in option_set.reports}
    assert handling[("media-profile-3-config.txt", "-f")] == "overridden"
    assert handling[("base-config.txt", "-f")] == "unsupported"

    assert load_options(files, ["-f", "bv*+ba/b"]).effective("format") == "bv*+ba/b"


def test_metadata_actions_run_in_yt_dlp_order_with_their_origin():
    files = (
        OptionFile("base", "base-config.txt", '--parse-metadata "title:%(a)s"\n'),
        OptionFile("media_profile", "media-profile-3-config.txt", '--parse-metadata "title:%(b)s"\n'),
    )

    actions = load_options(files, PINCHFLAT_ARGS).actions

    assert [(action.arguments[1], action.origin) for action in actions] == [
        ("%(b)s", "media-profile-3-config.txt"),
        ("%(a)s", "base-config.txt"),
        ("(?P<meta_date>.+)", COMMAND_LINE),
    ]


def test_every_written_option_has_a_handling_and_a_reason():
    files = (OptionFile("media_profile", "media-profile-3-config.txt",
                        "--sponsorblock-remove all\n--limit-rate 1M\n--embed-thumbnail\n--quiet\n--force-overwrites\n"
                        "--trim-filenames 100\n-o thumbnail:%(id)s.%(ext)s\n-o %(id)s.%(ext)s\n# a comment\n"),)

    option_set = load_options(files, PINCHFLAT_ARGS)
    reports = {(report.option.origin, report.option.source): report for report in option_set.reports}

    file = "media-profile-3-config.txt"
    assert reports[(file, "--sponsorblock-remove all")].handling == "unsupported"
    assert reports[(file, "--limit-rate 1M")].handling == "unsupported"
    assert reports[(file, "--embed-thumbnail")].handling == "converted"
    assert reports[(file, "--quiet")].handling == "not_needed"
    assert reports[(file, "--force-overwrites")].handling == "overridden"
    assert reports[(file, "--trim-filenames 100")].handling == "unsupported"
    assert reports[(file, "-o thumbnail:%(id)s.%(ext)s")].handling == "close"
    assert reports[(file, "-o %(id)s.%(ext)s")].handling == "overridden"
    assert reports[(COMMAND_LINE, "-f bv*+ba/b")].handling == "converted"
    assert reports[(COMMAND_LINE, "--parse-metadata %(upload_date>%Y-%m-%d)s:(?P<meta_date>.+)")].handling == "not_needed"
    assert all(report.reason for report in option_set.reports)
    assert option_set.profile_settings == {
        "filename_mode": "windows", "subtitle_mode": "sidecar", "thumbnail_mode": "embed", "metadata_mode": "no_metadata",
    }


@pytest.mark.parametrize("text, message", [
    ("--no-such-option\n", "no-such-option"),
    ("--config-locations other.txt\n", "loads more option files"),
    ('--parse-metadata "unclosed\n', "Unable to parse"),
])
def test_unreadable_option_files_are_errors(text, message):
    with pytest.raises(OptionError, match=message):
        load_options((OptionFile("base", "base-config.txt", text),))


def test_plex_title_option_file_converts_and_names_files_as_yt_dlp(monkeypatch, tmp_path):
    template = "/{{ source_custom_name }}/Season 01/{{ source_custom_name }} - {{ upload_yyyy_mm_dd }} - [%(plex_title)S].{{ ext }}"
    option_set = load_options((OptionFile("media_profile", "media-profile-3-config.txt", PLEX_TITLE),), PINCHFLAT_ARGS)

    report = convert_pinchflat(template, options_from(option_set))

    assert report.output_template is not None, report.lines()
    assert report.output_template.startswith(
        "{% set plex_title = title -%}\n"
        "{% set plex_title = plex_title | regex_replace('\\\\[', '(') -%}\n"
    )
    assert [action.support for action in report.actions] == ["exact"] * 5
    assert "doesn't use" in report.actions[-1].reason
    video = {**VIDEO, "title": "Building a 6x6 [Part 2]"}
    rendered = _render_vodloft(report.output_template, video, monkeypatch, tmp_path)
    assert rendered == "Greatest Hits/Season 01/Greatest Hits - 2024-03-05 - [Building a 6-by-6 (Part 2)].mp4"


ACTIONS = [
    (("interpret", ("title", r"(?P<title>.+?) \| .+")),),
    (("interpret", ("%(uploader)s - %(title)s", r"(?P<artist>.+?) - (?P<track>.+)")),),
    (("replace", ("title", r"\s+", "_")), ("replace", ("uploader", "Rick", "R"))),
    (("interpret", ("title", r"(?P<title>.+?)(?: \| (?P<series>.+))?$")),),
    (("replace", ("duration", "1", "9")),),
]


@pytest.mark.parametrize("actions", ACTIONS)
@pytest.mark.parametrize("title", ['Rick: "Never" Gonna Give You Up?', "Never Gonna | Rick Astley"])
def test_metadata_actions_name_files_as_yt_dlp(actions, title, monkeypatch, tmp_path):
    template = "%(uploader)s/%(series)s - %(artist,track|none)s - %(title)s %(duration)s.%(ext)s"
    metadata = tuple(MetadataAction(kind, arguments, "base-config.txt") for kind, arguments in actions)
    video = {**VIDEO, "title": title}

    report = convert_ytdlp(template, ConversionOptions(metadata_actions=metadata))

    assert report.output_template is not None, report.lines()
    expected = _render_ytdlp(template, video, metadata)
    rendered = _render_vodloft(report.output_template, video, monkeypatch, tmp_path)
    if report.support == "exact" or "series" not in report.output_template:
        assert rendered == expected
    else:
        # A group left out of the match: yt-dlp keeps the old value, VODLoft has none.
        assert any("leaves the field empty" in (part.reason or "") for part in report.actions)


def test_options_give_the_placeholder_and_autonumber_start():
    option_set = load_options((OptionFile("base", "base-config.txt", "--output-na-placeholder ? --autonumber-start 5\n"),))

    options = options_from(option_set)

    assert (options.na_placeholder, options.autonumber_start) == ("?", 5)
    assert convert_ytdlp("%(series)s %(autonumber)s.%(ext)s", options).output_template == (
        "/downloads/? {{ '%05d' | format('autonumber' | custom_index(start=5)) }}.ext"
    )
