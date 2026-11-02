"""yt-dlp option files, read with yt-dlp's own parser as Pinchflat passes them.

Pinchflat hands its option files to yt-dlp with ``--config-locations``, after
its own options. yt-dlp then reads the files in reverse, so for an option set
in more than one place the command line wins, then ``base-config.txt``, then
the media profile's, the source's and the media item's file. Options that
add up, such as ``--parse-metadata``, are all used, in that same order.

Every option written in a file is listed with where it came from and whether
it is the one that counts, and each gets one sentence on what the import does
with it.
"""
from __future__ import annotations

import contextlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yt_dlp
from yt_dlp.options import create_parser
from yt_dlp.postprocessor.metadataparser import MetadataParserPP
from yt_dlp.utils import Config

Level = Literal["base", "media_profile", "source", "media_item"]
Handling = Literal["converted", "close", "not_needed", "unsupported", "overridden"]
COMMAND_LINE = "Pinchflat"
"""The origin of the options Pinchflat itself passes."""

_FILE_NAMES: dict[Level, str] = {
    "media_item": "media-item-{}-config.txt",
    "source": "source-{}-config.txt",
    "media_profile": "media-profile-{}-config.txt",
    "base": "base-config.txt",
}


class OptionError(ValueError):
    """yt-dlp refuses the options."""


@dataclass(frozen=True)
class OptionFile:
    level: Level
    name: str
    """The file's name, such as ``media-profile-3-config.txt``."""
    text: str


@dataclass(frozen=True)
class WrittenOption:
    """One option as written in a file or on Pinchflat's command line."""

    flag: str
    """The option as written, such as ``--restrict-filenames``."""
    values: tuple[str, ...]
    dest: str
    origin: str
    key: str | None = None
    """For options set per type, such as ``-o thumbnail:…``, the type."""

    @property
    def source(self) -> str:
        return " ".join((self.flag, *(_quote(value) for value in self.values)))


@dataclass(frozen=True)
class MetadataAction:
    """A ``--parse-metadata`` (interpret) or ``--replace-in-metadata`` (replace), for one field."""

    kind: Literal["interpret", "replace"]
    arguments: tuple[str, ...]
    """``(from, to)`` to interpret, ``(field, search, replace)`` to replace."""
    origin: str


@dataclass(frozen=True)
class OptionReport:
    option: WrittenOption
    handling: Handling
    reason: str


@dataclass(frozen=True)
class OptionSet:
    options: Mapping[str, object]
    """yt-dlp's parsed options (``parse_options(...).options``), as a mapping."""
    written: tuple[WrittenOption, ...]
    """Every option, strongest last, as yt-dlp applies them."""
    actions: tuple[MetadataAction, ...] = ()
    """The metadata actions that change the file name, in the order yt-dlp runs them."""
    reports: tuple[OptionReport, ...] = ()
    profile_settings: dict[str, str] = field(default_factory=dict)
    """Local Media Profile settings the options give, by setting name."""

    def effective(self, dest: str, default: object = None) -> object:
        return self.options.get(dest, default)


def pinchflat_option_files(
    directory: Path,
    *,
    media_profile_id: int,
    source_id: int | None = None,
    media_item_id: int | None = None,
) -> tuple[OptionFile, ...]:
    """Pinchflat's option files for one download, in the order Pinchflat passes them.

    Pinchflat skips files that are missing or empty, as here.
    """
    ids: dict[Level, int | None] = {
        "media_item": media_item_id, "source": source_id, "media_profile": media_profile_id, "base": 0,
    }
    found: list[OptionFile] = []
    for level, pattern in _FILE_NAMES.items():
        if ids[level] is None:
            continue
        path = directory / pattern.format(ids[level])
        if path.is_file() and path.stat().st_size > 0:
            # Pinchflat builds its list by putting each file in front.
            found.insert(0, OptionFile(level, path.name, _read(path)))
    return tuple(found)


