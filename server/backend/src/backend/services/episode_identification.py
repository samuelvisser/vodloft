"""Changing how a collection numbers its episodes: by date, by number, or by season and episode.

The identification decides each episode's identifier, and with it the numbers media servers and podcast apps see and
the names Local Media Profiles give its files. Changing it gives every main episode the identifier it would have had if
the collection had numbered it that way from the start, by the same rules indexing uses:

- A Source that numbers its own episodes, such as The Daily Wire, keeps its numbers: "2460.10" stays episode 2460's
  tenth extra, now as S03E2460 or 2460 instead of a date. VODLoft's own trailer and auxiliary numbers stay where they
  still apply.
- For a Source VODLoft counts the episodes of itself (``Feature.EPISODE_LISTS``), the episodes are counted again in the
  order they were published, or within each season; a playlist season then follows the playlist's order. Videos of
  other kinds (Shorts and the like) and the parts of a video split by its chapters keep their numbers.

It runs as an operation (``CollectionIdentificationChangeOperation``), so the collection page shows its progress: the
new identifiers are written in one short write transaction, then each Local Media Profile's files move to their new
names and get their new metadata.
"""
from __future__ import annotations

from backend.utils.helpers import name_in_text
from collections import defaultdict
from collections.abc import Container, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, CollectionLocalMediaProfile, DownloadProfile, Episode, Season
from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadBase
from backend.operations.collections import CollectionIdentificationChangeOperation, CollectionRenumberOperation
from backend.services.download_options import effective_metadata_mode
from backend.services.episode_filters import (
    EpisodeSelection, evaluate, filter_leaving_out, retention_downloads, retention_removes,
)
from backend.services.errors import ServiceError
from backend.services.link_seasons import numbered_in_list_order
from backend.services.season_order import number_lists
from backend.services.season_state import EpisodeDraft, SeasonsState, apply_state, load_state
from backend.services.sites import collection_words
from backend.types import work_weights
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.types.download_profile_types import EpIdType, MediaDownloadArtifactStatus
from backend.types.local_media_profile_types import PreferredFormat
from backend.types.season_types import SeasonType
from backend.utils.episode import EpisodeIdentifierInfo
from backend.utils.output_template import output_template_fields
from config.settings.submodels import MetadataMode
from downloader.plan import EMBEDS_METADATA
from progress_plan import StageSpec
from task_manager.scheduler.db import TaskOperation
from task_manager.scheduler.operation_factory import create_operation
from task_manager.scheduler.operations import queue_operation_target_dispatch
from task_manager.scheduler.types import OperationStatus
from task_manager.tasks.helpers.episodes.identifier import (
    EpisodeNumbering, IdentifierMaxValues, counts_own_numbers, identify_episodes_in_season,
    keeps_generated_identifier, next_identifier,
)
from task_manager.tasks.helpers.general import datetime_to_string

_FIELD = "episodeIdentifier"
_ACTIVE = (OperationStatus.QUEUED.value, OperationStatus.RUNNING.value, OperationStatus.WAITING.value)
# Work on the collection that reads or writes its episodes' numbers or files while it runs.
_BUSY_KINDS = (
    "collection.index", "collection.sync", "collection.rename_files", "collection.rewrite_metadata",
    "collection.change_identification", "collection.renumber", "collection.download_all", "collection.redownload_episodes",
    "collection.delete_downloads",
)
_PHYSICAL = (
    MediaDownloadArtifactStatus.AVAILABLE.value,
    MediaDownloadArtifactStatus.MISSING.value,
    MediaDownloadArtifactStatus.CORRUPTED.value,
)
_ON_DISK = (MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value)
# Output template values that come from an episode's identifier: a profile that uses one names files by it.
_IDENTIFIER_FIELDS = frozenset({
    "episode_identifier", "episode_label", "episode_number", "episode_sub_number", "episode_type",
    "episode_extra_type",
})
_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class IdentificationPlan:
    """The identifier each episode gets under the new identification."""

    identification: EpisodeIdentifier
    identifiers: dict[int, str]
    """Episode id -> its new identifier, for the episodes whose identifier changes."""
    counters: IdentifierMaxValues = field(default_factory=dict)
    """VODLoft's own trailer, auxiliary and date counters, for a Source that numbers its episodes."""


