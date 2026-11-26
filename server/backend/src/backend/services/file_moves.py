"""Whether the downloaded files of an episode move when it changes season: each file's path is rendered from its Local
Media Profile's template for the episode in its new season, with its new number, and compared with its path now. Only
a file whose path changes moves; the others stay where they are."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from backend.db.models import Episode
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.download_options import effective_filename_mode
from backend.services.season_state import EpisodeDraft, SeasonDraft, SeasonsState
from backend.types.collection_types import EpisodeIdentifier
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from backend.utils.episode import EpisodeIdentifierInfo
from backend.utils.output_template import (
    episode_output_template_values, output_template_custom_index_keys, output_template_fields,
    resolve_episode_output_path_with_index_values,
)

@dataclass(frozen=True)
class FileMove:
    """One downloaded file that gets another path."""

    download_id: int
    episode_id: int
    from_path: str
    to_path: str | None
    """The path it gets, or None when only moving it tells, such as with a custom index."""


_ON_DISK = (MediaDownloadArtifactStatus.AVAILABLE.value, MediaDownloadArtifactStatus.CORRUPTED.value)
_SEASONAL = re.compile(r"^ep\.S(\d+)E(.*)$")
# A Music profile's album and track come from the album's place among the artist's albums, which a move changes in
# ways the path of one file does not show: a template that names them moves its files with their season.
_TRACK_FIELDS = frozenset({"album", "track_number", "track_number_padded"})


def number_in(state: SeasonsState, identifier: str | None, season: SeasonDraft) -> str | None:
    """The number an episode has in ``season``, as a move gives it: a seasonal number takes its new season's."""
    if state.collection.episode_identifier != EpisodeIdentifier.SEASONAL.value:
        return identifier
    match = _SEASONAL.match(identifier or "")
    return f"ep.S{season.season_number:02d}E{match.group(2)}" if match else identifier


class FileMoves:
    """The downloaded files of the planner's copy of a collection, to tell which of them a change of season moves."""

    def __init__(self, state: SeasonsState, s: Session | None = None):
        self._state = state
        self._s = s or object_session(state.record)
        self._downloads: dict[int, list[EpisodeMediaDownload]] | None = None

    def _of(self, episode_id: int) -> list[EpisodeMediaDownload]:
        if self._downloads is None:
            self._downloads = {}
            for download in self._s.scalars(
                select(EpisodeMediaDownload).join(Episode, Episode.id == EpisodeMediaDownload.media_item_id).where(
                    Episode.collection_id == self._state.record.id, EpisodeMediaDownload.artifact_status.in_(_ON_DISK),
                )
            ):
                self._downloads.setdefault(download.media_item_id, []).append(download)
        return self._downloads.get(episode_id, [])

    def moving(self, episode: EpisodeDraft, season: SeasonDraft, identifier: str | None) -> list[FileMove]:
        """The episode's downloads that get another path in ``season`` with ``identifier`` than where the episode as
        saved puts them."""
        downloads = self._of(episode.id)
        if not downloads:
            return []
        record = self._s.get(Episode, episode.id)
        was = episode_output_template_values(record)
        info = EpisodeIdentifierInfo.from_identifier(identifier or "")
        now = {
            **was,
            "season": season.slug, "season_name": season.name, "season_index": str(season.index),
            "season_type": season.season_type, "season_number": str(season.season_number),
            "album_slug": season.slug, "album_number": str(season.season_number),
            "episode_identifier": identifier or "", "episode_type": info.type or "",
            "episode_extra_type": info.extra_type or "", "episode_number": info.episode_number or "",
            "episode_sub_number": info.sub_episode_number or "", "episode_label": info.label,
        }
        season_changed = record.season_id != season.id
        return [move for download in downloads if (move := self._move(download, was, now, season_changed)) is not None]

    @staticmethod
    def _move(
        download: EpisodeMediaDownload, was: dict[str, str], now: dict[str, str], season_changed: bool,
    ) -> FileMove | None:
        def unknown() -> FileMove:
            return FileMove(download.id, download.media_item_id, download.file_path or "", None)

        profile = download.local_media_profile
        template = profile.output_template if profile is not None else None
        if not template:
            return unknown()
        try:
            if output_template_custom_index_keys(template):
                # A custom index may count by season, which only numbering the whole collection again tells.
                return unknown()
            if season_changed and output_template_fields(template) & _TRACK_FIELDS:
                return unknown()
            mode = effective_filename_mode(profile)
            extension = Path(download.file_path).suffix.removeprefix(".") if download.file_path else None

            def path(values: dict[str, str]) -> Path:
                return resolve_episode_output_path_with_index_values(
                    template, episode=download.media, index_definitions=frozenset(), index_values={},
                    filename_mode=mode, extension=extension, values=values,
                )

            before, after = path(was), path(now)
        except Exception:
            # A template that does not render says nothing: its files move, so nothing is left behind.
            return unknown()
        if before == after:
            return None
        return FileMove(download.id, download.media_item_id, download.file_path or str(before), str(after))
