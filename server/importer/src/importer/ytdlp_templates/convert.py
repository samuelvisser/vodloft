"""yt-dlp and Pinchflat output templates as VODLoft Jinja templates.

Each yt-dlp field becomes a Jinja expression tree, printed with the shared
expression printer and checked by parsing the result again. Every part of the
template gets a report entry saying whether it converted exactly, closely
(and why), or not at all (and what the conversion did instead). Nothing is
dropped without saying so.

The converted template follows VODLoft's rules: it starts with
``/downloads/`` and ends with ``.ext``, and it uses only Collection template
variables. The values it relies on are those of a YouTube video.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from jinja2 import Environment, TemplateSyntaxError as JinjaSyntaxError, nodes
from jinja_analysis import UnsafeEdit, expression_source

from ..contract import CustomIndexPlan, Support
from .grammar import Candidate, Field, Template, TemplateSyntaxError, Text, parse
from .pinchflat import PSEUDO_FIELD_PREFIX, expand
from .report import ConversionReport, ReportBuilder

ValueType = Literal["str", "int", "index", "date", "datetime"]
_ORDER = {"exact": 0, "close": 1, "unsupported": 2}
_ENVIRONMENT = Environment()


@dataclass(frozen=True)
class ConversionOptions:
    na_placeholder: str = "NA"
    """yt-dlp's ``--output-na-placeholder``: what a missing value becomes. "" leaves it out."""
    autonumber_start: int = 1
    playlist_index_width: int = 2
    """How many digits ``%(playlist_index)s`` gets; yt-dlp uses the length of the playlist's size."""
    format_values: Mapping[str, str] = field(default_factory=dict)
    """Values of format fields such as ``height`` for the format VODLoft will request."""
    collection_type: str | None = None
    """Pinchflat's source collection type, such as ``channel`` or ``playlist``."""
    extra_fields: Mapping[str, FieldValue] = field(default_factory=dict)
    """Fields an option file makes, such as one ``--parse-metadata`` fills."""


