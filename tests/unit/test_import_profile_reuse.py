"""An import uses a Local Media Profile VODLoft has instead of a copy only when it keeps files the same way."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import use_database

TEMPLATE = "/downloads/music/{{ artist }}/{{ album }}/{{ track_number_padded }} - {{ title }}.ext"


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _plan(audio_format: str):
    from importer.contract import ProfilePlan

    return ProfilePlan(
        external_id=f"music-{audio_format}", name=f"Music {audio_format}", output_template=TEMPLATE,
        settings={"type": "collection", "preferred_format": "format_audio_only", "collection_scope": "music",
                  "audio_format": audio_format},
    )


def test_a_profile_in_another_audio_format_is_not_reused(session):
    from backend.services.imports import _matching_profile
    from backend.services.local_media_profile_changes import create_collection_local_media_profile
    from backend.services.local_media_profile_inputs import NewCollectionLocalMediaProfile

    flac = create_collection_local_media_profile(session, NewCollectionLocalMediaProfile.model_validate({
        "name": "FLAC", "type": "collection", "output_template": TEMPLATE, "preferred_format": "format_audio_only",
        "collection_scope": "music", "audio_format": "flac",
    }))
    session.flush()

    assert _matching_profile(session, _plan("flac")) is flac
    assert _matching_profile(session, _plan("m4a")) is None
