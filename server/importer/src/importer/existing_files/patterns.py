"""A path template turned around: a pattern that reads values back out of a path.

``/downloads/{{ collection_title }}/{{ date }} {{ title }}.ext`` reads the
Collection title, the date and the title out of a path. Both the path and the
values are compared in a loose form (see :func:`normalise`), so the filename
mode's replacements, such as ``：`` for ``:`` or ``_`` for a space, still match.

Values with nothing but spaces or punctuation between them (``{{ date }}
{{ title }}``) can split in more than one place; :meth:`PathPattern.read`
gives every split that fits the values' shapes, and the matcher keeps the
ones that name an episode.
"""
from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from dataclasses import dataclass

from jinja2 import Environment, TemplateSyntaxError, nodes
from jinja_analysis import UnknownOutput, analyze_template
from jinja_analysis.paths import INPUT_PREFIX

from .normal import normalise_words

_ENVIRONMENT = Environment()
_MAX_READINGS = 256

# What a variable's value looks like once normalised.
_SHAPES = {
    "date": r"\d{4} \d{2} \d{2}", "episode_published_date": r"\d{4} \d{2} \d{2}",
    "time": r"\d{2} \d{2} \d{2}", "episode_published_time": r"\d{2} \d{2} \d{2}",
    "datetime": r"\d{4} \d{2} \d{2} \d{2} \d{2} \d{2}",
    "episode_published_datetime": r"\d{4} \d{2} \d{2} \d{2} \d{2} \d{2}",
    "year": r"\d{4}", "month": r"\d{2}", "day": r"\d{2}", "hour": r"\d{2}", "minute": r"\d{2}", "second": r"\d{2}",
    **dict.fromkeys(
        ("season_index", "season_number", "episode_index", "duration_seconds", "dw_episode_number",
         "episode_number", "episode_sub_number"),
        r"\d+",
    ),
}
_COMPILED_SHAPES = {name: re.compile(shape) for name, shape in _SHAPES.items()}

Run = tuple[str | None, ...]
"""Values side by side, with None for a part the pattern can't read (any text)."""


@dataclass(frozen=True)
class PathPattern:
    regex: re.Pattern[str]
    runs: tuple[Run, ...]
    """For each group of the regex, the values it holds."""

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(name for run in self.runs for name in run if name is not None))

    def read(self, normalised_path: str) -> Iterator[dict[str, str]]:
        """Each way the values can be read from a path (normalised, without extension)."""
        match = self.regex.match(normalised_path)
        if match is None:
            return
        options = [list(_splits(match.group(index).strip(), run)) for index, run in enumerate(self.runs, start=1)]
        for combination in itertools.islice(itertools.product(*options), _MAX_READINGS):
            values: dict[str, str] = {}
            for part in combination:
                for name, value in part.items():
                    if values.setdefault(name, value) != value:
                        break
                else:
                    continue
                break
            else:
                yield values


def _splits(text: str, run: Run) -> Iterator[dict[str, str]]:
    """Every split of ``text`` at spaces into one value per part of the run."""
    words = text.split()
    if len(run) == 1:
        name = run[0]
        if name is None:
            yield {}
        elif name not in _COMPILED_SHAPES or _COMPILED_SHAPES[name].fullmatch(text):
            yield {name: text}
        return
    # A part the pattern can't read may also be empty.
    minimum = [0 if name is None else 1 for name in run]
    for cuts in itertools.combinations(range(len(words) + 1), len(run) - 1):
        bounds = (0, *cuts, len(words))
        parts = [" ".join(words[bounds[index]:bounds[index + 1]]) for index in range(len(run))]
        if any(len(part.split()) < minimum[index] for index, part in enumerate(parts)):
            continue
        reading: dict[str, str] = {}
        for name, part in zip(run, parts, strict=True):
            if name is None:
                continue
            if name in _COMPILED_SHAPES and not _COMPILED_SHAPES[name].fullmatch(part):
                break
            if reading.setdefault(name, part) != part:
                break
        else:
            yield reading


def _component_regex(pieces: list[tuple[str, str]], runs: list[Run]) -> str:
    out: list[str] = []
    run: list[str | None] = []

    def close() -> None:
        if not run:
            return
        if len(run) == 1 and run[0] is None:
            out.append(r"[^/]*?")
            run.clear()
            return
        single = run[0] if len(run) == 1 else None
        out.append(f"({_SHAPES[single]})" if single in _SHAPES else r"([^/]*?)")
        runs.append(tuple(run))
        run.clear()

    for kind, value in pieces:
        if kind == "text":
            words = normalise_words(value)
            if words:
                close()
                out.append(r"\s+".join(re.escape(word) for word in words))
        else:
            run.append(value if kind == "variable" else None)
    close()
    return r"\s*".join(out)


def template_patterns(template: str, *, limit: int = 32) -> tuple[PathPattern, ...]:
    """A pattern for each way the template can lay out a path; empty when none reads a value."""
    try:
        analysis = analyze_template(template, environment=_ENVIRONMENT, max_variants=limit)
    except TemplateSyntaxError:
        return ()
    patterns: list[PathPattern] = []
    seen: set[str] = set()
    for variant in analysis.variants:
        components: list[list[tuple[str, str]]] = [[]]
        for part in variant.parts:
            if isinstance(part, str):
                for index, piece in enumerate(part.split("/")):
                    if index:
                        components.append([])
                    if piece:
                        components[-1].append(("text", piece))
            elif isinstance(part, nodes.Name) and part.name.startswith(INPUT_PREFIX):
                components[-1].append(("variable", part.name[len(INPUT_PREFIX):]))
            elif isinstance(part, nodes.Const) and isinstance(part.value, str):
                components[-1].append(("text", part.value))
            else:
                # UnknownOutput, or an expression such as a filter: any text.
                components[-1].append(("any", ""))
        # VODLoft's .ext at the end is the media file's own extension.
        last = components[-1]
        if last and last[-1][0] == "text" and last[-1][1].endswith(".ext"):
            last[-1] = ("text", last[-1][1][:-4])
        runs: list[Run] = []
        regex = "^" + "/".join(_component_regex(pieces, runs) for pieces in components if pieces) + "$"
        pattern = PathPattern(re.compile(regex), tuple(runs))
        if not pattern.variables or regex in seen:
            continue
        seen.add(regex)
        patterns.append(pattern)
    return tuple(patterns)
