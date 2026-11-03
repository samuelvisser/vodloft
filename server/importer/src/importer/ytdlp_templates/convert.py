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

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from jinja2 import Environment, TemplateSyntaxError as JinjaSyntaxError, nodes
from jinja_analysis import UnsafeEdit, expression_source
from yt_dlp.postprocessor.metadataparser import MetadataParserPP

from ..contract import CustomIndexPlan, Support
from .grammar import Candidate, Field, Template, TemplateSyntaxError, Text, parse
from .options import MetadataAction, OptionSet
from .pinchflat import PSEUDO_FIELD_PREFIX, expand, written_as
from .report import ConversionReport, PartReport, ReportBuilder

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
    for_playlists: bool = False
    """Whether some Collections that use the template are playlists, whose videos can come from many channels."""
    extra_fields: Mapping[str, FieldValue] = field(default_factory=dict)
    """Fields the importer knows a value for, by yt-dlp name."""
    metadata_actions: tuple[MetadataAction, ...] = ()
    """``--parse-metadata`` and ``--replace-in-metadata``, in the order yt-dlp runs them."""
    root: str = "/downloads/"
    """The VODLoft folder that is the download folder of the template, ending in ``/``."""


def options_from(option_set: OptionSet, **overrides: object) -> ConversionOptions:
    """Conversion options for what yt-dlp's options say: placeholder, numbering and metadata actions."""
    placeholder = option_set.effective("outtmpl_na_placeholder", "NA")
    start = option_set.effective("autonumber_start", 1)
    values: dict[str, object] = {
        "na_placeholder": "NA" if placeholder is None else str(placeholder),
        "autonumber_start": 1 if start is None else int(start),
        "metadata_actions": option_set.actions,
    }
    values.update(overrides)
    return ConversionOptions(**values)  # type: ignore[arg-type]


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

# A playlist's videos can come from many channels and a playlist Collection has no author, so each
# video's own channel is its uploader. A channel's videos all have it as their uploader too.
_PLAYLIST_CHANNEL = FieldValue(
    "episode_uploader", support="close", reason="VODLoft uses each video's uploader, which is its channel",
)

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
    # Pinchflat writes these into the template before yt-dlp sees it, so restrict_filenames leaves them alone.
    # The import names the Collection after the source's custom name, so this is exact.
    "source_custom_name": FieldValue("collection_title | as_typed", always=True),
    "source_collection_name": FieldValue("collection_title | as_typed", always=True, support="close", reason="VODLoft uses the Collection's title, which is the channel or playlist name"),
    "source_collection_id": FieldValue("collection_site_id", always=True),
    "media_playlist_index": FieldValue("'%02d' | format('playlist' | custom_index)", always=True, support="close", reason="Imported numbers are kept; new videos continue from the highest"),
    "media_upload_date_index": FieldValue(
        "'%02d' | format('day' | custom_index(per=date, start=99, step=-1))", always=True, support="close",
        reason="Imported numbers are kept; new days start at 99 like Pinchflat, and a second upload that day gets 98",
    ),
}
# Pinchflat counts a playlist's uploads of one day up from 0, and a channel's down from 99.
_PLAYLIST_UPLOAD_DATE_INDEX = FieldValue(
    "'%02d' | format('day' | custom_index(per=date, start=0))", always=True, support="close",
    reason="Imported numbers are kept; a playlist's uploads of one day count up from 0 like Pinchflat",
)
_PINCHFLAT_IDS = frozenset({"media_item_id", "source_id", "media_profile_id"})

# VODLoft's Collection template variables. A metadata action that changes a
# yt-dlp field of another name writes to a variable of its own, so it never
# changes a VODLoft variable that other fields read.
VODLOFT_VARIABLES = frozenset({
    "collection", "collection_title", "season", "season_name", "season_index", "season_type", "season_number",
    "episode", "episode_title", "title", "dw_episode_number", "episode_type", "episode_extra_type",
    "episode_number", "episode_sub_number", "episode_label", "episode_identifier", "episode_published_date",
    "episode_published_time", "episode_published_datetime", "episode_index",
    "collection_author", "collection_site_id", "episode_site_id", "episode_uploader", "duration_seconds",
    "date", "time", "datetime", "year", "month", "day", "hour", "minute", "second",
})
_MATCH = "ytdlp_match"