@dataclass(frozen=True)
class IdentificationChange:
    """One episode that gets a new identifier."""

    title: str
    before: str
    after: str


@dataclass(frozen=True)
class ProfileFilesChange:
    """What the change does to one Local Media Profile's files."""

    name: str
    files_renamed: int
    metadata_rewritten: int
    """Files whose tags or NFO are written again: every downloaded file of a profile that keeps metadata."""


@dataclass(frozen=True)
class DownloadProfileChange:
    """What the change does to what one Download Profile downloads and keeps."""

    name: str
    removed: int
    """Downloads on disk its cleanup would delete, which it would not have before."""
    no_longer_wanted: int
    """Other downloads on disk its filters would leave out; they stay until someone deletes them."""
    newly_wanted: int
    """Episodes it would download that it does not download now."""


@dataclass(frozen=True)
class IdentificationPreview:
    identification: EpisodeIdentifier
    episodes: int
    episodes_renumbered: int
    changes: list[IdentificationChange]
    """Every episode that gets a new identifier, newest first."""
    become_auxiliary: int
    """Main episodes that get an auxiliary number, because their Source gives them none under this identification."""
    profiles: list[ProfileFilesChange]
    download_profiles: list[DownloadProfileChange]
    busy: str | None
    """Why the change can't start now, such as downloads of the collection that are running."""


def _episodes(state: SeasonsState) -> list[EpisodeDraft]:
    return state.in_index_order()


def _published(episode) -> datetime:
    return episode.published_date or episode.went_live_date or episode.scheduled_date or episode.created_at or _EARLIEST


def _season_order(state: SeasonsState, episode: EpisodeDraft) -> tuple[int, int]:
    season = state.season(episode.season_id)
    return (season.index if season is not None else 0), (season.id if season is not None else 0)


def _tag(identifier: str | None) -> str:
    return (identifier or "").partition(".")[0]


def plan_identification(state: SeasonsState, identification: EpisodeIdentifier) -> IdentificationPlan:
    """The identifiers the copy's episodes get under ``identification``. Changes nothing."""
    collection = state.collection
    episodes = _episodes(state)
    if counts_own_numbers(collection):
        identifiers, counters = _plan_counted(state, identification, in_list_order=numbered_in_list_order(collection)), {}
    else:
        identifiers, counters = _plan_source_numbered(state, identification)
    return IdentificationPlan(
        identification=identification,
        identifiers={
            episode.id: identifiers[episode.id] for episode in episodes
            if episode.id in identifiers and identifiers[episode.id] != episode.episode_identifier
        },
        counters=counters,
    )


def number_episodes(state: SeasonsState, identification: EpisodeIdentifier) -> IdentificationPlan:
    """Number the copy's episodes under ``identification``, as saving it does: the plan's identifiers, then, by
    season, each playlist season in the playlist's order. ``state.changed_identifiers()`` then tells every episode
    whose identifier changed."""
    plan = plan_identification(state, identification)
    for episode_id, identifier in plan.identifiers.items():
        state.episodes[episode_id].episode_identifier = identifier
    state.collection.episode_identifier = identification.value
    if identification is EpisodeIdentifier.SEASONAL:
        # A playlist season numbers its videos in the playlist's order, as it does when they are added.
        number_lists(state)
    return plan


def save_numbers(s: Session, state: SeasonsState, plan: IdentificationPlan) -> None:
    """Save the copy numbered by ``number_episodes``, with the counters its plan keeps.

    ``s`` is a write transaction's session."""
    apply_state(s, state)
    for key, value in plan.counters.items():
        state.record.set_meta(key, str(value))
    s.flush()


