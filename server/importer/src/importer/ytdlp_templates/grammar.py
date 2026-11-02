"""yt-dlp output templates as a typed syntax tree.

The grammar follows ``YoutubeDL.prepare_outtmpl`` exactly: the same regular
expressions find each ``%(…)X`` field and split its key into field traversal,
maths, a strftime format, alternatives, a replacement and a default. Parsing
only reads the template; nothing is evaluated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_RE = r"\d+(?:\.\d+)?"
STR_FORMAT_TYPES = "diouxXeEfFgGcrsa"
# yt-dlp's STR_FORMAT_RE_TMPL, with its key and type parts filled in as
# prepare_outtmpl fills them.
_EXTERNAL_FORMAT_RE = re.compile(r"""(?x)
    (?<!%)(?P<prefix>(?:%%)*)
    %
    (?P<has_key>\((?P<key>[^)]*)\))?
    (?P<format>
        (?P<conversion>[#0\-+ ]+)?
        (?P<min_width>\d+)?
        (?P<precision>\.\d+)?
        (?P<len_mod>[hlL])?
        [""" + STR_FORMAT_TYPES + r"""ljhqBUDS]
    )
""")
_MATH_OPERATORS = ("+", "-", "*")
_FIELD_INNER_RE = r"(?:\w+|%(num)s|%(num)s?(?::%(num)s?){1,2})" % {"num": r"(?:-?\d+)"}
_FIELD_RE = r"\w*(?:\.(?:%(inner)s|{%(field)s(?:,%(field)s)*}))*" % {
    "inner": _FIELD_INNER_RE,
    "field": rf"\w*(?:\.{_FIELD_INNER_RE})*",
}
_MATH_FIELD_RE = rf"(?:{_FIELD_RE}|-?{NUMBER_RE})"
_MATH_OPERATORS_RE = r"(?:{})".format("|".join(map(re.escape, _MATH_OPERATORS)))
_INTERNAL_FORMAT_RE = re.compile(rf"""(?xs)
    (?P<negate>-)?
    (?P<fields>{_FIELD_RE})
    (?P<maths>(?:{_MATH_OPERATORS_RE}{_MATH_FIELD_RE})*)
    (?:>(?P<strf_format>.+?))?
    (?P<remaining>
        (?P<alternate>(?<!\\),[^|&)]+)?
        (?:&(?P<replacement>.*?))?
        (?:\|(?P<default>.*?))?
    )$""")


class TemplateSyntaxError(ValueError):
    """The template is not one yt-dlp accepts."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} (at character {position + 1})")
        self.position = position


@dataclass(frozen=True)
class Text:
    """Literal text, with ``%%`` already turned into ``%``."""

    text: str
    start: int


@dataclass(frozen=True)
class Maths:
    operator: str
    operand: str | float
    """A number, or a field whose value is used."""


@dataclass(frozen=True)
class Candidate:
    """One alternative: a field with its maths and date format."""

    field: str
    """The field as written, such as ``title`` or ``tags.0``."""
    negate: bool = False
    maths: tuple[Maths, ...] = ()
    strftime: str | None = None

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(part for part in re.split(r"\.(?![^{]*})", self.field) if part)

    @property
    def name(self) -> str:
        """The top-level field, such as ``tags`` for ``tags.0``."""
        return self.path[0] if self.path else ""


@dataclass(frozen=True)
class Field:
    """One ``%(…)X`` field."""

    source: str
    start: int
    candidates: tuple[Candidate, ...]
    replacement: str | None
    default: str | None
    """The ``|default``; None means yt-dlp's NA placeholder."""
    flags: str
    width: int | None
    precision: int | None
    conversion: str
    """The conversion letter, such as ``s``, ``S`` or ``d``."""


Part = Text | Field


@dataclass(frozen=True)
class Template:
    source: str
    parts: tuple[Part, ...]

    @property
    def fields(self) -> tuple[Field, ...]:
        return tuple(part for part in self.parts if isinstance(part, Field))


def _maths(text: str, position: int) -> tuple[Maths, ...]:
    items: list[Maths] = []
    operator: str | None = None
    while text:
        match = re.match(_MATH_FIELD_RE if operator else _MATH_OPERATORS_RE, text)
        if match is None or not match.group(0):
            raise TemplateSyntaxError("Unreadable maths in a field", position)
        item = match.group(0)
        text = text[len(item):]
        if operator is None:
            operator = item
            continue
        try:
            operand: str | float = float(item)
        except ValueError:
            operand = item
        items.append(Maths(operator, operand))
        operator = None
    return tuple(items)


def _key(key: str, position: int) -> tuple[tuple[Candidate, ...], str | None, str | None]:
    candidates: list[Candidate] = []
    replacement = default = None
    match = _INTERNAL_FORMAT_RE.match(key)
    if match is None:
        raise TemplateSyntaxError(f"Unreadable field %({key})", position)
    while match:
        groups = match.groupdict()
        if groups["default"] is not None:
            default = groups["default"]
        replacement = groups["replacement"]
        candidates.append(Candidate(
            field=groups["fields"],
            negate=bool(groups["negate"]),
            maths=_maths(groups["maths"], position),
            strftime=groups["strf_format"].replace("\\,", ",") if groups["strf_format"] else None,
        ))
        if not groups["alternate"]:
            break
        match = _INTERNAL_FORMAT_RE.match(groups["remaining"][1:])
    return tuple(candidates), replacement, default


def _text(text: str, start: int) -> Text:
    # A % that starts no field must still be one Python's % accepts as text.
    for match in re.finditer(r"%+", text):
        run = match.group(0)
        following = text[match.end():match.end() + 1]
        if len(run) % 2 and following == "(":
            raise TemplateSyntaxError("A field is not finished; it needs a type such as %(title)s", start + match.start())
    return Text(re.sub(r"%%", "%", text), start)


def parse(template: str) -> Template:
    """Parse a yt-dlp output template into literal text and fields."""
    parts: list[Part] = []
    position = 0
    for match in _EXTERNAL_FORMAT_RE.finditer(template):
        prefix = match.group("prefix")
        literal = template[position:match.start()] + prefix
        if literal:
            parts.append(_text(literal, position))
        start = match.start() + len(prefix)
        if not match.group("has_key"):
            # A key-less %s and the like are text to yt-dlp (escape_outtmpl doubles them).
            parts.append(Text(template[start:match.end()], start))
        else:
            candidates, replacement, default = _key(match.group("key"), start)
            parts.append(Field(
                source=template[start:match.end()],
                start=start,
                candidates=candidates,
                replacement=replacement,
                default=default,
                flags=match.group("conversion") or "",
                width=int(match.group("min_width")) if match.group("min_width") else None,
                precision=int(match.group("precision")[1:]) if match.group("precision") else None,
                conversion=match.group("format")[-1],
            ))
        position = match.end()
    if position < len(template):
        parts.append(_text(template[position:], position))
    merged: list[Part] = []
    for part in parts:
        if isinstance(part, Text) and merged and isinstance(merged[-1], Text):
            merged[-1] = Text(merged[-1].text + part.text, merged[-1].start)
        else:
            merged.append(part)
    return Template(template, tuple(merged))