# strftime formats that a VODLoft variable already gives.
_DATE_VARIABLES = {"%Y": "year", "%m": "month", "%d": "day", "%Y-%m-%d": "date"}
_TIME_VARIABLES = {"%H": "hour", "%M": "minute", "%S": "second", "%H:%M:%S": "time"}


def _index_plan(key: str, expression: str) -> CustomIndexPlan:
    """The Custom Index ``expression`` uses for ``key``, with its start= and step=."""
    plan = _INDEXES[key]
    call = re.search(rf"'{key}' \| custom_index(?:\((?P<args>[^)]*)\))?", expression)
    args = call.group("args") or "" if call else ""
    start = re.search(r"\bstart=(-?\d+)", args)
    step = re.search(r"\bstep=(-?\d+)", args)
    return CustomIndexPlan(
        plan.key, plan.name, plan.keep_numbers,
        start=int(start.group(1)) if start else 1, step=int(step.group(1)) if step else 1,
    )


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
        self.bindings: dict[str, FieldValue] = {}
        """yt-dlp fields a metadata action changed, as the variable that now holds them."""
        self.shadowed: dict[str, str] = {}
        """VODLoft variables a metadata action changed, with the yt-dlp field that changed them."""

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
        if name not in self.bindings:
            expression = _expression(value.expression)
            changed = {
                node.name for node in (expression, *expression.find_all(nodes.Name)) if isinstance(node, nodes.Name)
            } & set(self.shadowed)
            if changed:
                variable = sorted(changed)[0]
                value = FieldValue(
                    value.expression, value.type, value.always, "close",
                    f"{name} reads {variable}, which an option file changed for {self.shadowed[variable]}",
                )
        if "custom_index" in value.expression:
            for key in _INDEXES:
                if f"'{key}' | custom_index" in value.expression:
                    self.indexes[key] = _index_plan(key, value.expression)
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
            if item == "media_upload_date_index" and self.options.collection_type == "playlist":
                return _PLAYLIST_UPLOAD_DATE_INDEX
            if item in _PINCHFLAT_VALUES:
                return _PINCHFLAT_VALUES[item]
            raise _Unsupported(f"Pinchflat has no value called {item}")
        if name in self.bindings:
            return self.bindings[name]
        if name in self.options.extra_fields:
            return self.options.extra_fields[name]
        if name == "channel" and (self.options.for_playlists or self.options.collection_type == "playlist"):
            return _PLAYLIST_CHANNEL
        if name in {"channel", "channel_id"} and self.options.collection_type == "channel":
            # A channel Collection's author and id are that channel's, so these are exact.
            return replace(_FIELDS[name], support="exact", reason=None)
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

    # Metadata actions.
    def inline(self, template: str) -> tuple[nodes.Expr, bool, Support, list[str]]:
        """A yt-dlp template as one Jinja expression, as yt-dlp fills it in for a metadata action."""
        scratch = ReportBuilder()
        pieces: list[nodes.Expr] = []
        always = False
        for part in parse(template).parts:
            if isinstance(part, Text):
                if part.text:
                    pieces.append(_const(part.text))
                    always = True
                continue
            node = self.field(part, scratch, last=False)
            if node is not None:
                pieces.append(node)
                always = always or not isinstance(node, nodes.CondExpr)
        support: Support = "exact"
        reasons: list[str] = []
        for entry in scratch.parts:
            if _ORDER[entry.support] > _ORDER[support]:
                support = entry.support
            if entry.reason:
                reasons.append(entry.reason)
        if not pieces:
            return _const(""), False, support, reasons
        node = pieces[0] if len(pieces) == 1 else nodes.Concat(pieces)
        return node, always, support, reasons

    def variable(self, name: str, current: FieldValue | None) -> str:
        """The variable that holds a changed yt-dlp field."""
        if name not in VODLOFT_VARIABLES or (current is not None and current.expression == name):
            if current is not None and current.expression == name and name in VODLOFT_VARIABLES:
                self.shadowed[name] = name
            return name
        return f"ytdlp_{name}"

    def action(self, action: MetadataAction) -> tuple[list[nodes.Assign], Support, str | None]:
        if action.kind == "replace":
            return self.replace_action(*action.arguments)
        return self.interpret_action(*action.arguments)

    def replace_action(self, name: str, search: str, replace: str) -> tuple[list[nodes.Assign], Support, str | None]:
        try:
            current = self.value(name)
        except _Unsupported as exc:
            raise _Unsupported(f"{name} is not converted, because {exc.reason}") from None
        if current is None:
            return [], "exact", f"YouTube never fills {name}, so yt-dlp changes nothing"
        if current.type in ("int", "index"):
            return [], "exact", f"{name} is a number, which yt-dlp does not change"
        if current.type != "str":
            raise _Unsupported(f"VODLoft can't change the text of {name}")
        old = _expression(current.expression)
        new: nodes.Expr = _filter(old, "regex_replace", _const(search), _const(replace))
        if not current.always:
            new = nodes.CondExpr(old, new, old)
        target = self.variable(name, current)
        self.bindings[name] = FieldValue(target, "str", current.always, current.support, current.reason)
        return [nodes.Assign(nodes.Name(target, "store"), new)], current.support, current.reason

    def interpret_action(self, source: str, out: str) -> tuple[list[nodes.Assign], Support, str | None]:
        template = MetadataParserPP.field_to_template(source)
        pattern = MetadataParserPP.format_to_regex(out)
        compiled = re.compile(pattern)
        data, data_always, support, reasons = self.inline(template)
        names = list(compiled.groupindex)
        if not names:
            return [], "exact", "The pattern names no field, so yt-dlp changes nothing"
        statements: list[nodes.Assign] = []
        # A pattern that takes the whole value; without (?s) it takes the first line,
        # which is the whole value for every field VODLoft has.
        whole = pattern in (rf"(?s)(?P<{names[0]}>.+)", rf"(?P<{names[0]}>.+)")
        if not whole:
            statements.append(nodes.Assign(nodes.Name(_MATCH, "store"), _filter(data, "regex_groups", _const(pattern))))
            if _optional_groups(compiled):
                support = "close" if support == "exact" else support
                reasons.append("A part of the pattern that does not match leaves the field empty, where yt-dlp keeps it")
        for name in names:
            try:
                current = self.value(name)
            except _Unsupported:
                current = None
            old = _expression(current.expression) if current is not None else _const("")
            old_always = current is not None and current.always
            if whole:
                value: nodes.Expr = data if data_always else nodes.CondExpr(data, data, old)
                always = data_always or old_always
            else:
                group = nodes.Getitem(nodes.Name(_MATCH, "load"), _const(compiled.groupindex[name] - 1), "load")
                value = nodes.CondExpr(nodes.Name(_MATCH, "load"), group, old)
                always = old_always
            target = self.variable(name, current)
            statements.append(nodes.Assign(nodes.Name(target, "store"), value))
            self.bindings[name] = FieldValue(target, "str", always, support, "; ".join(reasons) or None)
        return statements, support, "; ".join(reasons) or None

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