def _plan_counted(state: SeasonsState, identification: EpisodeIdentifier, *, in_list_order: bool) -> dict[int, str]:
    """Count the main episodes again, as indexing counts the videos of a Source without episode numbers. Other tags,
    and the parts of a split video, keep theirs. ``in_list_order`` numbers them in the order they were added, which is
    their list's order for a collection made from one list, rather than by date."""
    episodes = _episodes(state)
    main = [
        episode for episode in episodes
        if episode.part_of is None and _tag(episode.episode_identifier) in {EpIdType.EP.value, EpIdType.AUX.value}
    ]
    moving = {episode.id for episode in main}
    taken = {episode.episode_identifier for episode in episodes if episode.id not in moving}
    identifiers: dict[int, str] = {}
    match identification:
        case EpisodeIdentifier.DATE_BASED:
            for episode in sorted(main, key=lambda episode: (_published(episode), episode.index, episode.id)):
                identifier = f"{EpIdType.EP}.{datetime_to_string(_published(episode))}"
                # Two videos published at the same moment: the second one is auxiliary.
                identifier = next_identifier(taken, EpIdType.AUX) if identifier in taken else identifier
                taken.add(identifier)
                identifiers[episode.id] = identifier
        case EpisodeIdentifier.NUMBERED:
            for episode in sorted(main, key=lambda episode: (
                (episode.index, episode.id) if in_list_order else (_published(episode), episode.index, episode.id)
            )):
                identifier = next_identifier(taken, EpIdType.EP)
                taken.add(identifier)
                identifiers[episode.id] = identifier
        case EpisodeIdentifier.SEASONAL:
            numbers: dict[int, int] = defaultdict(int)
            for episode in sorted(main, key=lambda episode: (_season_order(state, episode), episode.index, episode.id)):
                season = state.season(episode.season_id)
                if season is None:
                    continue
                while True:
                    numbers[season.id] += 1
                    identifier = f"{EpIdType.EP}.S{season.season_number:02d}E{numbers[season.id]:02d}"
                    if identifier not in taken:
                        break
                taken.add(identifier)
                identifiers[episode.id] = identifier
    return identifiers


def _plan_source_numbered(
        state: SeasonsState, identification: EpisodeIdentifier,
) -> tuple[dict[int, str], IdentifierMaxValues]:
    """Give each episode what the Source's own numbering gives it under ``identification``, season by season in the
    order indexing goes. A trailer or auxiliary number VODLoft counted stays where it still applies."""
    episodes = _episodes(state)
    numbering = {episode.id: EpisodeNumbering.of_episode(episode) for episode in episodes}
    moving: list[EpisodeDraft] = []
    taken: set[str] = set()
    for episode in episodes:
        season = state.season(episode.season_id)
        if season is None or episode.part_of is not None or keeps_generated_identifier(
            identification, season, numbering[episode.id], episode.episode_identifier,
        ):
            taken.add(episode.episode_identifier)
        else:
            moving.append(episode)
    by_season: dict[int, list[EpisodeDraft]] = defaultdict(list)
    for episode in moving:
        by_season[episode.season_id].append(episode)
    identifiers: dict[int, str] = {}
    values: IdentifierMaxValues = {}
    for season_episodes in sorted(by_season.values(), key=lambda items: _season_order(state, items[0])):
        season = state.season(season_episodes[0].season_id)
        if (
            identification is EpisodeIdentifier.SEASONAL and season.season_type != SeasonType.EXTRA.value
            and season.season_number < 1
        ):
            raise ServiceError(
                f"Season {season.name} has no season number, so its episodes can't be numbered by season",
                field=_FIELD,
            )
        ordered = sorted(season_episodes, key=lambda episode: (
            numbering[episode.id].published_date, numbering[episode.id].ep_number or 0,
            numbering[episode.id].ep_segment, episode.index,
        ))
        mapped, values = identify_episodes_in_season(
            identification, [numbering[episode.id] for episode in ordered], values,
            season=season, occupied_identifiers=taken,
        )
        for episode, (identifier, _numbering) in zip(ordered, mapped, strict=True):
            identifiers[episode.id] = identifier
    return identifiers, values


def _busy(s: Session, collection: Collection) -> str | None:
    return collection_busy(s, collection, "changing how its episodes are numbered")


@dataclass(frozen=True)
class CollectionWork:
    """Work on a collection that numbering its episodes again has to wait for."""

    title: str
    downloads: bool
    """Its episodes are downloading or waiting to download, rather than VODLoft working on its episodes or files,
    such as listing it again after a change."""
    operation_id: str | None = None
    """The task that works on it, when that is not downloading, so a preview that waits can show how far it is."""

    def refusal(self, doing: str) -> str:
        """Why ``doing`` it can't start now."""
        if self.downloads:
            return (
                f"Episodes of {name_in_text(self.title)} are downloading or waiting to download. "
                f"Let them finish, or cancel them, before {doing}."
            )
        return f"VODLoft is still working on {name_in_text(self.title)}. Try again once that is done."

    def waiting(self) -> str:
        """What a preview that waits for the work says while it waits."""
        if self.downloads:
            return (
                f"Episodes of {name_in_text(self.title)} are downloading or waiting to download. The changes "
                "show here once they are done, or once you cancel them."
            )
        return (
            f"VODLoft is still working on {name_in_text(self.title)}. The changes show here once that is done, as what "
            "it finds can change them."
        )


