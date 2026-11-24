from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Protocol, Tuple, TYPE_CHECKING, TypeVar, assert_never

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.types.download_profile_types import EpIdType
from backend.types.episode_types import EpisodeExtraType
from backend.types.season_types import SeasonType
from backend.types.collection_types import EpisodeIdentifier
from backend.utils.episode import EpisodeIdentifierInfo
from sources import Feature, get_source
from ..general import datetime_to_string

if TYPE_CHECKING:
    from backend.db.models import Collection, Episode, Season


logger = logging.getLogger(__name__)

type IdentifierMaxValues = Dict[str, int]


class NumberedEpisode(Protocol):
    """What numbering an episode takes from its Source: the Source's own episode number, as The Daily Wire gives
    one ("2460.10" is episode 2460, segment 10), whether it is a trailer, and when it was published."""

    @property
    def slug(self) -> str: ...

    @property
    def published_date(self) -> datetime: ...

    @property
    def ep_number(self) -> int | None: ...

    @property
    def ep_segment(self) -> int: ...

    @property
    def trailer(self) -> bool: ...


R = TypeVar("R", bound=NumberedEpisode)
type EpisodeWithIdentifier[R] = Tuple[str, R]


@dataclass(frozen=True)
class EpisodeNumbering:
    """An episode's numbering facts, read from a Source's record or from what VODLoft stored of it."""

    slug: str
    published_date: datetime
    ep_number: int | None = None
    ep_segment: int = 0
    trailer: bool = False

    @classmethod
    def from_number_text(
            cls, slug: str, published_date: datetime, number_text: str | None, *, trailer: bool = False,
    ) -> "EpisodeNumbering":
        """From a Source's episode number as text: "2460.10" is episode 2460, segment 10; no number gives None."""
        whole, _, fraction = (number_text or "").strip().partition(".")
        number = int(whole) if whole.isdigit() else None
        segment = int(fraction) if number is not None and fraction.isdigit() else 0
        return cls(slug=slug, published_date=published_date, ep_number=number, ep_segment=segment, trailer=trailer)

    @classmethod
    def of_episode(cls, episode: "Episode") -> "EpisodeNumbering":
        """What VODLoft stored: the Source's episode number, and whether the episode is a trailer."""
        info = _identifier_info(episode.episode_identifier)
        trailer = info is not None and (
            info.type == EpIdType.TRAILER
            or (info.type == EpIdType.EP_EXTRA and info.extra_type == EpisodeExtraType.TRAILER)
        )
        published = episode.published_date or episode.went_live_date or episode.scheduled_date or episode.created_at
        return cls.from_number_text(episode.slug, published, episode.source_number, trailer=trailer)

# The Daily Wire uses .01-.19 for content attached to an episode. Segment .20
# and above is collection-level auxiliary content and must use VODLoft's collection-global
# AUX/TRAILER namespace instead of an episode-extra identifier.
_COLLECTION_AUX_SEGMENT_START = 20


def is_episode_trailer(ep: NumberedEpisode) -> bool:
    return ep.trailer