def _optional_groups(pattern: re.Pattern[str]) -> bool:
    """Whether a named group of the pattern can be left out of a match."""
    try:
        from re import _parser as sre_parse  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover
        import sre_parse  # type: ignore[no-redef]
    named = set(pattern.groupindex.values())

    def walk(items, optional: bool) -> bool:
        for op, av in items:
            name = str(op)
            if name == "SUBPATTERN":
                group, _add, _del, sub = av
                if group in named and optional:
                    return True
                if walk(sub, optional):
                    return True
            elif name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
                low, _high, sub = av
                if walk(sub, optional or low == 0):
                    return True
            elif name == "BRANCH":
                if any(walk(branch, True) for branch in av[1]):
                    return True
            elif name in ("ASSERT", "ASSERT_NOT"):
                if walk(av[1], True):
                    return True
            elif name == "GROUPREF_EXISTS":
                if walk(av[1], True) or (av[2] is not None and walk(av[2], True)):
                    return True
        return False

    return walk(sre_parse.parse(pattern.pattern), False)


def _literal(text: str) -> str:
    """Literal text that Jinja reads as text, even right before an expression."""
    out = []
    for index, char in enumerate(text):
        if char == "{" and text[index + 1:index + 2] in ("{", "%", "#", ""):
            out.append("{{ '{' }}")
        else:
            out.append(char)
    return "".join(out)


