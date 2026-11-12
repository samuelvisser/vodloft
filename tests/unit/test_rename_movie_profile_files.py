from __future__ import annotations

from datetime import date
from pathlib import Path

from conftest import use_database
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

PLEX_TEMPLATE = (
    "{% set plex_year = ' (' ~ movie_year ~ ')' if movie_year else '' %}"
    "/downloads/Movies/{{ movie_title }}{{ plex_year }}/{{ movie_title }}{{ plex_year }}"
    "{% if media_type != 'movie' %}-{{ media_type }}{% endif %}.ext"
)


def _session() -> tuple[Session, object]:
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    return Session(engine), engine


def _movie(slug: str, title: str):
    from backend.db.models import Movie
    from backend.types.media_types import MediaType

    return Movie(
        source_key="dailywire", uuid=f"{slug}-uuid", type=MediaType.MOVIE.value, slug=slug,
        title=title, description=None, duration=100, release_date=date(2020, 1, 1),
    )


def _extra(movie, slug: str, title: str, extra_type: str):
    from backend.db.models import MovieExtra
    from backend.types.media_types import MediaType

    return MovieExtra(
        source_key="dailywire", uuid=f"{movie.slug}-{slug}-uuid", type=MediaType.MOVIE_EXTRA.value, movie=movie,
        movie_extra_type=extra_type, slug=slug, title=title, description=None, duration=10,
    )


def _download(session: Session, profile, media, path: Path, content: bytes):
    from backend.db.models.media_download import MovieExtraMediaDownload, MovieMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType
    from downloader.storage.identity import inspect_artifact

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    identity = inspect_artifact(path)
    model = MovieMediaDownload if media.type == MediaType.MOVIE.value else MovieExtraMediaDownload
    download = model(
        type=media.type, media_item_id=media.id, local_media_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.AVAILABLE.value, file_path=str(path),
        artifact_stat_dev=identity.stat_dev, artifact_stat_ino=identity.stat_ino,
        artifact_size_bytes=identity.size_bytes, artifact_fingerprint=identity.fingerprint,
    )
    session.add(download)
    return download


def _library(session: Session, tmp_path: Path, template: str):
    from backend.db.models import MovieLocalMediaProfile

    profile = MovieLocalMediaProfile(
        slug="movie-to-plex", name="Movie to Plex", preferred_format="format_1080p",
        output_template=template,
    )
    film, sequel = _movie("film", "Film"), _movie("sequel", "Sequel")
    # Two extras of one type in one movie, and one extra shared by both movies.
    clip_a, clip_b = _extra(film, "clip-a", "Clip A", "clip"), _extra(film, "clip-b", "Clip B", "clip")
    shared_film, shared_sequel = _extra(film, "shared", "Shared", "trailer"), _extra(sequel, "shared", "Shared", "trailer")
    session.add_all([profile, film, sequel, clip_a, clip_b, shared_film, shared_sequel])
    session.flush()
    old = tmp_path / "old"
    for name, media in [
        ("film.mp4", film), ("sequel.mp4", sequel), ("clip-a.mp4", clip_a), ("clip-b.mp4", clip_b),
        ("shared-film.mp4", shared_film), ("shared-sequel.mp4", shared_sequel),
    ]:
        _download(session, profile, media, old / name, name.encode())
    session.commit()
    return profile


def _paths(session: Session) -> dict[str, str]:
    from backend.db.models.media_download import MediaDownloadBase

    session.expire_all()
    return {Path(row.file_path).name: Path(row.file_path).read_bytes().decode() for row in session.scalars(select(MediaDownloadBase))}


def test_movie_rename_numbers_extras_that_share_a_name(monkeypatch, tmp_path):
    from config import get_settings
    from task_manager.tasks.workers.rename_movie_profile_files.service import run_rename_movie_profile_files

    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    session, engine = _session()
    try:
        profile = _library(session, tmp_path, PLEX_TEMPLATE)

        result = run_rename_movie_profile_files(local_media_profile_id=profile.id)

        assert result.data["files_renamed"] == 6
        assert _paths(session) == {
            "Film (2020).mp4": "film.mp4",
            "Sequel (2020).mp4": "sequel.mp4",
            "Film (2020)-clip.mp4": "clip-a.mp4",
            "Film (2020)-clip-1.mp4": "clip-b.mp4",
            "Film (2020)-trailer.mp4": "shared-film.mp4",
            "Sequel (2020)-trailer.mp4": "shared-sequel.mp4",
        }

        again = run_rename_movie_profile_files(local_media_profile_id=profile.id)
        assert again.data["files_renamed"] == 0
    finally:
        session.close()
        engine.dispose()


def test_movie_rename_keeps_the_number_a_file_already_has(monkeypatch, tmp_path):
    from config import get_settings
    from backend.db.models.media_download import MediaDownloadBase
    from task_manager.tasks.workers.rename_movie_profile_files.service import run_rename_movie_profile_files

    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    session, engine = _session()
    try:
        profile = _library(session, tmp_path, PLEX_TEMPLATE)
        run_rename_movie_profile_files(local_media_profile_id=profile.id)
        # Only the folder changes: each clip keeps its number.
        profile = session.get(type(profile), profile.id)
        profile.output_template = profile.output_template.replace("/Movies/", "/Films/")
        session.commit()

        run_rename_movie_profile_files(local_media_profile_id=profile.id)

        paths = _paths(session)
        assert paths["Film (2020)-clip.mp4"] == "clip-a.mp4"
        assert paths["Film (2020)-clip-1.mp4"] == "clip-b.mp4"
        assert all("/Films/" in row.file_path for row in session.scalars(select(MediaDownloadBase)))
    finally:
        session.close()
        engine.dispose()


def test_shared_destination_skips_a_number_an_unrelated_file_has(tmp_path):
    from backend.services.download_relocation import number_shared_destinations

    taken = tmp_path / "Film-clip.mp4"
    taken.write_bytes(b"not ours")
    a, b = tmp_path / "old" / "a.mp4", tmp_path / "old" / "b.mp4"

    assert number_shared_destinations([(a, taken), (b, taken)]) == [
        tmp_path / "Film-clip-1.mp4", tmp_path / "Film-clip-2.mp4",
    ]
