"""The one place that decides an episode's identifier, for every Source.

An identifier follows the collection's episode identification, and with it the numbers media servers and podcast
apps see and the names files get:

- Date-based: a main episode is its publication date and time, ``ep.2024-05-02T20:00:00.000000``.
- Numbered: a main episode is the next number across the collection, ``ep.12``. On a Site with ``show_numbers``,
  such as The Daily Wire, it is the Site's own number for it, ``ep.2460``, and a video it gives no number is
  auxiliary.
- Seasonal: a main episode is its number in its season, ``ep.S02E05``: the Source's own number in the season when it
  has one, and otherwise the next one there.

Only episodes with the Source's main tag follow that scheme. An extra that belongs to an episode
(``VideoDetails.extra_number``, as The Daily Wire's 2460.10) is numbered by that episode: ``ep-extra.other.2460.10``,
or ``ep-extra.other.S02E2460.10`` by season; by date it is dated like an episode, and a trailer of it is a trailer.
Every other tag counts on its own across the collection: ``trailer.1``, ``aux.2``, ``short.3``. A main episode whose
identifier is already taken, such as a second video of the same moment, is auxiliary.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.types.collection_types import EpisodeIdentifier
from backend.types.download_profile_types import EpIdType
from backend.types.episode_types import EpisodeExtraType
from backend.utils.episode import EpisodeIdentifierInfo
from sources import MAIN_TAG, Site, Source, VideoDetails
from task_manager.tasks.helpers.general import datetime_to_string

_TRAILER = "trailer"


@dataclass(frozen=True)
class Numbering:
    """What decides an episode's identifier: its tag, when it came out, and where its Source's own numbering puts it."""

    published: datetime
    tag: str = MAIN_TAG
    number: int | None = None
    """The Source's own episode number (``VideoDetails.episode_number``)."""
    extra: int | None = None
    """Its number as an extra of episode ``number`` (``VideoDetails.extra_number``)."""

    @classmethod
    def of_video(cls, details: VideoDetails, fallback: datetime, *, sources_season: bool = True) -> "Numbering":
        """``sources_season`` False: the video goes to a season VODLoft makes itself, such as one per upload year,
        which has no numbers of the Source's."""
        number = details.episode_number if sources_season else None
        return cls(
            published=details.published_at or fallback, tag=details.tag, number=number,
            extra=details.extra_number if number is not None else None,
        )

    @classmethod
    def of_stored(cls, source: Source, identifier: str | None, number_text: str | None, published: datetime) -> "Numbering":
        """What an episode VODLoft has was numbered from: its tag, from its identifier, and its Source's number, from
        the number the Source wrote (``Episode.source_number``)."""
        number, extra = source.numbers_of(number_text) if number_text else (None, None)
        prefix = (identifier or EpIdType.EP.value).partition(".")[0]
        info = _info(identifier)
        trailer = prefix == _TRAILER or (info is not None and info.extra_type == EpisodeExtraType.TRAILER)
        if extra is not None and number is not None:
            # An extra of an episode, which a date-based collection dated like one.
            return cls(published=published, tag=_TRAILER if trailer else EpIdType.EP_EXTRA.value, number=number, extra=extra)
        tag = MAIN_TAG if prefix in {EpIdType.EP.value, EpIdType.EP_EXTRA.value} else prefix
        return cls(published=published, tag=tag, number=number)

    @property
    def main(self) -> bool:
        return self.tag == MAIN_TAG and self.extra is None


class SeasonSlot(Protocol):
    """The season an episode is numbered in."""

    id: int
    season_number: int


class TakesNumbers(Protocol):
    def take(self, season, wanted: int | None) -> int:
        """The episode number ``wanted`` in ``season``, or the next free one there when it has none or it is taken."""


class CountedNumbers:
    """Episode numbers by season, counted from what ``identifiers`` already use, for numbering all of a collection's
    episodes again."""

    def __init__(self, identifiers: set[str]):
        self._taken: dict[int, set[int]] = defaultdict(set)
        for identifier in identifiers:
            info = _info(identifier)
            if info is not None and info.type == EpIdType.EP and info.season_number is not None and info.episode_number:
                self._taken[info.season_number].add(int(info.episode_number))

    def take(self, season, wanted: int | None) -> int:
        taken = self._taken[season.season_number]
        number = wanted if wanted is not None and wanted not in taken else max(taken, default=0) + 1
        taken.add(number)
        return number