def collection_work(
    s: Session, collection: Collection, *, downloads: bool = True, besides: Sequence[str] = (),
) -> CollectionWork | None:
    """The work on the collection that numbering its episodes again waits for: its episodes are downloading, or
    VODLoft is working on its episodes or files. None when there is none. Without ``downloads`` only work on its
    episodes or files counts, and work of the kinds in ``besides`` never does."""
    if downloads:
        return _downloading(s, collection) or collection_work(s, collection, downloads=False, besides=besides)
    work = s.scalar(
        select(TaskOperation.id).where(
            TaskOperation.resource_type == "collection",
            TaskOperation.resource_id == collection.id,
            TaskOperation.kind.in_([kind for kind in _BUSY_KINDS if kind not in besides]),
            TaskOperation.status.in_(_ACTIVE),
        ).limit(1)
    )
    return CollectionWork(collection.title, downloads=False, operation_id=work) if work is not None else None


def _downloading(s: Session, collection: Collection) -> CollectionWork | None:
    downloads = s.scalar(
        select(TaskOperation.id).where(
            TaskOperation.kind == "media.download",
            TaskOperation.status.in_(_ACTIVE),
            TaskOperation.resource_id.in_(
                select(MediaDownloadBase.id).join(Episode, Episode.id == MediaDownloadBase.media_item_id)
                .where(Episode.collection_id == collection.id)
            ),
        ).limit(1)
    )
    return CollectionWork(collection.title, downloads=True) if downloads is not None else None


def collection_busy(s: Session, collection: Collection, doing: str) -> str | None:
    """Why ``doing`` something that numbers the collection's episodes again can't start now (``collection_work``).
    None when it can."""
    work = collection_work(s, collection)
    return work.refusal(doing) if work is not None else None


def _metadata_rewrites(s: Session, collection: Collection, profile: CollectionLocalMediaProfile) -> int:
    """How many of the collection's files in the profile get their metadata written again: what the metadata rewrite
    after the change writes, an NFO for each file or tags in each file that can take them."""
    mode = effective_metadata_mode(profile)
    if mode is MetadataMode.NO_METADATA:
        return 0
    paths = s.scalars(
        select(EpisodeMediaDownload.file_path)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(
            Episode.collection_id == collection.id,
            EpisodeMediaDownload.local_media_profile_id == profile.id,
            EpisodeMediaDownload.artifact_status == MediaDownloadArtifactStatus.AVAILABLE.value,
            EpisodeMediaDownload.file_path.is_not(None),
        )
    )
    if mode is not MetadataMode.EMBED:
        return sum(1 for _ in paths)
    return sum(1 for path in paths if PurePath(path).suffix.lower().removeprefix(".") in EMBEDS_METADATA)


def _profiles_with_files(s: Session, collection: Collection) -> list[int]:
    return list(s.scalars(
        select(EpisodeMediaDownload.local_media_profile_id).distinct()
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(Episode.collection_id == collection.id, EpisodeMediaDownload.artifact_status.in_(_PHYSICAL))
        .order_by(EpisodeMediaDownload.local_media_profile_id)
    ))


def identification_steps(s: Session, collection: Collection, *, renumbering: bool) -> list[StageSpec]:
    """The plan of numbering the collection's episodes again: numbering them, one write that cannot say how far it is,
    then for each Local Media Profile with files, renaming them and rewriting their metadata. Each step weighs what it
    does, so an action that numbers several collections counts each by its size."""
    episodes = collection_words(collection).episode.plural
    count = s.scalar(select(func.count(Episode.id)).where(Episode.collection_id == collection.id)) or 0
    steps = [StageSpec(
        id="number", code="number_episodes", weight=max(work_weights.DEFAULT, count * work_weights.NUMBER_EPISODE),
        label=f"Numbering the {episodes}" if renumbering else "Saving the new order",
    )]
    return steps + profile_file_steps(s, collection)