def identify_episodes_in_season(
    episode_identifier: EpisodeIdentifier,
    season_eps: List[R],
    current_values: IdentifierMaxValues | None = None,
    season: Optional["Season"] = None,
    *,
    occupied_identifiers: set[str] | None = None,
) -> Tuple[List[EpisodeWithIdentifier[R]], IdentifierMaxValues]:
    """Assign canonical identifiers without using episode-number high-water marks.

    The Source's complete episode number (The Daily Wire gives one) is authoritative for normal episodes
    and attached episode extras. VODLoft only allocates its own collection-global
    counters for standalone trailers and auxiliary content.
    """
    values = dict(current_values or {})
    occupied = occupied_identifiers if occupied_identifiers is not None else set()
    occupied_source_slots = _occupied_source_slots(occupied)
    for episode_type, counter_key in (
        (EpIdType.AUX, "ep_id.latest_aux_num"),
        (EpIdType.TRAILER, "ep_id.latest_trailer_num"),
    ):
        occupied_max = _max_generated_identifier(occupied, episode_type)
        if counter_key in values or occupied_max:
            values[counter_key] = max(
                int(values.get(counter_key, 0)),
                occupied_max,
            )

    match episode_identifier:
        case EpisodeIdentifier.DATE_BASED:
            return _get_episode_identifier_map_date_based(
                season_eps,
                values,
                occupied,
                occupied_source_slots,
                season=season,
            )
        case EpisodeIdentifier.NUMBERED:
            return _get_episode_identifier_map_numbered(
                season_eps,
                values,
                occupied,
                occupied_source_slots,
                season=season,
            )
        case EpisodeIdentifier.SEASONAL:
            if season is None:
                raise ValueError("Seasonal identification requires the local season")
            return _get_episode_identifier_map_seasonal(
                season_eps,
                values,
                occupied,
                occupied_source_slots,
                season=season,
            )
        case _:
            assert_never(episode_identifier)


def _identifier_info(identifier: str) -> EpisodeIdentifierInfo | None:
    try:
        return EpisodeIdentifierInfo.from_identifier(identifier)
    except ValueError:
        return None


def _occupied_source_slots(occupied: set[str]) -> set[str]:
    slots: set[str] = set()
    for identifier in occupied:
        info = _identifier_info(identifier)
        if info is not None and info.source_slot is not None:
            slots.add(info.source_slot)
    return slots


def _max_generated_identifier(occupied: set[str], episode_type: EpIdType) -> int:
    maximum = 0
    for identifier in occupied:
        info = _identifier_info(identifier)
        if info is None or info.type != episode_type or info.episode_number is None:
            continue
        try:
            maximum = max(maximum, int(info.episode_number))
        except ValueError:
            continue
    return maximum


def _reserve_generated_identifier(
    episode_type: EpIdType,
    values: IdentifierMaxValues,
    occupied: set[str],
) -> str:
    counter_key = (
        "ep_id.latest_trailer_num"
        if episode_type is EpIdType.TRAILER
        else "ep_id.latest_aux_num"
    )
    if counter_key in values:
        current = int(values[counter_key])
    else:
        current = _max_generated_identifier(occupied, episode_type)
    while True:
        current += 1
        identifier = f"{episode_type}.{current}"
        if identifier not in occupied:
            values[counter_key] = current
            occupied.add(identifier)
            return identifier


def _reserve_direct_or_aux(
    candidate: str,
    *,
    ep: NumberedEpisode,
    values: IdentifierMaxValues,
    occupied: set[str],
    occupied_source_slots: set[str],
) -> str:
    info = EpisodeIdentifierInfo.from_identifier(candidate)
    source_slot = info.source_slot
    if candidate not in occupied and (
        source_slot is None or source_slot not in occupied_source_slots
    ):
        occupied.add(candidate)
        if source_slot is not None:
            occupied_source_slots.add(source_slot)
        return candidate

    logger.warning(
        "The Daily Wire source slot %s for episode %s is already occupied; "
        "classifying the duplicate as auxiliary content",
        source_slot or candidate,
        ep.slug,
    )
    return _reserve_generated_identifier(EpIdType.AUX, values, occupied)


def _is_extra_season(season: Optional["Season"]) -> bool:
    return bool(season is not None and season.season_type == SeasonType.EXTRA.value)


def _normal_season_number(season: "Season") -> int:
    number = int(season.season_number)
    if number < 1:
        raise ValueError(
            f"Normal season {season.slug!r} has invalid media season number {number}"
        )
    return number


def _standalone_identifier(
    ep: NumberedEpisode,
    *,
    values: IdentifierMaxValues,
    occupied: set[str],
) -> str:
    return _reserve_generated_identifier(
        EpIdType.TRAILER if is_episode_trailer(ep) else EpIdType.AUX,
        values,
        occupied,
    )


