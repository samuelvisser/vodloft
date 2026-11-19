"""ytdl-sub's ``{variable}`` templates, expanded into yt-dlp templates for the yt-dlp converter.

ytdl-sub names its values with ``{name}``: an override that the configuration defines, or one of
ytdl-sub's own entry variables, each with a ``_sanitized`` twin that is safe in a file name.
Overrides are expanded where they are used, as ytdl-sub does. Each entry variable becomes the
yt-dlp field it stands for, so the converter does the rest; a number VODLoft keeps its own way,
such as ``upload_date_index``, becomes a field the converter is told about.

ytdl-sub's scripting functions, such as ``%regex_sub`` or ``%if``, are a language of their own.
Each one becomes a field the converter can't fill, so the report lists it, under the text it was
written as, as not converted.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from yt_dlp.utils import sanitize_filename

from .convert import ConversionOptions, FieldValue, convert_ytdlp
from .report import ConversionReport

PSEUDO_FIELD_PREFIX = "__ytdlsub_"
_UNCONVERTED = f"{PSEUDO_FIELD_PREFIX}unconverted_"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SANITIZED = "_sanitized"
_INDEX_REASON = "Imported numbers are kept; new videos continue from the highest"

# ytdl-sub's entry variables as yt-dlp fields: (field, strftime format). Dates are upload dates
# unless the name says release.
_DATES = {
    "date": "%Y%m%d", "year": "%Y", "year_truncated": "%y", "month": "%-m", "month_padded": "%m",
    "day": "%-d", "day_padded": "%d", "day_of_year": "%-j", "day_of_year_padded": "%j",
    "date_standardized": "%Y-%m-%d",
}
ENTRY_VARIABLES: dict[str, tuple[str, str | None]] = {
    **{f"upload_{name}": ("upload_date", strftime) for name, strftime in _DATES.items()},
    **{f"release_{name}": ("release_date", strftime) for name, strftime in _DATES.items()},
    "upload_date": ("upload_date", None),
    "release_date": ("release_date", None),
    "title": ("title", None),
    "uid": ("id", None),
    "duration": ("duration", None),
    "channel": ("channel", None),
    "channel_id": ("channel_id", None),
    "uploader": ("uploader", None),
    "creator": ("creator", None),
    "extractor": ("extractor", None),
    "extractor_key": ("extractor_key", None),
    "ie_key": ("extractor_key", None),
    "playlist_title": ("playlist_title", None),
    "playlist_uid": ("playlist_id", None),
    "playlist_index": ("playlist_index", None),
    "playlist_index_padded": ("playlist_index", None),
    "source_title": ("channel", None),
    "source_uid": ("channel_id", None),
    "height": ("height", None),
    "width": ("width", None),
    "epoch": ("epoch", None),
    "ext": ("ext", None),
    "description": ("description", None),
    "webpage_url": ("webpage_url", None),
    "uploader_id": ("uploader_id", None),
    # ytdl-sub's own numbers, kept as VODLoft's Custom Indexes.
    "upload_date_index": (f"{PSEUDO_FIELD_PREFIX}upload_date_index", None),
    "upload_date_index_padded": (f"{PSEUDO_FIELD_PREFIX}upload_date_index_padded", None),
    "download_index": (f"{PSEUDO_FIELD_PREFIX}download_index", None),
    "download_index_padded6": (f"{PSEUDO_FIELD_PREFIX}download_index_padded6", None),
    "playlist_index_padded6": (f"{PSEUDO_FIELD_PREFIX}playlist_index_padded6", None),
    "subscription_name": (f"{PSEUDO_FIELD_PREFIX}subscription_name", None),
    # A Music profile's own values for the artist, the album (the episode's season) and the track.
    "music_artist": (f"{PSEUDO_FIELD_PREFIX}music_artist", None),
    "music_album": (f"{PSEUDO_FIELD_PREFIX}music_album", None),
    "music_track_number": (f"{PSEUDO_FIELD_PREFIX}music_track_number", None),
    "music_track_number_padded": (f"{PSEUDO_FIELD_PREFIX}music_track_number_padded", None),
    # A TV Show Collection's season, numbered as ytdl-sub numbers it: the import keeps each link's number.
    "collection_season_number": (f"{PSEUDO_FIELD_PREFIX}season_number", None),
    "collection_season_number_padded": (f"{PSEUDO_FIELD_PREFIX}season_number_padded", None),
    # Plex's variants swap digits for full-width ones, so Plex doesn't read "4x4" as an episode number.
    "title_sanitized_plex": (f"{PSEUDO_FIELD_PREFIX}title_plex", None),
    "uid_sanitized_plex": (f"{PSEUDO_FIELD_PREFIX}uid_plex", None),
}

YTDL_SUB_FIELDS: dict[str, FieldValue] = {
    f"{PSEUDO_FIELD_PREFIX}upload_date_index": FieldValue(
        "'day' | custom_index(per=date)", "index", always=True, support="close", reason=_INDEX_REASON,
    ),
    f"{PSEUDO_FIELD_PREFIX}upload_date_index_padded": FieldValue(
        "'%02d' | format('day' | custom_index(per=date))", always=True, support="close", reason=_INDEX_REASON,
    ),
    f"{PSEUDO_FIELD_PREFIX}download_index": FieldValue(
        "'autonumber' | custom_index", "index", always=True, support="close", reason=_INDEX_REASON,
    ),
    f"{PSEUDO_FIELD_PREFIX}download_index_padded6": FieldValue(
        "'%06d' | format('autonumber' | custom_index)", always=True, support="close", reason=_INDEX_REASON,
    ),
    f"{PSEUDO_FIELD_PREFIX}playlist_index_padded6": FieldValue(
        "'%06d' | format('playlist' | custom_index)", always=True, support="close", reason=_INDEX_REASON,
    ),
    f"{PSEUDO_FIELD_PREFIX}music_artist": FieldValue("artist", always=True),
    f"{PSEUDO_FIELD_PREFIX}music_album": FieldValue("album", always=True),
    f"{PSEUDO_FIELD_PREFIX}music_track_number": FieldValue("track_number", always=True),
    f"{PSEUDO_FIELD_PREFIX}music_track_number_padded": FieldValue("track_number_padded", always=True),
    f"{PSEUDO_FIELD_PREFIX}season_number": FieldValue("season_number", always=True),
    f"{PSEUDO_FIELD_PREFIX}season_number_padded": FieldValue("'%02d' | format(season_number | int)", always=True),
    # The import names each Collection after its subscription.
    f"{PSEUDO_FIELD_PREFIX}subscription_name": FieldValue("collection_title", always=True),
    f"{PSEUDO_FIELD_PREFIX}title_plex": FieldValue(
        "title", always=True, support="close",
        reason="VODLoft keeps the digits; the Plex preset of the template editor has its own rule for numbers in titles",
    ),
    f"{PSEUDO_FIELD_PREFIX}uid_plex": FieldValue(
        "episode_site_id", always=True, support="close", reason="VODLoft keeps the digits of the video id",
    ),
}
"""What the converter fills the fields of ytdl-sub's own values with."""


