"""Shared steps of the profile tables' bulk edit: what the chosen profiles are set to now, and the skipped ones."""
from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Callable, Iterable, TypeVar

from fastapi import HTTPException
from pydantic import ValidationError
from pydantic.alias_generators import to_camel

from backend.api.models.profile_bulk import (
    BulkFieldSummaryRead,
    BulkSkippedRead,
    BulkSummaryRead,
    BulkValueCountRead,
    BulkChangesIn,
)

ItemT = TypeVar("ItemT")


def _plain(value):
    return value.value if isinstance(value, Enum) else value


def summarize(
    items: list[ItemT],
    changes_model: type[BulkChangesIn],
    offers: Callable[[ItemT, str], bool],
) -> BulkSummaryRead:
    """For each setting the bulk edit can change: how many of ``items`` have it, and their values now."""
    fields: dict[str, BulkFieldSummaryRead] = {}
    for name in changes_model.model_fields:
        having = [item for item in items if offers(item, name)]
        counts = Counter(_plain(getattr(item, name)) for item in having)
        fields[to_camel(name)] = BulkFieldSummaryRead(
            offered=len(having),
            values=[BulkValueCountRead(value=value, count=count) for value, count in counts.most_common()],
        )
    return BulkSummaryRead(count=len(items), fields=fields)


def offered_changes(changes: BulkChangesIn, item, offers: Callable[[object, str], bool]) -> dict:
    """The changes that apply to ``item``, leaving out settings it does not have."""
    return {
        name: getattr(changes, name)
        for name in changes.model_fields_set
        if offers(item, name)
    }


def reason_of(error: Exception) -> str:
    """Why one profile could not be changed, as the user reads it."""
    if isinstance(error, HTTPException):
        if isinstance(error.detail, list):
            return " ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in error.detail)
        return str(error.detail)
    if isinstance(error, ValidationError):
        message = error.errors()[0]["msg"]
        return message.removeprefix("Value error, ")
    return str(error)


def skipped(item_id: int, name: str, reason: str) -> BulkSkippedRead:
    return BulkSkippedRead(id=item_id, name=name, reason=reason)


def in_order(ids: Iterable[int], items: Iterable[ItemT], id_of: Callable[[ItemT], int]) -> list[ItemT]:
    """``items`` in the order of ``ids``, so results read in the order the user chose them."""
    by_id = {id_of(item): item for item in items}
    return [by_id[item_id] for item_id in dict.fromkeys(ids) if item_id in by_id]
