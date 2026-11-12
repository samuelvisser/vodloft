from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_upcoming_movie_allows_extras_but_not_full_movie(tmp_path, monkeypatch):
    from backend.api.endpoints.media_downloads.service import (
        create_movie_download,
        create_movie_extra_download,
    )
    from backend.services import movies as movie_service
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.db.core import Base
    from backend.db.models import MovieLocalMediaProfile
    from backend.db.models.media_download import MovieExtraMediaDownload
    from config import get_settings
    from sources.dailywire.api.records import DwMovieExtraRecord, DwMovieRecord

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    monkeypatch.setattr(movie_service, "ensure_movie_release_metadata", lambda _s, _movie: None)

    profile = MovieLocalMediaProfile(
        slug="movies",
        name="Movies",
        output_template="/downloads/{{ movie_title }}/{{ slug }}.ext",
        preferred_format="format_1080p",
    )
    session.add(profile)
    session.commit()

    trailer = DwMovieExtraRecord(
        dw_id="trailer-1",
        slug="upcoming-movie-final-trailer",
        title="Upcoming Movie | Final Trailer",
        movie_extra_type="trailer",
        duration=67,
        sharing_url="https://www.dailywire.com/clips/upcoming-movie-final-trailer",
    )
    movie_data = DwMovieRecord(
        dw_id="movie-1",
        slug="upcoming-movie",
        title="Upcoming Movie | Final Trailer",
        description="Upcoming movie description.",
        duration=0,
        sharing_url="https://www.dailywire.com/videos/upcoming-movie",
        status="scheduled",
        published_at=datetime(2026, 9, 16, 5, 8, tzinfo=timezone.utc),
        has_video=False,
        is_downloadable=False,
        movie_extras=[trailer],
        trailer=trailer,
    )
    body = MediaDownloadAPICreate(local_media_profile_id=profile.id)

    assert movie_data.is_upcoming is True

    movie, _ = movie_service.index_dailywire_movie(session, movie_data)
    with pytest.raises(HTTPException) as exc_info:
        create_movie_download(session, movie, body)
    assert exc_info.value.status_code == 422

    extra_download = create_movie_extra_download(
        session,
        movie,
        trailer.slug,
        body,
    )
    session.commit()

    assert isinstance(extra_download, MovieExtraMediaDownload)
    assert extra_download.media.slug == trailer.slug

    session.close()
    engine.dispose()


def test_released_movie_downloads_even_when_daily_wire_turns_off_offline_downloads(tmp_path, monkeypatch):
    """isDownloadable only governs The Daily Wire's own apps; a released movie with a video can be downloaded."""
    from backend.api.endpoints.media_downloads.service import create_movie_download
    from backend.services import movies as movie_service
    from backend.api.models.media_download import MediaDownloadAPICreate
    from backend.db.core import Base
    from backend.db.models import MovieLocalMediaProfile
    from backend.db.models.media_download import MovieMediaDownload
    from config import get_settings
    from sources.dailywire.api.records import DwMovieRecord

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    monkeypatch.setattr(movie_service, "ensure_movie_release_metadata", lambda _s, _movie: None)

    profile = MovieLocalMediaProfile(
        slug="movies",
        name="Movies",
        output_template="/downloads/{{ movie_title }}/{{ slug }}.ext",
        preferred_format="format_1080p",
    )
    session.add(profile)
    session.commit()

    movie_data = DwMovieRecord(
        dw_id="movie-2",
        slug="released-movie",
        title="Released Movie",
        description="Released movie description.",
        duration=7920,
        sharing_url="https://www.dailywire.com/videos/released-movie",
        status="published",
        published_at=datetime(2026, 11, 11, 23, 40, tzinfo=timezone.utc),
        has_video=True,
        is_downloadable=False,
    )

    movie, _ = movie_service.index_dailywire_movie(session, movie_data)
    download = create_movie_download(
        session,
        movie,
        MediaDownloadAPICreate(local_media_profile_id=profile.id),
    )
    session.commit()

    assert isinstance(download, MovieMediaDownload)
    assert download.media_item_id == movie.id

    session.close()
    engine.dispose()
