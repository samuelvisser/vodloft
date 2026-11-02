from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time

from jinja2 import StrictUndefined, pass_context
from jinja2.exceptions import TemplateRuntimeError
from jinja2.sandbox import ImmutableSandboxedEnvironment


def _compile_regex(pattern: object) -> re.Pattern[str]:
    try:
        return re.compile(str(pattern))
    except re.error as exc:
        raise TemplateRuntimeError(f"Invalid regular expression: {exc}") from exc


def regex_replace(
    value: object,
    pattern: object,
    replacement: object,
    count: int = 0,
) -> str:
    """Replace regex matches in a Jinja value; count=0 replaces every match."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise TemplateRuntimeError("regex_replace count must be a non-negative integer")

    regex = _compile_regex(pattern)
    try:
        return regex.sub(str(replacement), str(value), count=count)
    except re.error as exc:
        raise TemplateRuntimeError(f"Invalid regular expression replacement: {exc}") from exc


def regex_search(value: object, pattern: object) -> bool:
    """Return whether a regex matches anywhere in a Jinja value."""
    return _compile_regex(pattern).search(str(value)) is not None


def regex_groups(value: object, pattern: object) -> list[str]:
    """The groups of the first regex match in a Jinja value, or an empty list.

    A group that did not take part in the match is an empty string.
    """
    match = _compile_regex(pattern).search(str(value))
    if match is None:
        return []
    return [group or "" for group in match.groups()]


def _parse_strftime_value(value: object) -> date | datetime | time | None:
    """Parse the canonical date/time strings exposed to output templates."""
    if isinstance(value, (datetime, date, time)):
        return value

    text = str(value)
    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return time.fromisoformat(text)
    except ValueError:
        pass

    raise TemplateRuntimeError(
        "strftime requires a VODLoft date/time value in ISO format"
    )


def strftime(value: object, format_string: object) -> str:
    """Format a VODLoft date/time value with Python strftime directives."""
    parsed = _parse_strftime_value(value)
    if parsed is None:
        return ""

    try:
        return parsed.strftime(str(format_string))
    except (TypeError, ValueError, OSError) as exc:
        raise TemplateRuntimeError(f"Invalid strftime format: {exc}") from exc


CustomIndexGroup = str | tuple[str, ...]
CustomIndexResolver = Callable[[str, CustomIndexGroup], object]


def custom_index_group(per: object) -> CustomIndexGroup:
    """The counter a Custom Index uses for one episode: one per value of per=.

    A list groups by all its items together. Without per= every episode shares one counter.
    """
    if per is None:
        return ()
    if isinstance(per, (list, tuple)):
        return tuple(str(item) for item in per)
    return str(per)


class TypedText(str):
    """A value to name files with as if it were typed into the template (see ``as_typed``)."""


def as_typed(value: object) -> TypedText:
    """Use a value as typed text: the filename mode cleans it like the template's own text.

    In Restricted mode that keeps its spaces and punctuation, as Pinchflat does for a
    source's custom name. It still can't add a folder level. Use it as the last filter.
    """
    return TypedText("" if value is None else value)


def create_output_template_environment(
    *,
    custom_index_resolver: CustomIndexResolver | None = None,
) -> ImmutableSandboxedEnvironment:
    """Create VODLoft's isolated sandbox for Local Media Profile path templates."""
    environment = ImmutableSandboxedEnvironment(
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    # Path templates only need explicitly supplied media values. Removing globals
    # also keeps helpers such as range() unavailable to user templates.
    environment.globals.clear()
    @pass_context
    def custom_index(
        context, value: object, per: object = None, start: int = 1, step: int = 1,
    ) -> object:
        # custom_index is deliberately context-dependent. Marking it this way
        # prevents Jinja from constant-folding literal filter calls while
        # compiling the template, which would otherwise evaluate dead branches
        # and allocate indexes that the rendered path never reaches. Prepared
        # templates may provide a per-render resolver through the private
        # context key so one compiled Jinja template can be reused safely.
        for name, number in (("start", start), ("step", step)):
            if isinstance(number, bool) or not isinstance(number, int):
                raise TemplateRuntimeError(f"custom_index {name}= must be a whole number")
        if step == 0:
            raise TemplateRuntimeError("custom_index step= cannot be 0")
        resolver = context.get("__vodloft_custom_index_resolver") or custom_index_resolver
        if resolver is None:
            return ""
        # The resolver hands out ordinals 1, 2, 3...; start= and step= only change how they read.
        ordinal = resolver(str(value), custom_index_group(per))
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            return ordinal
        return start + (ordinal - 1) * step

    environment.filters.update({
        "regex_replace": regex_replace,
        "regex_search": regex_search,
        "regex_groups": regex_groups,
        "strftime": strftime,
        "custom_index": custom_index,
        "as_typed": as_typed,
    })
    return environment