def _check(output_template: str, expressions: list[nodes.Expr], assignments: list[nodes.Assign] = ()) -> None:
    """Parse the template again and make sure each expression and {% set %} reads as built."""
    parsed = _ENVIRONMENT.parse(output_template)
    found_sets = [(node.target.name, expression_source(node.node)) for node in parsed.find_all(nodes.Assign)]
    if found_sets != [(node.target.name, expression_source(node.node)) for node in assignments]:
        raise UnsafeEdit()
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

    prelude, assignments, action_reports = _prelude(converter, options.metadata_actions, parsed)
    root = options.root if options.root.endswith("/") else options.root + "/"
    output: list[str] = [*prelude, root]
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
        _check(output_template, expressions, assignments)
    except (JinjaSyntaxError, UnsafeEdit):
        return ConversionReport(original, template, None, tuple(report.parts), actions=action_reports,
                                errors=("The converted template does not read back as it was written",))
    if output_template.endswith(root + ".ext"):
        return ConversionReport(original, template, None, tuple(report.parts), actions=action_reports,
                                errors=("Nothing of the file name is left after conversion",))
    return ConversionReport(
        original, template, output_template, tuple(report.parts),
        tuple(converter.indexes[key] for key in sorted(converter.indexes)),
        actions=action_reports,
    )


def _action_source(action: MetadataAction) -> str:
    if action.kind == "interpret":
        return f"--parse-metadata {':'.join(action.arguments)!r}"
    field_, search, replace = action.arguments
    return f"--replace-in-metadata {field_} {search!r} {replace!r}"


def _template_fields(template: str) -> set[str]:
    try:
        return {candidate.name for part in parse(template).fields for candidate in part.candidates}
    except TemplateSyntaxError:
        return set()


def _prelude(
    converter: _Converter, actions: tuple[MetadataAction, ...], parsed: Template,
) -> tuple[list[str], list[nodes.Assign], tuple[PartReport, ...]]:
    """The {% set %} lines for the metadata actions that change the file name."""
    if not actions:
        return [], [], ()
    # Walk back from the template: an action counts when a field it sets is read later.
    needed = {candidate.name for part in parsed.fields for candidate in part.candidates}
    live = [False] * len(actions)
    for index in range(len(actions) - 1, -1, -1):
        action = actions[index]
        if action.kind == "replace":
            sets = {action.arguments[0]}
        else:
            try:
                sets = set(re.compile(MetadataParserPP.format_to_regex(action.arguments[1])).groupindex)
            except re.error:
                sets = set()
        if sets & needed:
            live[index] = True
            if action.kind == "interpret":
                needed |= _template_fields(MetadataParserPP.field_to_template(action.arguments[0]))

    lines: list[str] = []
    assignments: list[nodes.Assign] = []
    reports: list[PartReport] = []
    for action, used in zip(actions, live, strict=True):
        source = _action_source(action)
        if not used:
            reports.append(PartReport(source, "", "exact", f"From {action.origin}. The template doesn't use what it changes"))
            continue
        try:
            statements, support, reason = converter.action(action)
            # One line, as the Local Media Profile editor saves a template.
            printed = [f"{{% set {node.target.name} = {expression_source(node.node)} -%}}" for node in statements]
        except (_Unsupported, UnsafeEdit, re.error, ValueError) as exc:
            reason = getattr(exc, "reason", None) or str(exc) or "it could not be written as Jinja"
            reports.append(PartReport(source, "", "unsupported", f"From {action.origin}. Not converted: {reason}"))
            continue
        lines.extend(printed)
        assignments.extend(statements)
        detail = f"From {action.origin}." + (f" {reason}" if reason else "")
        reports.append(PartReport(source, "".join(printed), support, detail))
    return lines, assignments, tuple(reports)


def convert_pinchflat(template: str, options: ConversionOptions | None = None) -> ConversionReport:
    """Convert a Pinchflat output template: liquid-style, yt-dlp style, or both."""
    try:
        ytdlp_template = expand(template)
    except TemplateSyntaxError as exc:
        return ConversionReport(template, template, None, errors=(str(exc),))
    report = convert_ytdlp(ytdlp_template, options, original=template)
    # Name each part as the person wrote it: Pinchflat's {{ channel }}, not the %(channel)S it stands for.
    aliases = written_as(template)
    parts = []
    for part in report.parts:
        part = replace(part, source=aliases.get(part.source, part.source))
        if part.source == "/" and not part.result:
            # Pinchflat starts every path in its media folder, which the import maps to VODLoft's folder.
            part = replace(part, support="exact", reason=None)
        parts.append(part)
    return replace(report, parts=tuple(parts))
