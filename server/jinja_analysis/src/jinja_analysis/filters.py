"""What the analysis knows about the filters a template can use, in one table.

This is not a template-language restriction: a template may use any filter its
environment defines. The table only says which filters the analysis can reason
about when it moves, copies or prints an expression, and what they return.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ValueType = Literal["str", "int", "float"]


@dataclass(frozen=True)
class FilterRule:
    pure: bool = True
    """The same input always gives the same output, with no side effects, so an
    expression using it may be moved, copied or evaluated a different number of times."""
    result: ValueType | Literal["same"] | None = None
    """What it returns: a type, "same" for the type of its input, or None when unknown."""
    total_for: frozenset[ValueType] = frozenset()
    """Input types it never fails on when called without arguments."""


_STR = frozenset({"str"})
_INT = frozenset({"int"})

FILTERS: dict[str, FilterRule] = {
    "abs": FilterRule(result="same", total_for=_INT),
    "as_typed": FilterRule(result="str", total_for=frozenset({"str", "int"})),
    "capitalize": FilterRule(result="str", total_for=_STR),
    "float": FilterRule(result="float"),
    "format": FilterRule(result="str"),
    "int": FilterRule(result="int", total_for=_INT),
    "length": FilterRule(result="int"),
    "lower": FilterRule(result="str", total_for=_STR),
    "regex_groups": FilterRule(),
    "regex_replace": FilterRule(result="str"),
    "regex_search": FilterRule(),
    "replace": FilterRule(result="str"),
    "round": FilterRule(),
    "strftime": FilterRule(result="str"),
    "string": FilterRule(result="str", total_for=frozenset({"str", "int"})),
    "title": FilterRule(result="str", total_for=_STR),
    "trim": FilterRule(result="str", total_for=_STR),
    "upper": FilterRule(result="str", total_for=_STR),
    # Context-dependent: the value depends on more than the input.
    "custom_index": FilterRule(pure=False, result="int"),
    "random": FilterRule(pure=False),
}

PURE_FILTERS = frozenset(name for name, rule in FILTERS.items() if rule.pure)
VOLATILE_FILTERS = frozenset(name for name, rule in FILTERS.items() if not rule.pure)
STRING_FILTERS = frozenset(name for name, rule in FILTERS.items() if rule.result == "str" and rule.pure)


def filter_result(name: str, value_type: ValueType | None, *, has_arguments: bool) -> ValueType | None:
    """The type a known-total filter returns for a value of ``value_type``, or None."""
    rule = FILTERS.get(name)
    if rule is None or not rule.pure or has_arguments or value_type not in rule.total_for:
        return None
    return value_type if rule.result == "same" else rule.result