def _read(path: Path) -> str:
    data = path.read_bytes()
    # yt-dlp's own detection: a BOM or a "# coding:" line, else UTF-8 here.
    from yt_dlp.utils import determine_file_encoding

    encoding, skip = determine_file_encoding(data[:512])
    return data[skip:].decode(encoding or "utf-8")


def _quote(value: str) -> str:
    return value if value and not any(char in value for char in " \"'\\#") else '"' + value.replace('"', '\\"') + '"'


def _split(text: str, name: str) -> list[str]:
    import shlex

    try:
        return shlex.split(text, comments=True)
    except ValueError as exc:
        raise OptionError(f'Unable to parse "{name}": {exc}') from exc


def _parse(args: Sequence[str]) -> yt_dlp.ParsedOptions:
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            return yt_dlp.parse_options(["--ignore-config", *args])
    except SystemExit as exc:
        message = stderr.getvalue().strip().splitlines()
        raise OptionError(message[-1] if message else f"yt-dlp refused the options ({exc.code})") from None
    except (ValueError, TypeError) as exc:
        raise OptionError(str(exc)) from exc


def _written(args: Sequence[str], origin: str) -> list[WrittenOption]:
    """Each option in ``args``, matched to yt-dlp's parser the way optparse matches it."""
    parser = create_parser()
    written: list[WrittenOption] = []
    index = 0
    while index < len(args):
        token = args[index]
        index += 1
        if token == "--" or not token.startswith("-") or token == "-":
            written.append(WrittenOption(token, (), "url", origin))
            continue
        inline: str | None = None
        if token.startswith("--"):
            name, equals, rest = token.partition("=")
            inline = rest if equals else None
            try:
                name = parser._match_long_opt(name)
            except Exception:
                raise OptionError(f"yt-dlp has no option {name} ({origin})") from None
            option = parser._long_opt[name]
        else:
            name = token[:2]
            option = parser._short_opt.get(name)
            if option is None:
                raise OptionError(f"yt-dlp has no option {name} ({origin})")
            inline = token[2:] or None
        values: tuple[str, ...] = ()
        if option.takes_value():
            count = option.nargs or 1
            taken = [inline] if inline is not None else []
            while len(taken) < count:
                if index >= len(args):
                    raise OptionError(f"{name} needs {count} value(s) ({origin})")
                taken.append(args[index])
                index += 1
            values = tuple(taken)
        key = None
        if option.dest in ("outtmpl", "paths") and values:
            prefix, colon, _rest = values[0].partition(":")
            key = prefix if colon and prefix.isidentifier() and prefix in _OUTPUT_TYPES else "default"
        written.append(WrittenOption(name, values, option.dest, origin, key))
    return written


_OUTPUT_TYPES = frozenset({
    "default", "chapter", "subtitle", "thumbnail", "description", "annotation", "infojson",
    "link", "pl_thumbnail", "pl_description", "pl_infojson", "pl_video", "home", "temp",
})
_ACCUMULATING = frozenset({"parse_metadata", "match_filter", "config_locations", "postprocessor_args", "add_postprocessors"})


def _actions(parsed: yt_dlp.ParsedOptions, origin: str) -> list[MetadataAction]:
    actions: list[MetadataAction] = []
    for function, *arguments in (parsed.options.parse_metadata or {}).get("pre_process", []):
        kind = "interpret" if function is MetadataParserPP.Actions.INTERPRET else "replace"
        actions.append(MetadataAction(kind, tuple(arguments), origin))
    return actions


def load_options(files: Sequence[OptionFile], command_line: Sequence[str] = ()) -> OptionSet:
    """The options yt-dlp ends up with for Pinchflat's command line and these files."""
    file_args = {file.name: _split(file.text, file.name) for file in files}
    # yt-dlp reads the files back to front, and the command line last.
    order = [*((file.name, file_args[file.name]) for file in reversed(files)), (COMMAND_LINE, list(command_line))]
    written = [option for origin, args in order for option in _written(args, origin)]
    if any(option.dest == "config_locations" for option in written if option.origin != COMMAND_LINE):
        raise OptionError("An option file that loads more option files is not supported")

    merged = _parse([arg for _origin, args in order for arg in args])
    actions = [action for origin, args in order for action in _actions(_parse(args), origin)]
    if [(a.kind, a.arguments) for a in actions] != [(a.kind, a.arguments) for a in _actions(merged, "")]:
        raise OptionError("yt-dlp's metadata actions do not add up from the files")

    option_set = OptionSet(dict(vars(merged.options)), tuple(written), tuple(actions))
    return classify(option_set)