def _get_episode_identifier_map_numbered(
    season_eps: List[R],
    current_values: IdentifierMaxValues,
    occupied: set[str],
    occupied_source_slots: set[str],
    *,
    season: Optional["Season"],
) -> Tuple[List[EpisodeWithIdentifier[R]], IdentifierMaxValues]:
    mapped: list[EpisodeWithIdentifier[R]] = []

    for ep in season_eps:
        ep_num = ep.ep_number
        segment = ep.ep_segment
        trailer = is_episode_trailer(ep)

        if _is_extra_season(season) or ep_num is None:
            identifier = _standalone_identifier(
                ep,
                values=current_values,
                occupied=occupied,
            )
        elif segment == 0:
            if trailer:
                identifier = _reserve_generated_identifier(
                    EpIdType.TRAILER,
                    current_values,
                    occupied,
                )
            else:
                identifier = _reserve_direct_or_aux(
                    f"{EpIdType.EP}.{ep_num}",
                    ep=ep,
                    values=current_values,
                    occupied=occupied,
                    occupied_source_slots=occupied_source_slots,
                )
        elif 0 < segment < _COLLECTION_AUX_SEGMENT_START:
            extra_type = (
                EpisodeExtraType.TRAILER
                if trailer
                else EpisodeExtraType.OTHER
            )
            identifier = _reserve_direct_or_aux(
                f"{EpIdType.EP_EXTRA}.{extra_type}.{ep_num}.{segment}",
                ep=ep,
                values=current_values,
                occupied=occupied,
                occupied_source_slots=occupied_source_slots,
            )
        else:
            identifier = _standalone_identifier(
                ep,
                values=current_values,
                occupied=occupied,
            )

        mapped.append((identifier, ep))

    return mapped, current_values


def _get_episode_identifier_map_seasonal(
    season_eps: List[R],
    current_values: IdentifierMaxValues,
    occupied: set[str],
    occupied_source_slots: set[str],
    *,
    season: "Season",
) -> Tuple[List[EpisodeWithIdentifier[R]], IdentifierMaxValues]:
    mapped: list[EpisodeWithIdentifier[R]] = []
    season_number = (
        0 if _is_extra_season(season) else _normal_season_number(season)
    )

    for ep in season_eps:
        ep_num = ep.ep_number
        segment = ep.ep_segment
        trailer = is_episode_trailer(ep)

        if _is_extra_season(season) or ep_num is None:
            identifier = _standalone_identifier(
                ep,
                values=current_values,
                occupied=occupied,
            )
        elif segment == 0:
            if trailer:
                identifier = _reserve_generated_identifier(
                    EpIdType.TRAILER,
                    current_values,
                    occupied,
                )
            else:
                identifier = _reserve_direct_or_aux(
                    f"{EpIdType.EP}.S{season_number:02d}E{ep_num:02d}",
                    ep=ep,
                    values=current_values,
                    occupied=occupied,
                    occupied_source_slots=occupied_source_slots,
                )
        elif 0 < segment < _COLLECTION_AUX_SEGMENT_START:
            extra_type = (
                EpisodeExtraType.TRAILER
                if trailer
                else EpisodeExtraType.OTHER
            )
            identifier = _reserve_direct_or_aux(
                (
                    f"{EpIdType.EP_EXTRA}.{extra_type}."
                    f"S{season_number:02d}E{ep_num:02d}.{segment}"
                ),
                ep=ep,
                values=current_values,
                occupied=occupied,
                occupied_source_slots=occupied_source_slots,
            )
        else:
            identifier = _standalone_identifier(
                ep,
                values=current_values,
                occupied=occupied,
            )

        mapped.append((identifier, ep))

    return mapped, current_values