@dataclass(frozen=True)
class Expansion:
    template: str
    """The yt-dlp template."""
    aliases: dict[str, str] = field(default_factory=dict)
    """Each yt-dlp field of the template, and the ytdl-sub variable it was written as."""
    unconverted: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Each field that stands for a part that can't be converted: (the part as written, why)."""


class _Unresolved(Exception):
    pass


def _parts(text: str) -> list[tuple[bool, str]]:
    """``text`` as (is a {…} part, its text) pieces. A brace part may hold nested braces."""
    pieces: list[tuple[bool, str]] = []
    position = 0
    while position < len(text):
        start = text.find("{", position)
        if start < 0:
            pieces.append((False, text[position:]))
            break
        if start > position:
            pieces.append((False, text[position:start]))
        depth, end = 0, start
        while end < len(text):
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            if depth == 0:
                break
            end += 1
        if depth:
            pieces.append((False, text[start:]))
            break
        pieces.append((True, text[start + 1:end]))
        position = end + 1
    return pieces


class _Expander:
    def __init__(self, overrides: Mapping[str, object], computed: Mapping[str, str],
                 leaf: Callable[[str, bool, str], str], text: Callable[[str, bool], str]) -> None:
        self.overrides = overrides
        self.computed = computed
        self.leaf = leaf
        self.text = text

    def expand(self, value: object, sanitize: bool, seen: tuple[str, ...] = ()) -> str:
        if isinstance(value, bool):
            value = str(value)
        out: list[str] = []
        for is_variable, piece in _parts(str(value)):
            if not is_variable:
                out.append(self.text(piece, sanitize))
                continue
            name = piece.strip()
            if not _NAME.fullmatch(name):
                out.append(self.leaf("{" + piece + "}", sanitize, "{" + piece + "}"))
                continue
            out.append(self.variable(name, sanitize, seen, name))
        return "".join(out)

    def variable(self, name: str, sanitize: bool, seen: tuple[str, ...], written: str) -> str:
        if name in seen:
            raise _Unresolved(f"{name} refers to itself")
        if name in self.overrides:
            return self.expand(self.overrides[name], sanitize, (*seen, name))
        if name in self.computed:
            return self.expand(self.computed[name], sanitize, (*seen, name))
        if name in ENTRY_VARIABLES:
            return self.leaf(name, sanitize, "{" + written + "}")
        if name.endswith(_SANITIZED):
            base = name[:-len(_SANITIZED)]
            if base in self.overrides or base in self.computed or base in ENTRY_VARIABLES:
                return self.variable(base, True, seen, written)
        return self.leaf("{" + name + "}", sanitize, "{" + written + "}")


