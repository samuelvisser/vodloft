from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.db.models import Episode, Collection
from backend.db.models.media_download import EpisodeMediaDownload


@dataclass(frozen=True)
class EpisodeDownloadScope:
    """Reusable SQL-backed selection of episode MediaDownloads."""

    collection: Collection
    episode: Episode | None
    downloads: tuple[EpisodeMediaDownload, ...]
    _session: Session = field(repr=False, compare=False)
    _local_media_profile_id: int | None = field(default=None, repr=False, compare=False)
    _artifact_statuses: frozenset[str] | None = field(default=None, repr=False, compare=False)
    _filtered_download_ids: frozenset[int] | None = field(default=None, repr=False, compare=False)

    @staticmethod
    def _downloads(
            s: Session,
            *,
            collection_id: int,
            episode_id: int | None,
            local_media_profile_id: int | None,
            artifact_statuses: frozenset[str] | None,
    ) -> tuple[EpisodeMediaDownload, ...]:
        stmt = (
            select(EpisodeMediaDownload)
            .options(joinedload(EpisodeMediaDownload.local_media_profile))
            .join(Episode, Episode.id == EpisodeMediaDownload.media_item_id)
            .where(Episode.collection_id == collection_id)
        )
        if episode_id is not None:
            stmt = stmt.where(Episode.id == episode_id)
        if local_media_profile_id is not None:
            stmt = stmt.where(
                EpisodeMediaDownload.local_media_profile_id
                == local_media_profile_id
            )
        if artifact_statuses is not None:
            stmt = stmt.where(
                EpisodeMediaDownload.artifact_status.in_(artifact_statuses)
            )
        return tuple(
            s.scalars(stmt.order_by(EpisodeMediaDownload.id.asc()))
        )

    @classmethod
    def resolve(
            cls,
            s: Session,
            *,
            collection_id: int | None = None,
            episode_id: int | None = None,
            local_media_profile_id: int | None = None,
            artifact_statuses: Collection[str] | None = None,
    ) -> EpisodeDownloadScope:
        if (collection_id is None) == (episode_id is None):
            raise ValueError("Provide exactly one collection id or episode id")

        episode: Episode | None = None
        if episode_id is not None:
            episode = s.get(Episode, episode_id)
            if episode is None:
                raise ValueError(f"Episode {episode_id} no longer exists")
            collection = episode.collection
        else:
            collection = s.get(Collection, collection_id)
            if collection is None:
                raise ValueError(f"Collection {collection_id} no longer exists")

        accepted_statuses = (
            frozenset(artifact_statuses)
            if artifact_statuses is not None
            else None
        )
        downloads = cls._downloads(
            s,
            collection_id=collection.id,
            episode_id=episode.id if episode is not None else None,
            local_media_profile_id=local_media_profile_id,
            artifact_statuses=accepted_statuses,
        )
        return cls(
            collection=collection,
            episode=episode,
            downloads=downloads,
            _session=s,
            _local_media_profile_id=local_media_profile_id,
            _artifact_statuses=accepted_statuses,
        )

    @property
    def local_media_profile_ids(self) -> tuple[int, ...]:
        return tuple(sorted({download.local_media_profile_id for download in self.downloads}))

    @property
    def local_media_profile_count(self) -> int:
        return len(self.local_media_profile_ids)

    @property
    def episode_ids(self) -> tuple[int, ...]:
        return tuple(sorted({download.media_item_id for download in self.downloads}))

    def select(
            self,
            *,
            local_media_profile_id: int | None = None,
            artifact_statuses: Collection[str] | None = None,
            episode_ids: Collection[int] | None = None,
            media_download_ids: Collection[int] | None = None,
    ) -> EpisodeDownloadScope:
        """Return this scope narrowed in SQL by profile, artifact, episode, or download IDs."""
        selected_profile_id = (
            local_media_profile_id
            if local_media_profile_id is not None
            else self._local_media_profile_id
        )
        selected_statuses = (
            frozenset(artifact_statuses)
            if artifact_statuses is not None
            else self._artifact_statuses
        )
        if episode_ids is not None or media_download_ids is not None:
            selected_episode_ids = frozenset(episode_ids) if episode_ids is not None else None
            selected_download_ids = frozenset(media_download_ids) if media_download_ids is not None else None
            downloads = tuple(download for download in self.downloads
                if (selected_episode_ids is None or download.media_item_id in selected_episode_ids)
                and (selected_download_ids is None or download.id in selected_download_ids)
            )
            return replace(
                self,
                downloads=downloads,
                _filtered_download_ids=frozenset(download.id for download in downloads),
            )

        if (
            selected_profile_id == self._local_media_profile_id
            and selected_statuses == self._artifact_statuses
        ):
            return self

        downloads = self._downloads(
            self._session,
            collection_id=self.collection.id,
            episode_id=self.episode.id if self.episode is not None else None,
            local_media_profile_id=selected_profile_id,
            artifact_statuses=selected_statuses,
        )
        if self._filtered_download_ids is not None:
            downloads = tuple(
                download for download in downloads
                if download.id in self._filtered_download_ids
            )
        return replace(
            self,
            downloads=downloads,
            _local_media_profile_id=selected_profile_id,
            _artifact_statuses=selected_statuses,
        )

    def result_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "collection_id": self.collection.id,
            "collection_slug": self.collection.slug,
            "collection_title": self.collection.title,
            "local_media_profiles": self.local_media_profile_count,
        }
        if self.episode is not None:
            data.update({
                "episode_id": self.episode.id,
                "episode_slug": self.episode.slug,
                "episode_title": self.episode.title,
            })
        return data