# What each option becomes. "converted" options are used by the converter or
# the profile settings below; the sentence says how.
_CONVERTED: dict[str, str] = {
    "parse_metadata": "Becomes a line at the top of the template",
    "restrictfilenames": "VODLoft's Restricted filename mode",
    "windowsfilenames": "VODLoft's Windows filename mode",
    "outtmpl_na_placeholder": "Used for missing values in the template",
    "autonumber_start": "The Custom Index for autonumber starts there",
    "writesubtitles": "The profile's subtitle setting",
    "embedsubtitles": "The profile's subtitle setting",
    "convertsubtitles": "VODLoft saves subtitles as SRT",
    "writethumbnail": "The profile's thumbnail setting",
    "embedthumbnail": "The profile's thumbnail setting",
    "convertthumbnails": "VODLoft saves thumbnails as JPEG",
    "addmetadata": "The profile's metadata setting",
    "writeinfojson": "VODLoft keeps the video's information itself",
}
_NOT_NEEDED: dict[str, str] = {
    **dict.fromkeys(
        ("noprogress", "quiet", "verbose", "no_warnings", "newline", "consoletitle", "progress_template",
         "print_json", "forceprint", "simulate", "skip_download", "color"),
        "Only changes what yt-dlp prints",
    ),
    **dict.fromkeys(
        ("overwrites", "continue_dl", "nopart", "retries", "fragment_retries", "file_access_retries",
         "extractor_retries", "concurrent_fragment_downloads", "socket_timeout", "ignoreerrors",
         "cachedir", "updatetime", "buffersize", "http_chunk_size"),
        "VODLoft runs the download and its retries itself",
    ),
    "clean_infojson": "VODLoft keeps the video's information itself",
    "sleep_interval": "VODLoft paces its own requests",
    "max_sleep_interval": "VODLoft paces its own requests",
    "sleep_interval_requests": "VODLoft paces its own requests",
    "sleep_interval_subtitles": "VODLoft paces its own requests",
}
_UNSUPPORTED: dict[str, str] = {
    "trim_file_name": "VODLoft has no file name length setting yet",
    "format": "The profile's quality setting decides the format; VODLoft has no custom format strings",
    "format_sort": "The profile's quality setting decides the format; VODLoft has no custom format sorting",
    "merge_output_format": "Existing files keep their extension; new downloads follow VODLoft's container setting",
    "remuxvideo": "Existing files keep their extension; new downloads follow VODLoft's container setting",
    "recodevideo": "Existing files keep their extension; new downloads follow VODLoft's container setting",
    "subtitleslangs": "VODLoft downloads every language a video has; a language list is planned",
    "writeautomaticsub": "Auto-generated subtitles are planned",
    "match_filter": "VODLoft has no download filters yet",
    "sponsorblock_remove": "SponsorBlock is planned",
    "sponsorblock_mark": "SponsorBlock is planned",
    "ratelimit": "VODLoft has no download speed limit",
    "cookiefile": "Cookies are imported with the rest of the Pinchflat data, not from an option",
    "addchapters": "VODLoft does not embed chapters yet",
    "embed_infojson": "VODLoft does not embed the information file",
    "paths": "VODLoft decides where files go with the template and its download folder",
}


# Options Pinchflat passes for its own media profile settings, which the
# importer maps from those settings directly.
_FROM_PINCHFLAT_SETTINGS = {
    **dict.fromkeys(("format", "format_sort", "merge_output_format", "remuxvideo", "extractaudio", "audioformat"),
                    "Pinchflat's quality setting becomes the profile's quality"),
    **dict.fromkeys(("subtitleslangs", "writeautomaticsub"), "Pinchflat's subtitle setting, reported with the profile"),
    **dict.fromkeys(("sponsorblock_remove", "sponsorblock_mark"), "Pinchflat's SponsorBlock setting, reported with the profile"),
}
PINCHFLAT_META_DATE = ("%(upload_date>%Y-%m-%d)s:(?P<meta_date>.+)",)
"""The --parse-metadata Pinchflat always passes."""


