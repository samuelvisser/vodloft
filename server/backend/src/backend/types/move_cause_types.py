from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional, Union

MoveCauseValue = Union[str, list[str], None]
"""A setting's value as it is stored: an option, a set of refs such as feeds, or None for a default such as every feed."""


class MoveCauseOrigin(StrEnum):
    """Where the settings that put a collection's downloads in another season are changed. Each origin reads its own
    settings (``backend.services.move_causes.READERS``) and the UI shows them in its own words."""

    SEASONS = "seasons"
    """The collection's Seasons dialog."""


@dataclass(frozen=True)
class MoveCause:
    """One setting change that put downloads of a collection in another season, which wait for its Move action: the
    setting as it was before the first change and as it is now."""

    origin: MoveCauseOrigin
    setting: str
    """The setting, by the name its origin knows it by, such as loose_videos."""
    before: MoveCauseValue
    after: MoveCauseValue
    subject_id: Optional[int] = None
    """For a setting of one thing in the collection, such as one of its lists: that thing's id."""
    subject_title: Optional[str] = None
    """And its title, as it was when the setting changed."""

    @property
    def key(self) -> tuple[str, str, Optional[int]]:
        return self.origin.value, self.setting, self.subject_id
