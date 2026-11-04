from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import Field

from backend.api.models.base import RequestBase, ResponseBase
from backend.api.models.collection_example import ExampleCollectionAPIIn
from backend.services.regex_check import MAX_PATTERN_LENGTH


class RegexSampleField(StrEnum):
    TITLE = "title"
    DESCRIPTION = "description"


class RegexCheckRequest(RequestBase):
    pattern: str = Field(max_length=MAX_PATTERN_LENGTH * 2)
    ignore_case: bool = False
    samples: list[str] = Field(default_factory=list, max_length=50, description="Your own test texts")
    collection_id: Optional[int] = Field(default=None, description="Also test on this Collection's indexed episodes")
    example_collection: Optional[ExampleCollectionAPIIn] = Field(
        default=None, description="Or on the newest episodes of this collection that is not saved yet",
    )
    field: RegexSampleField = RegexSampleField.TITLE


class RegexSampleRead(ResponseBase):
    text: str
    matched: bool
    spans: list[tuple[int, int]]
    timed_out: bool
    own: bool
    published_at: Optional[datetime] = None


class RegexCheckRead(ResponseBase):
    pattern: str = Field(description="The pattern without a leading (?i), which became ignoreCase")
    ignore_case: bool
    valid: bool
    error: Optional[str] = None
    error_position: Optional[int] = None
    samples: list[RegexSampleRead]
    collection_total: int = Field(description="How many of the Collection's episodes were tested")
    collection_matches: int
