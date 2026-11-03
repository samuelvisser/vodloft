"""Your own yt-dlp options, checked one line at a time with yt-dlp's own parser.

A Local Media Profile and a Collection can each add yt-dlp options to the
downloads yt-dlp makes for them. Every line is read the way yt-dlp reads an
option file, then checked: options VODLoft has to control itself are blocked
with the reason, and options VODLoft already has a setting for point to that
setting. Only lines that pass are ever handed to yt-dlp, and VODLoft's own
options come after them, so they can never change where files go.
"""
from __future__ import annotations

import contextlib
import io
import optparse
import shlex
from dataclasses import dataclass
from typing import Literal

import yt_dlp
from yt_dlp.options import create_parser

LineStatus = Literal["valid", "blocked", "has_setting", "invalid"]
Setting = Literal["quality", "subtitles", "thumbnails", "metadata", "file_names", "sponsorblock", "which_episodes", "cookies"]

MAX_OPTIONS_LENGTH = 8000

# Options VODLoft must control itself, by yt-dlp's name for them.
_BLOCKED: dict[str, str] = {
    **dict.fromkeys(("outtmpl", "paths", "outtmpl_na_placeholder"),
                    "VODLoft decides where files go and what they are called with the output template"),
    **dict.fromkeys(("format", "format_sort", "format_sort_force"),
                    "VODLoft picks the format from the Quality setting, which a format choice here would bypass"),
    **dict.fromkeys(("exec_cmd", "exec_before_dl_cmd", "add_postprocessors", "plugin_dirs", "external_downloader",
                     "external_downloader_args", "postprocessor_args"),
                    "Runs other programs or plugins on the server"),
    **dict.fromkeys(("config_locations", "ignoreconfig", "batchfile", "load_info_filename", "_"),
                    "Reads more options or links from somewhere else"),
    **dict.fromkeys(("forceprint", "print_to_file", "progress_template", "progress_with_newline", "quiet", "noprogress",
                     "simulate", "skip_download", "dumpjson", "dump_single_json", "geturl", "gettitle", "getid",
                     "getthumbnail", "getdescription", "getduration", "getfilename", "getformat", "listformats",
                     "listsubtitles", "list_thumbnails", "verbose", "dump_intermediate_pages", "write_pages",
                     "print_traffic", "extract_flat", "no_color", "color", "consoletitle"),
                    "VODLoft follows the download through what yt-dlp prints, which this changes"),
    **dict.fromkeys(("noplaylist", "playlist_items", "playliststart", "playlistend", "playlist_reverse",
                     "playlist_random", "lazy_playlist", "download_archive", "break_on_existing", "break_per_url"),
                    "VODLoft downloads one video at a time and keeps track of what it downloaded itself"),
    **dict.fromkeys(("update_self",), "VODLoft keeps yt-dlp up to date itself"),
    **dict.fromkeys(("ffmpeg_location",), "VODLoft's download settings say where ffmpeg is"),
    **dict.fromkeys(("split_chapters",), "VODLoft keeps one file per video"),
    **dict.fromkeys(("usenetrc", "netrc_location", "netrc_cmd", "username", "password", "twofactor", "videopassword",
                     "ap_mso", "ap_username", "ap_password", "client_certificate", "client_certificate_key",
                     "client_certificate_password"),
                    "Sign-in details would be stored as plain text here"),
}

# Options VODLoft already has a setting for.
_HAS_SETTING: dict[str, Setting] = {
    **dict.fromkeys(("merge_output_format", "remuxvideo", "recodevideo", "extractaudio", "audioformat",
                     "prefer_free_formats", "allow_multiple_audio_streams", "allow_multiple_video_streams"), "quality"),
    **dict.fromkeys(("writesubtitles", "writeautomaticsub", "subtitleslangs", "embedsubtitles", "subtitlesformat",
                     "convertsubtitles", "allsubtitles"), "subtitles"),
    **dict.fromkeys(("writethumbnail", "embedthumbnail", "convertthumbnails", "write_all_thumbnails"), "thumbnails"),
    **dict.fromkeys(("addmetadata", "embed_infojson", "writeinfojson", "writedescription"), "metadata"),
    **dict.fromkeys(("restrictfilenames", "windowsfilenames", "trim_file_name"), "file_names"),
    **dict.fromkeys(("sponsorblock_mark", "sponsorblock_remove", "no_sponsorblock", "sponsorblock_chapter_title",
                     "sponsorblock_api"), "sponsorblock"),
    **dict.fromkeys(("match_filter", "breaking_match_filter", "dateafter", "datebefore", "date", "min_filesize",
                     "max_filesize", "min_views", "max_views", "age_limit"), "which_episodes"),
    **dict.fromkeys(("cookiefile", "cookiesfrombrowser", "no_cookies", "no_cookies_from_browser"), "cookies"),
}