class _Unsupported(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FieldValue:
    """What one yt-dlp field becomes: a Jinja expression over Collection template variables."""

    expression: str
    type: ValueType = "str"
    always: bool = False
    """Whether the value is always there, so no default is needed."""
    support: Support = "exact"
    reason: str | None = None


_INDEXES = {
    "playlist": CustomIndexPlan("playlist", "Playlist index", keep_numbers=True),
    "day": CustomIndexPlan("day", "Upload date index", keep_numbers=True),
    "autonumber": CustomIndexPlan("autonumber", "Autonumber", keep_numbers=True),
}

_FIELDS: dict[str, FieldValue] = {
    "title": FieldValue("title", always=True),
    "fulltitle": FieldValue("title", always=True),
    "id": FieldValue("episode_site_id", always=True),
    "display_id": FieldValue("episode_site_id", always=True, support="close", reason="VODLoft keeps the video id, which YouTube also uses as its display id"),
    "upload_date": FieldValue("date", "date", always=True),
    "release_date": FieldValue("date", "date", always=True, support="close", reason="VODLoft keeps the upload date; a premiere's release date can differ"),
    "timestamp": FieldValue("datetime", "datetime", always=True),
    "release_timestamp": FieldValue("datetime", "datetime", always=True, support="close", reason="VODLoft keeps the upload time; a premiere's release time can differ"),
    "uploader": FieldValue("episode_uploader"),
    "channel": FieldValue("collection_author", support="close", reason="VODLoft uses the Collection's author, which is the channel for a channel"),
    "channel_id": FieldValue("collection_site_id", always=True, support="close", reason="VODLoft uses the Collection's own id, which is the channel id for a channel"),
    "playlist": FieldValue("collection_title", always=True, support="close", reason="VODLoft uses the Collection's title, which is the playlist's title for a playlist"),
    "playlist_title": FieldValue("collection_title", always=True, support="close", reason="VODLoft uses the Collection's title, which is the playlist's title for a playlist"),
    "playlist_id": FieldValue("collection_site_id", always=True, support="close", reason="VODLoft uses the Collection's own id, which is the playlist id for a playlist"),
    "duration": FieldValue("duration_seconds", "int", always=True),
    "playlist_index": FieldValue("'playlist' | custom_index", "index", always=True, support="close", reason="Imported numbers are kept; new videos continue from the highest"),
    "playlist_autonumber": FieldValue("'playlist' | custom_index", "index", always=True, support="close", reason="yt-dlp counts only the videos of one run, so this differs per run anyway; VODLoft numbers the whole playlist"),
    "autonumber": FieldValue("'autonumber' | custom_index", "index", always=True, support="close", reason="yt-dlp restarts this on every run; VODLoft keeps numbering from the highest"),
    "video_autonumber": FieldValue("'autonumber' | custom_index", "index", always=True, support="close", reason="yt-dlp restarts this on every run; VODLoft keeps numbering from the highest"),
    "extractor": FieldValue("'youtube'", always=True),
    "extractor_key": FieldValue("'Youtube'", always=True),
}

# Fields YouTube never fills, so yt-dlp always writes its placeholder for them.
_NEVER_FILLED = frozenset({
    "artist", "artists", "creator", "creators", "album", "album_artist", "track", "track_number", "track_id",
    "disc_number", "release_year", "series", "series_id", "season", "season_number", "season_id",
    "episode", "episode_number", "episode_id", "chapter", "chapter_number", "chapter_id", "genre", "composer",
})
_VOLATILE = {
    **dict.fromkeys(
        ("view_count", "like_count", "dislike_count", "comment_count", "repost_count",
         "channel_follower_count", "concurrent_view_count", "average_rating"),
        "it changes all the time",
    ),
    "epoch": "it is the time of the download",
    "playlist_count": "it changes with every new video, which would rename every file",
    "n_entries": "it changes with every new video, which would rename every file",
}
_FORMAT_FIELDS = frozenset({
    "height", "width", "resolution", "fps", "format", "format_id", "format_note", "vcodec", "acodec",
    "tbr", "abr", "vbr", "asr", "filesize", "filesize_approx", "dynamic_range", "audio_channels",
})
# Pinchflat's per-download values, as fields the expansion made of them.
_PINCHFLAT_VALUES: dict[str, FieldValue] = {
    "source_custom_name": FieldValue("collection_title", always=True, support="close", reason="The import names the Collection after the Pinchflat source's custom name"),
    "source_collection_name": FieldValue("collection_title", always=True, support="close", reason="VODLoft uses the Collection's title, which is the channel or playlist name"),
    "source_collection_id": FieldValue("collection_site_id", always=True),
    "media_playlist_index": FieldValue("'%02d' | format('playlist' | custom_index)", always=True, support="close", reason="Imported numbers are kept; new videos continue from the highest"),
    "media_upload_date_index": FieldValue(
        "'%02d' | format('day' | custom_index(per=date, start=99, step=-1))", always=True, support="close",
        reason="Imported numbers are kept; new days start at 99 like Pinchflat, and a second upload that day gets 98",
    ),
}
_PINCHFLAT_IDS = frozenset({"media_item_id", "source_id", "media_profile_id"})

# strftime formats that a VODLoft variable already gives.
_DATE_VARIABLES = {"%Y": "year", "%m": "month", "%d": "day", "%Y-%m-%d": "date"}
_TIME_VARIABLES = {"%H": "hour", "%M": "minute", "%S": "second", "%H:%M:%S": "time"}


def _expression(source: str) -> nodes.Expr:
    output = _ENVIRONMENT.parse("{{ " + source + " }}").body[0]
    assert isinstance(output, nodes.Output)
    return output.nodes[0]


def _const(value: object) -> nodes.Const:
    return nodes.Const(value)


def _filter(node: nodes.Expr, name: str, *args: nodes.Expr) -> nodes.Filter:
    return nodes.Filter(node, name, list(args), [], None, None)


@dataclass
class _Built:
    node: nodes.Expr
    type: ValueType
    always: bool
    support: Support = "exact"
    reasons: list[str] = field(default_factory=list)

    def weaken(self, support: Support, reason: str) -> None:
        if _ORDER[support] > _ORDER[self.support]:
            self.support = support
        self.reasons.append(reason)


class _Converter:
    def __init__(self, options: ConversionOptions) -> None:
        self.options = options
        self.indexes: dict[str, CustomIndexPlan] = {}

    # One alternative.
    def candidate(self, candidate: Candidate) -> _Built | None:
        """The value of one alternative, or None when YouTube never has it."""
        name = candidate.name
        if candidate.negate:
            raise _Unsupported("a negated field has no VODLoft equivalent")
        if len(candidate.path) > 1:
            raise _Unsupported(f"VODLoft has no value inside {name}")
        value = self.value(name)
        if value is None:
            return None
        if "custom_index" in value.expression:
            for key in _INDEXES:
                if f"'{key}' | custom_index" in value.expression:
                    self.indexes[key] = _INDEXES[key]
        built = _Built(_expression(value.expression), value.type, value.always, value.support,
                       [value.reason] if value.reason else [])
        if candidate.maths:
            built = self.maths(built, candidate)
        if candidate.strftime is not None:
            built = self.strftime(built, candidate.strftime)
        return built

    def value(self, name: str) -> FieldValue | None:
        if name.startswith(PSEUDO_FIELD_PREFIX):
            item = name[len(PSEUDO_FIELD_PREFIX):]
            if item in _PINCHFLAT_IDS:
                raise _Unsupported(f"{item} is Pinchflat's own database id")
            if item == "source_collection_type":
                if self.options.collection_type is None:
                    raise _Unsupported("the collection type is only known per Pinchflat source")
                return FieldValue(repr(self.options.collection_type), always=True)
            if item in _PINCHFLAT_VALUES:
                return _PINCHFLAT_VALUES[item]
            raise _Unsupported(f"Pinchflat has no value called {item}")
        if name in self.options.extra_fields:
            return self.options.extra_fields[name]
        if name in _FIELDS:
            if name in {"autonumber", "video_autonumber"} and self.options.autonumber_start != 1:
                start = self.options.autonumber_start
                return FieldValue(f"'autonumber' | custom_index(start={start})", "index", always=True,
                              support="close", reason=_FIELDS[name].reason)
            return _FIELDS[name]
        if name in _NEVER_FILLED:
            return None
        if name in _VOLATILE:
            raise _Unsupported(_VOLATILE[name])
        if name in _FORMAT_FIELDS:
            if name in self.options.format_values:
                return FieldValue(repr(self.options.format_values[name]), always=True, support="close",
                              reason="The value of the format VODLoft will request")
            raise _Unsupported(f"{name} depends on the format of each download")
        raise _Unsupported(f"VODLoft has no value like {name}")

    def maths(self, built: _Built, candidate: Candidate) -> _Built:
        if built.type not in ("int", "index"):
            raise _Unsupported("maths only works on numbers")
        node = built.node if built.type == "index" else _filter(built.node, "float")
        for item in candidate.maths:
            if not isinstance(item.operand, float):
                raise _Unsupported("maths with another field has no VODLoft equivalent")
            operand = _const(item.operand)
            node = {"+": nodes.Add, "-": nodes.Sub, "*": nodes.Mul}[item.operator](node, operand)
        # yt-dlp does maths in floats, so the result prints as 4.0.
        return _Built(node, "int", built.always, built.support, built.reasons)

    def strftime(self, built: _Built, format_: str) -> _Built:
        if built.type == "date":
            if format_ in _DATE_VARIABLES:
                return _Built(nodes.Name(_DATE_VARIABLES[format_], "load"), "str", True, built.support, built.reasons)
            return _Built(_filter(nodes.Name("date", "load"), "strftime", _const(format_)), "str", True,
                          built.support, built.reasons)
        if built.type == "datetime":
            variables = {**_DATE_VARIABLES, **_TIME_VARIABLES}
            if format_ in variables:
                return _Built(nodes.Name(variables[format_], "load"), "str", True, built.support, built.reasons)
            return _Built(_filter(nodes.Name("datetime", "load"), "strftime", _const(format_)), "str", True,
                          built.support, built.reasons)
        raise _Unsupported("only dates can have a date format")

    # One whole field.
    def field(self, field_: Field, report: ReportBuilder, *, last: bool) -> nodes.Expr | None:
        support: Support = "exact"
        reasons: list[str] = []

        def weaken(level: Support, reason: str) -> None:
            nonlocal support
            if _ORDER[level] > _ORDER[support]:
                support = level
            reasons.append(reason)

        values: list[_Built] = []
        for candidate in field_.candidates:
            if values and values[-1].always:
                break
            try:
                built = self.candidate(candidate)
            except _Unsupported as exc:
                level: Support = "close" if values else "unsupported"
                weaken(level, f"{candidate.field} is not converted, because {exc.reason}")
                continue
            if built is None:
                if len(field_.candidates) == 1 or candidate is field_.candidates[-1] and not values:
                    weaken("exact", f"YouTube never fills {candidate.field}, so yt-dlp writes its placeholder")
                continue
            for reason in built.reasons:
                weaken(built.support, reason)
            values.append(built)

        default = field_.default if field_.default is not None else self.options.na_placeholder
        if not values:
            report_result = default
            node = _const(default) if default else None
            if support == "exact" and not reasons:
                reasons.append("YouTube never fills it, so yt-dlp writes its placeholder")
            report.add(field_.source, repr(default) if default else "", support, "; ".join(reasons) or None)
            return node

        value = values[0].node
        for item in values[1:]:
            value = nodes.Or(value, item.node)
        always = values[-1].always
        value_type = values[0].type if len(values) == 1 else "str"

        try:
            if field_.replacement is not None:
                value = nodes.CondExpr(value, self.replacement(field_.replacement, value), _const(default))
                always, value_type = True, "str"
            node = self.conversion(field_, value, value_type, always=always, default=default)
        except _Unsupported as exc:
            weaken("unsupported", f"left out: {exc.reason}")
            report.add(field_.source, "", support, "; ".join(reasons))
            return None
        if not always and field_.conversion in "sS" and default:
            node = nodes.Or(node, _const(default))
        if field_.conversion == "S" and "#" in field_.flags:
            weaken("close", "VODLoft cleans this value with the filename mode of its settings, not always as Restricted")
        printed = expression_source(node)
        report.add(field_.source, "{{ " + printed + " }}", support, "; ".join(reasons) or None)
        return node

    def replacement(self, replacement: str, value: nodes.Expr) -> nodes.Expr:
        pieces: list[nodes.Expr] = []
        text = ""
        index = 0
        while index < len(replacement):
            char = replacement[index]
            pair = replacement[index:index + 2]
            if pair in ("{{", "}}"):
                text += char
                index += 2
            elif char == "{":
                end = replacement.find("}", index)
                if end < 0 or replacement[index + 1:end] not in ("", "0"):
                    raise _Unsupported("only {} can be replaced in a replacement")
                if text:
                    pieces.append(_const(text))
                    text = ""
                pieces.append(value)
                index = end + 1
            else:
                text += char
                index += 1
        if text:
            pieces.append(_const(text))
        if not pieces:
            return _const("")
        return pieces[0] if len(pieces) == 1 else nodes.Concat(pieces)

    def conversion(self, field_: Field, value: nodes.Expr, value_type: ValueType, *, always: bool, default: str) -> nodes.Expr:
        conversion = field_.conversion
        width, precision, flags = field_.width, field_.precision, field_.flags.replace("#", "")
        name = field_.candidates[-1].name if field_.candidates else ""
        if conversion in "sS" and value_type == "index" and width is None and precision is None:
            # yt-dlp pads playlist_index, playlist_autonumber and autonumber with zeros for %s.
            size = {"playlist_index": self.options.playlist_index_width,
                    "playlist_autonumber": self.options.playlist_index_width,
                    "autonumber": 5}.get(name)
            if size:
                return _filter(_const(f"%0{size}d"), "format", value)
            return value
        if conversion in "sS":
            if value_type == "date":
                value = _filter(nodes.Name("date", "load"), "strftime", _const("%Y%m%d"))
            elif value_type == "datetime":
                raise _Unsupported("a raw time stamp has no VODLoft equivalent; give it a date format")
            if precision is not None:
                value = nodes.Getitem(value, nodes.Slice(None, _const(precision), None), "load")
            if width is not None:
                value = _filter(_const(f"%{flags}{width}s"), "format", value)
            return value
        if conversion in "dif":
            if value_type not in ("int", "index"):
                raise _Unsupported("a number format needs a number")
            number = value if value_type == "index" else _filter(value, "float" if conversion == "f" else "int")
            spec = f"%{flags}{width or ''}{'.' + str(precision) if precision is not None else ''}{'d' if conversion == 'i' else conversion}"
            formatted = _filter(_const(spec), "format", number)
            if not always:
                return nodes.CondExpr(value, formatted, _const(default))
            return formatted
        raise _Unsupported(f"the %{conversion} conversion has no VODLoft equivalent")


def _literal(text: str) -> str:
    """Literal text that Jinja reads as text, even right before an expression."""
    out = []
    for index, char in enumerate(text):
        if char == "{" and text[index + 1:index + 2] in ("{", "%", "#", ""):
            out.append("{{ '{' }}")
        else:
            out.append(char)
    return "".join(out)


def _check(output_template: str, expressions: list[nodes.Expr]) -> None:
    """Parse the template again and make sure each expression reads as built."""
    parsed = _ENVIRONMENT.parse(output_template)
    # Literal braces are written as {{ '{' }}; they are text, not expressions.
    found = [node for output in parsed.find_all(nodes.Output) for node in output.nodes
             if not isinstance(node, nodes.TemplateData) and not (isinstance(node, nodes.Const) and node.value == "{")]
    if [expression_source(node) for node in found] != [expression_source(node) for node in expressions]:
        raise UnsafeEdit()


def convert_ytdlp(template: str, options: ConversionOptions | None = None, *, original: str | None = None) -> ConversionReport:
    """Convert a yt-dlp output template, relative to the download folder."""
    options = options or ConversionOptions()
    original = template if original is None else original
    try:
        parsed: Template = parse(template)
    except TemplateSyntaxError as exc:
        return ConversionReport(original, template, None, errors=(str(exc),))

    converter = _Converter(options)
    report = ReportBuilder()
    parts = list(parsed.parts)
    if parts and isinstance(parts[0], Text) and parts[0].text.startswith("/"):
        parts[0] = Text(parts[0].text.lstrip("/"), parts[0].start)
        report.add("/", "", "close", "The template's folder becomes VODLoft's download folder")

    # The extension: yt-dlp's .%(ext)s at the end becomes VODLoft's .ext.
    has_extension = (
        len(parts) >= 2 and isinstance(parts[-1], Field) and isinstance(parts[-2], Text)
        and parts[-2].text.endswith(".") and len(parts[-1].candidates) == 1
        and parts[-1].candidates[0].field == "ext" and parts[-1].conversion in "sS"
    )
    extension_source = parts[-1].source if has_extension else None
    if has_extension:
        parts = parts[:-1]
        parts[-1] = Text(parts[-1].text[:-1], parts[-1].start)

    output: list[str] = ["/downloads/"]
    expressions: list[nodes.Expr] = []
    for index, part in enumerate(parts):
        if isinstance(part, Text):
            output.append(_literal(part.text))
            if part.text:
                report.add(part.text, part.text)
            continue
        if part.candidates and part.candidates[0].field == "ext":
            report.add(part.source, "", "unsupported", "VODLoft only has the extension at the end of the file name")
            continue
        node = converter.field(part, report, last=index == len(parts) - 1)
        if node is None:
            continue
        if isinstance(node, nodes.Const) and isinstance(node.value, str):
            output.append(_literal(node.value))
            continue
        try:
            output.append("{{ " + expression_source(node) + " }}")
        except UnsafeEdit:
            return ConversionReport(original, template, None, tuple(report.parts),
                                    errors=(f"{part.source} could not be written as Jinja",))
        expressions.append(node)
    output.append(".ext")
    if extension_source:
        report.add("." + extension_source, ".ext")
    else:
        report.add("", ".ext", "close", "The template has no .%(ext)s at the end; VODLoft adds the extension itself")

    output_template = "".join(output)
    try:
        _check(output_template, expressions)
    except (JinjaSyntaxError, UnsafeEdit):
        return ConversionReport(original, template, None, tuple(report.parts),
                                errors=("The converted template does not read back as it was written",))
    if output_template == "/downloads/.ext":
        return ConversionReport(original, template, None, tuple(report.parts),
                                errors=("Nothing of the file name is left after conversion",))
    return ConversionReport(
        original, template, output_template, tuple(report.parts),
        tuple(converter.indexes[key] for key in sorted(converter.indexes)),
    )


def convert_pinchflat(template: str, options: ConversionOptions | None = None) -> ConversionReport:
    """Convert a Pinchflat output template: liquid-style, yt-dlp style, or both."""
    try:
        ytdlp_template = expand(template)
    except TemplateSyntaxError as exc:
        return ConversionReport(template, template, None, errors=(str(exc),))
    return convert_ytdlp(ytdlp_template, options, original=template)
