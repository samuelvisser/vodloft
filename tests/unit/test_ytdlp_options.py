"""Your own yt-dlp options: each line checked with yt-dlp's parser, the block list, and where they are used."""
from __future__ import annotations

import pytest

from sources.ytdlp_options import OptionsRefused, check_ytdlp_options, ytdlp_option_arguments


def _status(text: str):
    return [(line.line, line.status, line.setting) for line in check_ytdlp_options(text)]


def test_each_line_is_checked_on_its_own():
    text = "\n".join([
        "# notes are left out",
        "--concurrent-fragments 4",
        "",
        "-o '%(title)s.%(ext)s'",
        "--write-subs",
        "--retries lots",
        "--no-such-option",
        "https://example.com/video",
        "--exec 'echo hi'",
    ])
    assert _status(text) == [
        (2, "valid", None),
        (4, "blocked", None),
        (5, "has_setting", "subtitles"),
        (6, "invalid", None),
        (7, "invalid", None),
        (8, "blocked", None),
        (9, "blocked", None),
    ]


def test_a_blocked_option_says_why():
    [line] = check_ytdlp_options("-o '%(title)s.%(ext)s'")
    assert line.message == "-o: VODLoft decides where files go and what they are called with the output template"
    [line] = check_ytdlp_options("-f bestvideo")
    assert "Quality" in line.message
    [line] = check_ytdlp_options("--paths /tmp")
    assert line.status == "blocked"


def test_options_vodloft_has_a_setting_for_point_to_it():
    assert _status("--sponsorblock-remove sponsor\n--embed-thumbnail\n--cookies c.txt\n--remux-video mkv") == [
        (1, "has_setting", "sponsorblock"), (2, "has_setting", "thumbnails"),
        (3, "has_setting", "cookies"), (4, "has_setting", "quality"),
    ]


def test_a_shortened_long_option_is_matched_like_yt_dlp_does():
    # optparse takes an unambiguous prefix of a long option.
    assert _status("--restrict-file") == [(1, "has_setting", "file_names")]


def test_usable_options_become_arguments_in_order():
    assert ytdlp_option_arguments("-N 4  # faster\n\n--extractor-args 'youtube:player_client=web'") == (
        "-N", "4", "--extractor-args", "youtube:player_client=web",
    )


def test_options_with_a_line_that_can_not_be_used_are_refused():
    with pytest.raises(OptionsRefused, match="Line 2: -o"):
        ytdlp_option_arguments("-N 4\n-o x")


def test_the_ytdlp_source_refuses_a_blocked_option_with_its_reason():
    from pydantic import ValidationError

    from backend.api.models.source import YtdlpOptionsAPIUpdate

    assert YtdlpOptionsAPIUpdate.model_validate({"text": "-N 4\n"}).text == "-N 4"
    with pytest.raises(ValidationError, match="Line 1: -o: VODLoft decides where files go"):
        YtdlpOptionsAPIUpdate.model_validate({"text": "-o out.mp4"})


def test_the_check_endpoint_reports_each_line():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.sources import router as source_router_module

    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    client = TestClient(app)
    response = client.post("/api/sources/ytdlp-options/check", json={"text": "-N 4\n-P /tmp"})
    assert response.status_code == 200
    assert [(line["line"], line["status"]) for line in response.json()] == [(1, "valid"), (2, "blocked")]