@dataclass(frozen=True)
class OptionLine:
    """One line of options and what VODLoft makes of it."""

    line: int
    """The line number, from 1."""
    text: str
    status: LineStatus
    message: str = ""
    setting: Setting | None = None
    """For ``has_setting``, the VODLoft setting that does this."""


class OptionsRefused(ValueError):
    """At least one line can not be used; the message names the first."""


def _matched(tokens: list[str]) -> list[tuple[str, str]]:
    """Each option in ``tokens`` as (as written, yt-dlp's name), matched the way yt-dlp's parser matches it."""
    parser = create_parser()
    found: list[tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == "--":
            found.extend((rest, "url") for rest in tokens[index:])
            break
        if not token.startswith("-") or token == "-":
            found.append((token, "url"))
            continue
        if token.startswith("--"):
            name, equals, _rest = token.partition("=")
            try:
                name = parser._match_long_opt(name)
            except Exception:
                found.append((name, "unknown"))
                continue
            option = parser._long_opt[name]
            inline = bool(equals)
        else:
            name = token[:2]
            option = parser._short_opt.get(name)
            if option is None:
                found.append((name, "unknown"))
                continue
            inline = len(token) > 2
        if option.takes_value():
            index += (option.nargs or 1) - (1 if inline else 0)
        found.append((name, option.dest or name))
    return found


def _parse_error(tokens: list[str]) -> str | None:
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            yt_dlp.parse_options(["--ignore-config", *tokens])
    except SystemExit:
        return _last_error(stderr.getvalue())
    except optparse.OptParseError as exc:
        return _last_error(str(exc))
    except (ValueError, TypeError) as exc:
        return str(exc)
    return None


def _last_error(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    message = lines[-1] if lines else "yt-dlp does not accept this line"
    return message.split("error: ", 1)[-1].strip()


def _check_line(number: int, text: str) -> OptionLine | None:
    try:
        tokens = shlex.split(text, comments=True)
    except ValueError as exc:
        return OptionLine(number, text, "invalid", f"Can not be read: {exc}")
    if not tokens:
        return None
    options = _matched(tokens)
    for written, dest in options:
        if dest == "unknown":
            return OptionLine(number, text, "invalid", f"yt-dlp has no option {written}")
        if dest == "url":
            return OptionLine(number, text, "blocked", f"'{written}' is not an option; a web address here would be downloaded too")
    for written, dest in options:
        if dest in _BLOCKED:
            return OptionLine(number, text, "blocked", f"{written}: {_BLOCKED[dest]}")
    for written, dest in options:
        if dest in _HAS_SETTING:
            return OptionLine(number, text, "has_setting", f"{written}: VODLoft already has a setting for this", _HAS_SETTING[dest])
    error = _parse_error(tokens)
    if error is not None:
        return OptionLine(number, text, "invalid", error)
    return OptionLine(number, text, "valid")


def check_ytdlp_options(text: str) -> list[OptionLine]:
    """Every line with options in ``text``, checked. Blank lines and comments are left out."""
    checked = (_check_line(number, line) for number, line in enumerate(text.splitlines(), start=1))
    return [line for line in checked if line is not None]


def ytdlp_option_arguments(text: str) -> tuple[str, ...]:
    """The options in ``text`` as arguments for yt-dlp, refusing them when any line can not be used."""
    if len(text) > MAX_OPTIONS_LENGTH:
        raise OptionsRefused(f"Keep your own yt-dlp options under {MAX_OPTIONS_LENGTH} characters")
    arguments: list[str] = []
    for line in check_ytdlp_options(text):
        if line.status != "valid":
            raise OptionsRefused(f"Line {line.line}: {line.message}")
        arguments.extend(shlex.split(line.text, comments=True))
    return tuple(arguments)