def _get_episode_identifier_map_date_based(
    season_eps: List[R],
    current_values: IdentifierMaxValues,
    occupied: set[str],
    occupied_source_slots: set[str],
    *,
    season: Optional["Season"],
) -> Tuple[List[EpisodeWithIdentifier[R]], IdentifierMaxValues]:
    mapped: list[EpisodeWithIdentifier[R]] = []
    last_ep_date = int(current_values.get("ep_id.latest_ep_date", 0))

    for ep in season_eps:
        if _is_extra_season(season) or is_episode_trailer(ep):
            identifier = _standalone_identifier(
                ep,
                values=current_values,
                occupied=occupied,
            )
        else:
            ep_date = int(ep.published_date.timestamp())
            candidate = f"{EpIdType.EP}.{datetime_to_string(ep.published_date)}"
            if last_ep_date < ep_date and candidate not in occupied:
                last_ep_date = ep_date
                occupied.add(candidate)
                identifier = candidate
            else:
                identifier = _reserve_generated_identifier(
                    EpIdType.AUX,
                    current_values,
                    occupied,
                )
        mapped.append((identifier, ep))

    current_values["ep_id.latest_ep_date"] = last_ep_date
    return mapped, current_values


def next_identifier(identifiers: set[str], prefix: str) -> str:
    """The next free ``<prefix>.<number>`` after the highest one the collection has."""
    numbers = [
        int(identifier.removeprefix(f"{prefix}."))
        for identifier in identifiers
        if identifier.startswith(f"{prefix}.") and identifier.removeprefix(f"{prefix}.").isdigit()
    ]
    return f"{prefix}.{max(numbers, default=0) + 1}"


def counts_own_numbers(collection: "Collection") -> bool:
    """Whether VODLoft counts the collection's episodes itself, as for a Source that lists its videos without
    episode numbers; otherwise the Source's own episode numbers decide them, as The Daily Wire's do."""
    return get_source(collection.source_key).has(Feature.EPISODE_LISTS)


def _generated_type_for_record(
    identifier_type: EpisodeIdentifier,
    season: "Season",
    numbering: NumberedEpisode,
) -> EpIdType | None:
    if _is_extra_season(season):
        return EpIdType.TRAILER if is_episode_trailer(numbering) else EpIdType.AUX

    if identifier_type is EpisodeIdentifier.DATE_BASED:
        return EpIdType.TRAILER if is_episode_trailer(numbering) else None

    if numbering.ep_number is None:
        return EpIdType.TRAILER if is_episode_trailer(numbering) else EpIdType.AUX

    segment = numbering.ep_segment
    if identifier_type in {EpisodeIdentifier.NUMBERED, EpisodeIdentifier.SEASONAL}:
        if segment == 0 and is_episode_trailer(numbering):
            return EpIdType.TRAILER
        if segment >= _COLLECTION_AUX_SEGMENT_START:
            return (
                EpIdType.TRAILER
                if is_episode_trailer(numbering)
                else EpIdType.AUX
            )
        return None

    return None


def keeps_generated_identifier(
    identifier_type: EpisodeIdentifier,
    season: "Season",
    numbering: NumberedEpisode,
    identifier: str,
) -> bool:
    """Whether the episode keeps the trailer or auxiliary number VODLoft counted for it, because under this
    identification it is still one."""
    generated_type = _generated_type_for_record(identifier_type, season, numbering)
    info = _identifier_info(identifier)
    return generated_type is not None and info is not None and info.type == generated_type


def _listed_identifier(s: Session, episode: "Episode", numbering: NumberedEpisode) -> str | None:
    """The identifier a main episode of a collection VODLoft counts itself gets for its publication date, or None
    when it keeps its own. Only a date-based one follows its date: a numbered or seasonal one keeps the number it
    was counted, and its other tags count on their own."""
    from backend.db.models import Episode

    collection = episode.collection
    if collection.episode_identifier != EpisodeIdentifier.DATE_BASED.value or episode.part_of is not None:
        return None
    if not (episode.episode_identifier or "").startswith(f"{EpIdType.EP}."):
        return None
    identifier = f"{EpIdType.EP}.{datetime_to_string(numbering.published_date)}"
    if episode.episode_identifier == identifier:
        return None
    identifiers = set(s.scalars(select(Episode.episode_identifier).where(
        Episode.collection_id == collection.id, Episode.id != episode.id,
    )))
    return next_identifier(identifiers, EpIdType.AUX) if identifier in identifiers else identifier


