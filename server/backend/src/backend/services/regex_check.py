"""Regular expressions people write for Which episodes, checked and run safely.

Filters run on the server, so the regex editor checks and tests patterns here
too: what the editor says matches is what the filter will match. Patterns use
the ``regex`` package, which reads Python's ``re`` syntax and can stop a match
that takes too long. A pattern that runs out of time counts as not matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import regex

MAX_PATTERN_LENGTH = 1000
# Long enough for any sensible title or description, short enough that a
# pathological pattern cannot stall indexing.
MATCH_TIMEOUT_SECONDS = 0.05
MAX_TEXT_LENGTH = 20_000
_INLINE_IGNORE_CASE = "(?i)"


class PatternError(ValueError):
    """A pattern that cannot be used, with where the mistake is when known."""

    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


@dataclass(frozen=True)
class SampleMatch:
    text: str
    matched: bool
    spans: tuple[tuple[int, int], ...] = ()
    timed_out: bool = False


@dataclass(frozen=True)
class PatternCheck:
    pattern: str
    ignore_case: bool
    error: str | None = None
    error_position: int | None = None
    samples: list[SampleMatch] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.error is None


def split_inline_ignore_case(pattern: str, ignore_case: bool) -> tuple[str, bool]:
    """A pasted leading ``(?i)`` becomes the Ignore case flag."""
    if pattern.startswith(_INLINE_IGNORE_CASE):
        return pattern[len(_INLINE_IGNORE_CASE):], True
    return pattern, ignore_case


@lru_cache(maxsize=512)
def compile_pattern(pattern: str, ignore_case: bool) -> regex.Pattern:
    if not pattern:
        raise PatternError("Type a pattern")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PatternError(f"Keep the pattern under {MAX_PATTERN_LENGTH} characters", MAX_PATTERN_LENGTH)
    flags = regex.VERSION0 | (regex.IGNORECASE if ignore_case else 0)
    try:
        return regex.compile(pattern, flags)
    except regex.error as exc:
        message = str(getattr(exc, "msg", None) or exc) or "this pattern is not valid"
        raise PatternError(message[0].upper() + message[1:], exc.pos) from None


def search(compiled: regex.Pattern, text: str | None) -> bool | None:
    """Whether the pattern matches anywhere in the text. None when it ran out of time."""
    try:
        return compiled.search((text or "")[:MAX_TEXT_LENGTH], timeout=MATCH_TIMEOUT_SECONDS) is not None
    except TimeoutError:
        return None


def _sample(compiled: regex.Pattern, text: str) -> SampleMatch:
    spans: list[tuple[int, int]] = []
    try:
        for match in compiled.finditer(text[:MAX_TEXT_LENGTH], timeout=MATCH_TIMEOUT_SECONDS):
            if match.end() > match.start():
                spans.append(match.span())
            elif not spans:
                # An empty match, such as a lone ^, still matches.
                spans.append(match.span())
            if len(spans) >= 20:
                break
    except TimeoutError:
        return SampleMatch(text=text, matched=False, timed_out=True)
    return SampleMatch(text=text, matched=bool(spans), spans=tuple(span for span in spans if span[1] > span[0]))


def check_pattern(pattern: str, ignore_case: bool, samples: list[str]) -> PatternCheck:
    pattern, ignore_case = split_inline_ignore_case(pattern, ignore_case)
    try:
        compiled = compile_pattern(pattern, ignore_case)
    except PatternError as exc:
        return PatternCheck(pattern=pattern, ignore_case=ignore_case, error=str(exc), error_position=exc.position)
    return PatternCheck(
        pattern=pattern, ignore_case=ignore_case, samples=[_sample(compiled, text) for text in samples],
    )
