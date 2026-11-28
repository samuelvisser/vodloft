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
    app.include_router(source_router_module.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post("/api/v1/sources/ytdlp-options/check", json={"text": "-N 4\n-P /tmp"})
    assert response.status_code == 200
    assert [(line["line"], line["status"]) for line in response.json()] == [(1, "valid"), (2, "blocked")]


def test_options_that_break_a_download_are_blocked():
    for option in ("--test", "--no-warnings", "--hls-split-discontinuity", "--ignore-no-formats-error",
                   "--download-sections '*0-60'", "-J"):
        [line] = check_ytdlp_options(option)
        assert line.status == "blocked", option


def test_more_options_point_to_their_setting():
    assert _status("--reject-title trailer\n--max-downloads 3\n--remove-chapters Intro\n--no-mtime\n-r 4M") == [
        (1, "has_setting", "which_episodes"),
        (2, "has_setting", "which_episodes"),
        (3, "has_setting", "chapters"),
        (4, "has_setting", "file_date"),
        (5, "has_setting", "download_speed"),
    ]


def test_network_and_site_options_reach_every_call():
    from sources.ytdlp_options import every_call_arguments

    text = "--proxy http://proxy:3128\n--concurrent-fragments 4\n--impersonate chrome\n" \
           "--extractor-args 'youtube:player_client=web'\n--embed-chapters"
    assert every_call_arguments(text) == (
        "--proxy", "http://proxy:3128", "--impersonate", "chrome", "--extractor-args", "youtube:player_client=web",
    )
    # Options that can't be used reach no call at all; saving them is refused.
    assert every_call_arguments("--proxy http://proxy:3128\n--exec 'echo hi'") == ()


def test_every_yt_dlp_started_in_the_block_gets_the_options_also_in_its_threads():
    from concurrent.futures import ThreadPoolExecutor

    from sources import ytdlp_runner
    from sources.ytdlp_options import call_options, keep_call_options

    assert "--proxy" not in ytdlp_runner.command()
    with call_options(("--proxy", "http://proxy:3128")):
        assert ytdlp_runner.command()[-2:] == ("--proxy", "http://proxy:3128")
        with ThreadPoolExecutor(max_workers=1, **keep_call_options()) as pool:
            assert pool.submit(ytdlp_runner.command).result()[-2:] == ("--proxy", "http://proxy:3128")
    assert "--proxy" not in ytdlp_runner.command()


def test_a_download_keeps_yt_dlps_warnings_and_lookups_leave_them_out():
    from sources import ytdlp_runner

    assert "--no-warnings" in ytdlp_runner.command()
    assert "--no-warnings" not in ytdlp_runner.command(warnings=True)


def test_a_lookup_uses_the_sources_and_the_collections_network_options(task_database):
    from backend.db.core import run_write_transaction
    from backend.db.models import Settings
    from backend.services.source_options import ytdlp_call_options
    from sources import ytdlp_runner

    def save(w):
        w.query(Settings).one().ytdlp_options = "--proxy http://proxy:3128\n--concurrent-fragments 4"

    run_write_transaction(save)
    with ytdlp_call_options("ytdlp", "--impersonate chrome"):
        assert ytdlp_runner.command()[-4:] == ("--proxy", "http://proxy:3128", "--impersonate", "chrome")
    # A Source without your own yt-dlp options gets none of them.
    with ytdlp_call_options("dailywire", "--impersonate chrome"):
        assert "--proxy" not in ytdlp_runner.command()