def profile_file_steps(s: Session, collection: Collection, profile_ids: Container[int] | None = None) -> list[StageSpec]:
    """Renaming each Local Media Profile's files, then rewriting their metadata, after the numbering: of every profile
    with files, or of those of ``profile_ids``. The rewriting counts what it rewrote as the profile's files are called,
    such as the tracks of a profile for an artist's sound."""
    steps = []
    for profile_id, name, files, audio in files_by_profile(s, collection.id):
        if profile_ids is None or profile_id in profile_ids:
            unit = collection_words(collection, audio=True if audio else None).episode.plural
            steps += _file_steps(profile_id, name, files, unit)
    return steps


def _file_steps(profile_id: int, name: str, files: int, unit: str) -> list[StageSpec]:
    of = f" of {name}"
    return [
        StageSpec(id=f"rename:{profile_id}", code="rename_files", label=f"Renaming the files{of}",
                  weight=max(1, files) * work_weights.MOVE_FILE, depends_on=("number",)),
        StageSpec(id=f"rewrite:{profile_id}", code="rewrite_metadata", label=f"Rewriting the metadata{of}", unit=unit,
                  weight=max(1, files) * work_weights.REWRITE_FILE, depends_on=(f"rename:{profile_id}",)),
    ]


def files_by_profile(s: Session, collection_id: int) -> list[tuple[int, str, int, bool]]:
    """Each Local Media Profile with files of the collection's episodes: its id, its name, how many files and whether
    they are sound only, for the plan of the work that renames them and rewrites their metadata."""
    return [(row.id, row.name, row.files, row.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY) for row in s.execute(
        select(
            CollectionLocalMediaProfile.id, CollectionLocalMediaProfile.name, CollectionLocalMediaProfile.preferred_format,
            func.count(EpisodeMediaDownload.id).label("files"),
        )
        .join(EpisodeMediaDownload, EpisodeMediaDownload.local_media_profile_id == CollectionLocalMediaProfile.id)
        .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
        .where(Episode.collection_id == collection_id, EpisodeMediaDownload.artifact_status.in_(_PHYSICAL))
        .group_by(CollectionLocalMediaProfile.id, CollectionLocalMediaProfile.name,
                  CollectionLocalMediaProfile.preferred_format)
        .order_by(CollectionLocalMediaProfile.id)
    )]


_KIND_NAMES = {EpIdType.TRAILER.value: "Trailer", EpIdType.AUX.value: "Auxiliary"}


def _label(identifier: str) -> str:
    """How an identifier reads to a person: S03E14, 101, 2024-05-02 20:00, or Auxiliary 3."""
    try:
        info = EpisodeIdentifierInfo.from_identifier(identifier)
    except ValueError:
        return identifier
    label = info.label or identifier
    try:
        label = datetime.fromisoformat(label).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    if info.type == EpIdType.EP_EXTRA:
        return f"{label} extra"
    if info.type in _KIND_NAMES:
        return f"{_KIND_NAMES[info.type]} {label}"
    if info.type != EpIdType.EP:
        return f"{info.type} {label}"
    return label


def preview_identification(
        s: Session, collection: Collection, identification: EpisodeIdentifier,
) -> IdentificationPreview:
    """What changing the collection's identification would do, as saving it numbers the planner's copy of the
    collection: nothing is saved."""
    busy = _busy(s, collection)
    state = load_state(s, collection)
    number_episodes(state, identification)
    changed = state.changed_identifiers()
    changes, _ = _changes(s, changed)
    become_auxiliary = sum(
        1 for before, after in changed.values()
        if _tag(after) == EpIdType.AUX.value and _tag(before) in {EpIdType.EP.value, EpIdType.EP_EXTRA.value}
    )
    return IdentificationPreview(
        identification=identification, episodes=len(state.episodes), episodes_renumbered=len(changed), changes=changes,
        become_auxiliary=become_auxiliary, profiles=profile_file_changes(s, collection, set(changed)),
        download_profiles=_download_profile_changes(s, collection, {
            episode_id: after for episode_id, (_before, after) in changed.items()
        }),
        busy=busy,
    )


