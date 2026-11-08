"""SQL for the search box and chips of the profile tables."""
from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, true
from sqlalchemy.sql.elements import ColumnElement

from backend.api.models.profile_list import FormatKind, ProfileStatus
from backend.types.local_media_profile_types import PreferredFormat


def search_words(search: str) -> list[str]:
    return search.lower().split()


def matches_words(words: list[str], *fields: ColumnElement[Any]) -> ColumnElement[bool]:
    """Every word appears in at least one of ``fields``, ignoring case."""
    return and_(true(), *(
        or_(*(func.lower(field).contains(word, autoescape=True) for field in fields))
        for word in words
    ))


def matches_format(preferred_format: ColumnElement[str], kinds: list[FormatKind]) -> ColumnElement[bool]:
    is_audio = preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
    if set(kinds) in (set(), set(FormatKind)):
        return true()
    return is_audio if kinds[0] == FormatKind.AUDIO else ~is_audio


def matches_status(enabled: ColumnElement[bool], statuses: list[ProfileStatus]) -> ColumnElement[bool]:
    if set(statuses) in (set(), set(ProfileStatus)):
        return true()
    return enabled.is_(statuses[0] == ProfileStatus.ENABLED)


def matches_any(clauses: list[ColumnElement[bool]]) -> ColumnElement[bool]:
    """Any of ``clauses``; no clauses means the filter is off."""
    return or_(*clauses) if clauses else true()


def scope_of(query: Any) -> dict[str, Any]:
    """The filters as a cursor stores them, with each list sorted."""
    return {
        key: sorted(value) if isinstance(value, list) else value
        for key, value in query.model_dump(mode="json", exclude={"cursor", "limit"}).items()
    }
