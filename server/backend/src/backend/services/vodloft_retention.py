"""Release unowned representations without interpreting an unavailable mount as loss."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from backend.db import get_session
from backend.db.models.vodloft import (AcquisitionJob, Artifact, ArtifactPlacement,
    MediaDemand, MediaServerExport, PlaybackSession)
from config import get_settings


def reconcile(*, grace_hours: int = 24) -> int:
    root = Path(get_settings().download_settings.download_root).resolve()
    if not root.is_dir() or not (root / "vodloft").is_dir():
        return 0
    removed = 0
    with get_session() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=grace_hours)
        artifacts = session.scalars(select(Artifact).where(Artifact.profile_id.is_not(None))).all()
        for artifact in artifacts:
            if artifact.created_at.replace(tzinfo=timezone.utc) > cutoff:
                continue
            if session.scalar(select(PlaybackSession.id).where(
                PlaybackSession.item_id == artifact.item_id,
                PlaybackSession.transport == "file",
                PlaybackSession.expires_at > datetime.now(timezone.utc))):
                continue
            path = Path(artifact.path).resolve()
            if not path.is_relative_to(root / "vodloft"):
                continue
            placements = session.scalars(select(ArtifactPlacement).where(
                ArtifactPlacement.artifact_id == artifact.id)).all()
            if any(not Path(p.path).resolve().is_relative_to(root) for p in placements):
                continue
            def required(profile_id: int | None) -> bool:
                return bool(profile_id is not None and (
                    session.scalar(select(MediaDemand.id).where(
                        MediaDemand.item_id == artifact.item_id,
                        MediaDemand.profile_id == profile_id)) or
                    session.scalar(select(AcquisitionJob.id).where(
                        AcquisitionJob.item_id == artifact.item_id,
                        AcquisitionJob.profile_id == profile_id,
                        AcquisitionJob.active_key.is_not(None)))))
            # The database record remains if unlink fails; the next sweep can
            # retry. Feed enclosures are separate immutable published copies.
            try:
                for placement in placements:
                    if required(placement.profile_id):
                        continue
                    Path(placement.path).unlink(missing_ok=True)
                    session.execute(delete(MediaServerExport).where(
                        MediaServerExport.placement_id == placement.id))
                    session.delete(placement)
                if required(artifact.profile_id) or any(required(p.profile_id) for p in placements):
                    session.commit()
                    continue
                path.unlink(missing_ok=True)
            except OSError:
                session.rollback()
                continue
            session.delete(artifact)
            session.commit()
            removed += 1
    return removed