def next_identifier(identifiers: set[str], prefix: str) -> str:
    """The next free ``<prefix>.<number>`` after the highest one the collection has."""
    numbers = [
        int(identifier.removeprefix(f"{prefix}."))
        for identifier in identifiers
        if identifier.startswith(f"{prefix}.") and identifier.removeprefix(f"{prefix}.").isdigit()
    ]
    return f"{prefix}.{max(numbers, default=0) + 1}"


def dated(published: datetime) -> str:
    return f"{EpIdType.EP}.{datetime_to_string(published)}"


def follows_facts(identification: EpisodeIdentifier, site: Site, numbering: Numbering) -> bool:
    """Whether the identifier follows from what the Source says about the episode, its date or the Source's own
    number for it, rather than from a count of VODLoft's, such as a trailer's number or a numbered collection's own."""
    if numbering.extra is not None:
        return numbering.tag != _TRAILER or identification is not EpisodeIdentifier.DATE_BASED
    if not numbering.main:
        return False
    match identification:
        case EpisodeIdentifier.DATE_BASED:
            return True
        case EpisodeIdentifier.NUMBERED:
            return site.show_numbers and numbering.number is not None
        case EpisodeIdentifier.SEASONAL:
            return numbering.number is not None


def identify(
    identification: EpisodeIdentifier, site: Site, season: SeasonSlot, numbering: Numbering, taken: set[str],
    numbers: TakesNumbers,
) -> str:
    """The identifier ``numbering`` gives an episode in ``season``, among the ``taken`` ones of its collection. It is
    added to ``taken``."""
    identifier = _identifier(identification, site, season, numbering, taken, numbers)
    taken.add(identifier)
    return identifier


def _identifier(
    identification: EpisodeIdentifier, site: Site, season: SeasonSlot, numbering: Numbering, taken: set[str],
    numbers: TakesNumbers,
) -> str:
    if numbering.extra is not None:
        return _extra(identification, season, numbering, taken)
    if numbering.tag != MAIN_TAG:
        return next_identifier(taken, numbering.tag)
    match identification:
        case EpisodeIdentifier.DATE_BASED:
            return _free_or_aux(dated(numbering.published), taken)
        case EpisodeIdentifier.NUMBERED:
            if not site.show_numbers:
                return next_identifier(taken, EpIdType.EP)
            if numbering.number is None:
                # A Site numbers its episodes itself, so a video it gives no number is no episode of the show.
                return next_identifier(taken, EpIdType.AUX)
            return _free_or_aux(f"{EpIdType.EP}.{numbering.number}", taken)
        case EpisodeIdentifier.SEASONAL:
            return f"{EpIdType.EP}.S{season.season_number:02d}E{numbers.take(season, numbering.number):02d}"


def _extra(identification: EpisodeIdentifier, season: SeasonSlot, numbering: Numbering, taken: set[str]) -> str:
    trailer = numbering.tag == _TRAILER
    if identification is EpisodeIdentifier.DATE_BASED:
        # By date an extra is dated like an episode; a trailer of an episode is a trailer.
        return next_identifier(taken, _TRAILER) if trailer else _free_or_aux(dated(numbering.published), taken)
    episode = (
        f"S{season.season_number:02d}E{numbering.number:02d}" if identification is EpisodeIdentifier.SEASONAL
        else str(numbering.number)
    )
    slots = {f"{EpIdType.EP_EXTRA}.{kind}.{episode}.{numbering.extra}" for kind in EpisodeExtraType}
    if slots & taken:
        # A trailer and another extra of the same number are one place in the Source's numbering.
        return next_identifier(taken, EpIdType.AUX)
    kind = EpisodeExtraType.TRAILER if trailer else EpisodeExtraType.OTHER
    return f"{EpIdType.EP_EXTRA}.{kind}.{episode}.{numbering.extra}"


def _free_or_aux(identifier: str, taken: set[str]) -> str:
    return next_identifier(taken, EpIdType.AUX) if identifier in taken else identifier


def _info(identifier: str | None) -> EpisodeIdentifierInfo | None:
    try:
        return EpisodeIdentifierInfo.from_identifier(identifier)
    except ValueError:
        return None