def _report(option: WrittenOption, overridden_by: str | None) -> OptionReport:
    if overridden_by is not None:
        return OptionReport(option, "overridden", f"{overridden_by} sets this option too, and yt-dlp uses that one")
    dest = option.dest
    if option.origin == COMMAND_LINE and dest in _FROM_PINCHFLAT_SETTINGS:
        return OptionReport(option, "converted", _FROM_PINCHFLAT_SETTINGS[dest])
    if option.origin == COMMAND_LINE and option.values == PINCHFLAT_META_DATE:
        return OptionReport(option, "not_needed", "Pinchflat's date for media servers; VODLoft writes the date itself")
    if dest == "outtmpl":
        if option.key in (None, "default"):
            if option.origin == COMMAND_LINE:
                return OptionReport(option, "converted", "The output template, converted")
            return OptionReport(option, "overridden", "Pinchflat passes its own output template, which wins over option files")
        if option.key == "thumbnail":
            return OptionReport(option, "close", "VODLoft names the thumbnail after the video")
        return OptionReport(option, "unsupported", f"VODLoft names {option.key} files after the video")
    if dest == "url":
        return OptionReport(option, "unsupported", "A web address in an option file is not downloaded")
    if dest == "parse_metadata" and option.values and option.values[0].split(":", 1)[0] in (
        "post_process", "after_filter", "video", "before_dl", "after_move", "after_video", "playlist",
    ):
        return OptionReport(option, "unsupported", "Only metadata changes made before the download change the file name")
    if dest in _CONVERTED:
        return OptionReport(option, "converted", _CONVERTED[dest])
    if dest in _NOT_NEEDED:
        return OptionReport(option, "not_needed", _NOT_NEEDED[dest])
    if dest in _UNSUPPORTED:
        return OptionReport(option, "unsupported", _UNSUPPORTED[dest])
    return OptionReport(option, "unsupported", f"VODLoft has no equivalent of {option.flag}")


def _mode(written: bool, embedded: bool, *, none: str, embed: str, sidecar: str, both: str) -> str:
    if written and embedded:
        return both
    return sidecar if written else embed if embedded else none


def classify(option_set: OptionSet) -> OptionSet:
    """Add a report for each written option, and the profile settings the options give."""
    reports: list[OptionReport] = []
    written = option_set.written
    for index, option in enumerate(written):
        overridden_by = None
        if option.dest not in _ACCUMULATING:
            later = [other for other in written[index + 1:] if other.dest == option.dest and other.key == option.key]
            if later and option.dest != "url":
                overridden_by = later[-1].origin
        reports.append(_report(option, overridden_by))

    opts = option_set.options

    def written_flag(dest: str) -> bool:
        # yt-dlp turns writing on by itself to embed, and deletes the file after;
        # only a written --write-… keeps it next to the media.
        last = [option for option in written if option.dest == dest]
        return bool(last) and not last[-1].flag.startswith("--no-")

    settings = {
        "filename_mode": "restricted" if opts.get("restrictfilenames") else "windows",
        "subtitle_mode": _mode(
            written_flag("writesubtitles"), bool(opts.get("embedsubtitles")),
            none="no_subtitles", embed="embed", sidecar="sidecar", both="embed_and_sidecar",
        ),
        "thumbnail_mode": _mode(
            written_flag("writethumbnail"), bool(opts.get("embedthumbnail")),
            none="no_thumbnail", embed="embed", sidecar="sidecar", both="embed_and_sidecar",
        ),
        "metadata_mode": "embed" if opts.get("addmetadata") else "no_metadata",
    }
    return OptionSet(option_set.options, written, option_set.actions, tuple(reports), settings)
