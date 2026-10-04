"""Recover the gap between a file rename and its database transaction."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select

from backend.db import get_session
from backend.db.models.vodloft import AcquisitionJob, Artifact, ArtifactPlacement, FileFinalization
from config import get_settings


def prepare(job_id: int, destination: Path, output: Path | None) -> None:
    with get_session() as session:
        job = session.get(AcquisitionJob, job_id)
        occupied = session.scalar(select(ArtifactPlacement).where(
            ArtifactPlacement.path == str(output))) if output else None
        if occupied:
            old_artifact = session.get(Artifact, occupied.artifact_id)
            if occupied.profile_id != job.profile_id or old_artifact.item_id != job.item_id:
                raise ValueError("Output path belongs to another media item or profile")
        journal = session.scalar(select(FileFinalization).where(FileFinalization.job_id == job_id))
        if journal:
            raise ValueError("This download has an unreconciled finalization")
        session.add(FileFinalization(job_id=job_id, destination=str(destination),
            placement_path=str(output) if output else None,
            previous_artifact_id=occupied.artifact_id if occupied else None,
            phase="prepared"))
        session.commit()


def advance(job_id: int, phase: str) -> None:
    with get_session() as session:
        journal = session.scalar(select(FileFinalization).where(FileFinalization.job_id == job_id))
        journal.phase = phase
        session.commit()


def _same_bytes(first: Path, second: Path) -> bool:
    if first.stat().st_size != second.stat().st_size:
        return False
    def digest(path):
        hash_value = hashlib.sha256()
        with path.open("rb") as source:
            for part in iter(lambda: source.read(1024 * 1024), b""):
                hash_value.update(part)
        return hash_value.digest()
    return digest(first) == digest(second)


def reconcile(job_id: int | None = None) -> None:
    root = Path(get_settings().download_settings.download_root).resolve()
    # An unmounted library must never be interpreted as intentionally empty.
    if not root.is_dir():
        return
    with get_session() as session:
        query = select(FileFinalization)
        if job_id is not None:
            query = query.where(FileFinalization.job_id == job_id)
        for journal in session.scalars(query).all():
            destination = Path(journal.destination).resolve()
            output = Path(journal.placement_path).resolve() if journal.placement_path else None
            if not destination.is_relative_to(root / "vodloft") or output and not output.is_relative_to(root):
                raise ValueError("Invalid finalization path in the journal")
            if session.scalar(select(Artifact.id).where(Artifact.path == journal.destination)):
                session.delete(journal)
                continue
            existing = session.scalar(select(ArtifactPlacement).where(
                ArtifactPlacement.path == journal.placement_path)) if output else None
            if output and output.is_file() and destination.is_file() and _same_bytes(output, destination):
                if journal.previous_artifact_id and existing:
                    old_artifact = session.get(Artifact, journal.previous_artifact_id)
                    if not old_artifact or not Path(old_artifact.path).is_file():
                        # The old source or volume may be temporarily unavailable.
                        continue
                    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".restore-", delete=False) as temporary:
                        with Path(old_artifact.path).open("rb") as source:
                            shutil.copyfileobj(source, temporary)
                        temporary_path = Path(temporary.name)
                    os.replace(temporary_path, output)
                elif not existing:
                    output.unlink()
            if destination.is_file():
                destination.unlink()
            session.delete(journal)
        session.commit()