def expand(template: str, overrides: Mapping[str, object], computed: Mapping[str, str] | None = None) -> Expansion:
    """The yt-dlp template ytdl-sub's ``template`` stands for, with ``overrides`` and the values a preset computes.

    ``computed`` holds variables that ytdl-sub's own presets compute with scripts, written as ytdl-sub
    templates of entry variables, such as ``{upload_year}`` for a season numbered by year.
    """
    aliases: dict[str, str] = {}
    unconverted: dict[str, tuple[str, str]] = {}

    def leaf(name: str, sanitize: bool, written: str) -> str:
        if name in ENTRY_VARIABLES:
            field_name, strftime = ENTRY_VARIABLES[name]
            if name.endswith("_plex"):
                sanitize = True
            source = f"%({field_name}{'>' + strftime if strftime else ''}){'S' if sanitize else 's'}"
            aliases.setdefault(source, written)
            return source
        # A script or a name ytdl-sub doesn't know: a field the converter reports as not converted.
        reason = ("ytdl-sub's scripting functions are a language of their own" if name.lstrip("{").lstrip().startswith("%")
                  else f"VODLoft has no value like {name}")
        key = next((pseudo for pseudo, (written, _why) in unconverted.items() if written == name), None)
        if key is None:
            key = f"{_UNCONVERTED}{len(unconverted) + 1}"
            unconverted[key] = (name, reason)
        source = f"%({key})s"
        aliases.setdefault(source, written)
        return source

    def text(piece: str, sanitize: bool) -> str:
        return (sanitize_filename(piece) if sanitize else piece).replace("%", "%%")

    expanded = _Expander(overrides, computed or {}, leaf, text).expand(template, False)
    return Expansion(expanded, aliases, unconverted)


def render(template: str, overrides: Mapping[str, object], values: Mapping[str, str]) -> str | None:
    """``template`` filled in with ``values`` for its entry variables, as ytdl-sub does; None when it needs
    a value that is only known per video, or a script."""

    def leaf(name: str, sanitize: bool, _written: str) -> str:
        if name not in values:
            raise _Unresolved(name)
        return sanitize_filename(values[name]) if sanitize else values[name]

    try:
        return _Expander(overrides, {}, leaf, lambda piece, sanitize: sanitize_filename(piece) if sanitize else piece) \
            .expand(template, False)
    except _Unresolved:
        return None


def convert_ytdl_sub(expansion: Expansion, original: str, options: ConversionOptions | None = None) -> ConversionReport:
    """Convert an expanded ytdl-sub file path, relative to the download folder, as a yt-dlp template is converted.

    Each part of the report is named as ytdl-sub wrote it: ``{title_sanitized}``, not the field it stands for.
    """
    options = options or ConversionOptions(na_placeholder="")
    options = replace(options, extra_fields={**YTDL_SUB_FIELDS, **options.extra_fields})
    report = convert_ytdlp(expansion.template, options, original=original)
    parts = []
    for part in report.parts:
        source = part.source
        key = source[2:-2] if source.startswith("%(") and source.endswith(")s") else None
        if key in expansion.unconverted:
            written, why = expansion.unconverted[key]
            part = replace(part, source=written, reason=f"{why}, so the import leaves it out")
        elif source.startswith(".") and source[1:] in expansion.aliases:
            part = replace(part, source="." + expansion.aliases[source[1:]])
        else:
            part = replace(part, source=expansion.aliases.get(source, source))
        if part.source == "/" and not part.result:
            part = replace(part, support="exact", reason="ytdl-sub's folder becomes VODLoft's folder for it")
        parts.append(part)
    return replace(report, parts=tuple(parts))