def _changes(
        s: Session, changed: dict[int, tuple[str | None, str | None]],
) -> tuple[list[IdentificationChange], set[int]]:
    """The episodes that get another identifier, newest first, and their ids."""
    if not changed:
        return [], set()
    episodes = list(s.scalars(select(Episode).where(Episode.id.in_(changed))))
    newest_first = sorted(episodes, key=lambda episode: (_published(episode), episode.id), reverse=True)
    return [
        IdentificationChange(
            title=episode.title, before=_label(changed[episode.id][0]), after=_label(changed[episode.id][1]),
        )
        for episode in newest_first
    ], set(changed)


def profile_file_changes(s: Session, collection: Collection, changed_ids: set[int]) -> list[ProfileFilesChange]:
    """What giving the episodes ``changed_ids`` new numbers does to each Local Media Profile's files: the files of
    those episodes that are named by their number move, and every file gets its metadata written again."""
    profiles: list[ProfileFilesChange] = []
    for profile_id in _profiles_with_files(s, collection):
        profile = s.get(CollectionLocalMediaProfile, profile_id)
        if profile is None:
            continue
        renamed = s.scalar(select(func.count(EpisodeMediaDownload.id)).where(
            EpisodeMediaDownload.local_media_profile_id == profile_id,
            EpisodeMediaDownload.media_item_id.in_(changed_ids),
            EpisodeMediaDownload.artifact_status.in_(_PHYSICAL),
        )) if changed_ids and output_template_fields(profile.output_template) & _IDENTIFIER_FIELDS else 0
        retagged = _metadata_rewrites(s, collection, profile)
        if renamed or retagged:
            profiles.append(ProfileFilesChange(name=profile.name, files_renamed=renamed, metadata_rewritten=retagged))
    return profiles


def renumber_changes(s: Session, state: SeasonsState) -> tuple[list[IdentificationChange], set[int]]:
    """The episodes that get a new number when the collection numbers its episodes again the way it numbers them,
    as after episodes moved in or out of it: newest first, and their ids. Numbers the planner's copy, which may have
    moved episodes already, and saves nothing."""
    was = {episode.id: episode.episode_identifier for episode in state.episodes.values()}
    number_episodes(state, EpisodeIdentifier(state.collection.episode_identifier))
    return _changes(s, {
        episode.id: (was[episode.id], episode.episode_identifier) for episode in state.episodes.values()
        if episode.id > 0 and episode.id in was and was[episode.id] != episode.episode_identifier
    })


def renumbers(s: Session, collection: Collection) -> bool:
    """Whether numbering the collection's episodes again the way it numbers them changes any. Reading only."""
    state = load_state(s, collection)
    number_episodes(state, EpisodeIdentifier(collection.episode_identifier))
    return bool(state.changed_identifiers())


def queue_renumber(s: Session, collection: Collection, *, renumber: bool) -> TaskOperation:
    """Number the collection's episodes again the way it numbers them, unless ``renumber`` is False, then rename its
    files and rewrite their metadata, as after episodes moved within it. Runs as the task that changes a collection's
    identification, so the collection page shows its progress.

    ``s`` is a write transaction's session."""
    weight = sum(step.weight for step in identification_steps(s, collection, renumbering=renumber))
    operation = create_operation(s, CollectionRenumberOperation(
        collection, renumber=renumber, work_weight=weight,
    ))
    queue_operation_target_dispatch(s, operation.id, operation.targets[0].slot_key)
    s.flush()
    return operation


class _Numbered:
    """An episode as it reads with another identifier, for the filters to judge without changing it."""

    def __init__(self, episode: Episode, identifier: str):
        self._episode = episode
        self.episode_identifier = identifier

    def __getattr__(self, name):
        return getattr(self._episode, name)