def _counter_values(collection: "Collection") -> IdentifierMaxValues:
    return {
        item.key: int(item.value)
        for item in collection.meta_items
        if item.key in {
            "ep_id.latest_aux_num",
            "ep_id.latest_trailer_num",
            "ep_id.latest_ep_date",
        }
    }


def _source_numbered_identifier(
    s: Session, episode: "Episode", numbering: NumberedEpisode,
) -> tuple[str, IdentifierMaxValues] | None:
    """The identifier the Source's own numbering gives the episode, with the counters it moved; None when it keeps
    its own."""
    from backend.db.models import Episode

    identifier_type = EpisodeIdentifier(episode.collection.episode_identifier)
    season = episode.season
    if season is None:
        return None
    if keeps_generated_identifier(identifier_type, season, numbering, episode.episode_identifier):
        return None

    occupied = set(
        s.scalars(
            select(Episode.episode_identifier).where(
                Episode.collection_id == episode.collection_id,
                Episode.id != episode.id,
            )
        )
    )
    [mapped], updated_values = identify_episodes_in_season(
        identifier_type,
        [numbering],
        _counter_values(episode.collection),
        season=season,
        occupied_identifiers=occupied,
    )
    desired, _ = mapped

    generated_type = _generated_type_for_record(identifier_type, season, numbering)
    current_info = _identifier_info(episode.episode_identifier)
    desired_info = _identifier_info(desired)
    if (
        generated_type is None
        and current_info is not None
        and current_info.type == EpIdType.AUX
        and desired_info is not None
        and desired_info.type == EpIdType.AUX
    ):
        # A direct source slot is occupied by another record. The episode already has an identifier in the
        # collection-global AUX namespace, so keep that stable AUX identity rather than allocating a fresh counter.
        return None
    return desired, updated_values


def refresh_episode_identifier(
    s: Session,
    episode: "Episode",
    numbering: NumberedEpisode,
) -> bool:
    """Give one episode the identifier its Source's refreshed details call for, on any Site: the Source's own
    episode number and trailer flag where it numbers its episodes, and the publication date for a date-based
    collection. Returns whether it changed."""
    from backend.db.models import Episode

    if counts_own_numbers(episode.collection):
        desired = _listed_identifier(s, episode, numbering)
        updated_values: IdentifierMaxValues = {}
    else:
        found = _source_numbered_identifier(s, episode, numbering)
        desired, updated_values = found if found is not None else (None, {})
    if desired is None or desired == episode.episode_identifier:
        return False

    collision = s.scalar(
        select(Episode.id)
        .where(
            Episode.collection_id == episode.collection_id,
            Episode.episode_identifier == desired,
            Episode.id != episode.id,
        )
        .limit(1)
    )
    if collision is not None:
        logger.warning(
            "Cannot refresh episode %s identifier %s -> %s; identifier is already "
            "used by episode %s",
            episode.id,
            episode.episode_identifier,
            desired,
            collision,
        )
        return False

    old_identifier = episode.episode_identifier
    episode.episode_identifier = desired
    for key in ("ep_id.latest_aux_num", "ep_id.latest_trailer_num", "ep_id.latest_ep_date"):
        if key in updated_values:
            episode.collection.set_meta(key, str(updated_values[key]))

    s.flush()
    logger.info(
        "Refreshed episode %s identifier %s -> %s from its Source's details",
        episode.id,
        old_identifier,
        desired,
    )
    return True