def _download_profile_changes(
        s: Session, collection: Collection, identifiers: dict[int, str],
) -> list[DownloadProfileChange]:
    """What each Download Profile's filters do with the new identifiers: a filter on episode types can match other
    episodes once their type changes, such as a Daily Wire extra that is an episode when numbered by date."""
    profiles = list(s.scalars(select(DownloadProfile).where(DownloadProfile.collection_id == collection.id)))
    if not profiles or not identifiers:
        return []
    episodes = list(s.scalars(select(Episode).where(Episode.collection_id == collection.id)))
    ordered = sorted(episodes, key=lambda episode: (_published(episode), episode.id), reverse=True)
    renumbered = [
        _Numbered(episode, identifiers[episode.id]) if episode.id in identifiers else episode for episode in ordered
    ]
    before: dict[int, tuple] = {}
    after: dict[int, tuple] = {}
    downloads: dict[int, list[EpisodeMediaDownload]] = {}
    for profile in profiles:
        downloads[profile.id] = retention_downloads(s, profile)
        before[profile.id] = _judge(s, profile, ordered, downloads[profile.id])
        after[profile.id] = _judge(s, profile, renumbered, downloads[profile.id])
    changes = []
    for profile in profiles:
        wanted_before, out_before, removed_before = before[profile.id]
        wanted_after, out_after, removed_after = after[profile.id]
        removed = removed_after - removed_before
        change = DownloadProfileChange(
            name=_download_profile_name(profile),
            removed=len(removed),
            no_longer_wanted=len(out_after - out_before - removed),
            newly_wanted=len(wanted_after - wanted_before - {download.media_item_id for download in downloads[profile.id]}),
        )
        if change.removed or change.no_longer_wanted or change.newly_wanted:
            changes.append(change)
    return changes


def _judge(
        s: Session, profile: DownloadProfile, episodes: list[Episode], downloads: list[EpisodeMediaDownload],
) -> tuple[set[int], set[int], set[int]]:
    """The episodes the profile wants, its downloads on disk that its filters leave out, and the downloads on disk
    that its cleanup deletes, manual ones included when it includes them."""
    evaluation = evaluate(s, EpisodeSelection.of_profile(profile), episodes=episodes)
    on_disk = [download for download in downloads if download.artifact_status in _ON_DISK]
    out = {
        download.id for download in on_disk
        if download.download_profile_id == profile.id and filter_leaving_out(evaluation, download) is not None
    }
    removed = {
        download.id for download in on_disk
        if retention_removes(evaluation, download, delete_older_episodes=profile.delete_older_episodes)
    }
    return {episode.id for episode in evaluation.wanted}, out, removed


def _download_profile_name(profile: DownloadProfile) -> str:
    return profile.local_media_profile.name


def request_identification_change(
        s: Session, collection: Collection, identification: EpisodeIdentifier, *, episode_order: EpisodeOrder | None,
) -> TaskOperation:
    """Start numbering the collection's episodes another way, as an operation whose progress the collection page
    shows. Refuses what would go wrong before anything changes. ``s`` is a write transaction's session."""
    if EpisodeIdentifier(collection.episode_identifier) is identification:
        raise ServiceError(f"{name_in_text(collection.title)} already numbers its episodes this way", field=_FIELD)
    busy = _busy(s, collection)
    if busy is not None:
        raise ServiceError(busy, field=_FIELD)
    # Whatever stops the plan, such as a season without a number, stops it here, where the form shows why.
    plan_identification(load_state(s, collection), identification)
    operation = create_operation(s, CollectionIdentificationChangeOperation(
        collection, episode_identifier=identification.value,
        episode_order=episode_order.value if episode_order is not None else None,
    ))
    queue_operation_target_dispatch(s, operation.id, operation.targets[0].slot_key)
    s.flush()
    return operation


def change_identification(
        s: Session, collection_id: int, identification: EpisodeIdentifier, *, episode_order: EpisodeOrder | None,
        renumber: bool = True,
) -> tuple[int, list[int]]:
    """Give the collection's episodes their new identifiers: under a new identification, or again under the one it
    has, as after episodes moved in or out of it. Without ``renumber`` they keep them. Returns how many changed, and
    the Local Media Profiles whose files then move to their new names and get their new metadata.

    ``s`` is a write transaction's session."""
    collection = s.get(Collection, collection_id)
    if collection is None:
        return 0, []
    renumbered = 0
    if renumber:
        state = load_state(s, collection)
        plan = number_episodes(state, identification)
        renumbered = len(state.changed_identifiers())
        save_numbers(s, state, plan)
    if episode_order is not None:
        collection.episode_order = episode_order.value
    s.flush()
    return renumbered, _profiles_with_files(s, collection)
