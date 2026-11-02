from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _metadata_items(values=None):
    return [
        SimpleNamespace(key=f"custom.{key}", value=value)
        for key, value in (values or {}).items()
    ]


def _episode(*, collection_metadata=None):
    return SimpleNamespace(
        collection=SimpleNamespace(
            slug="parenting",
            title="Parenting",
            author_name="Host",
            meta_items=_metadata_items(collection_metadata),
        ),
        season=None,
        slug="episode-one",
        source_slug="episode-one",
        author_name=None,
        duration=0.0,
        title="Episode One",
        episode_identifier="ep.1",
        published_date=None,
        index=1,
        dw_episode_number=None,
    )


def _movie(*, movie_metadata=None):
    return SimpleNamespace(
        type="movie",
        slug="run-hide-fight",
        title="Run Hide Fight",
        extended_title=None,
        author_name="Daily Wire",
        mature_rating="R",
        duration=6540,
        release_date=None,
        meta_items=_metadata_items(movie_metadata),
    )


def _make_collection(session: Session, *, slug: str):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = Collection(
        source_key="dailywire",
        uuid=f"{slug}-uuid",
        slug=slug,
        title=slug.replace("-", " ").title(),
        description=None,
        sharing_url=f"https://example.test/{slug}",
        membership_level="FREE",
        type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host",
        author_slug="host",
    )
    session.add(collection)
    session.flush()
    return collection


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def test_collection_metadata_is_exposed_to_episode_templates() -> None:
    from backend.utils.output_template import (
        COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        episode_output_template_values,
        render_output_template,
    )

    values = episode_output_template_values(
        _episode(collection_metadata={"year": "2026"}),
    )

    assert values["meta_collection_year"] == "2026"
    assert render_output_template(
        "/downloads/{{ collection_title }} ({{ meta_collection_year }})/{{ title }}.ext",
        values,
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    ) == "/downloads/Parenting (2026)/Episode One.ext"


def test_nonexistent_collection_metadata_field_renders_as_empty() -> None:
    from backend.utils.output_template import (
        COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        episode_output_template_values,
        render_output_template,
    )

    values = episode_output_template_values(_episode())
    rendered = render_output_template(
        "/downloads/{{ collection_title }}{% if meta_collection_year %} ({{ meta_collection_year }}){% endif %}/{{ title }}.ext",
        values,
        allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    )

    assert rendered == "/downloads/Parenting/Episode One.ext"


def test_movie_metadata_is_scoped_to_movie_templates() -> None:
    from backend.utils.output_template import (
        MOVIE_OUTPUT_TEMPLATE_FIELDS,
        MOVIE_OUTPUT_TEMPLATE_METADATA_SCOPES,
        COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        movie_output_template_values,
        render_output_template,
    )

    values = movie_output_template_values(_movie(movie_metadata={"collection": "Originals"}))
    assert values["meta_movie_collection"] == "Originals"
    assert render_output_template(
        "/downloads/{{ meta_movie_collection }}/{{ movie_title }}.ext",
        values,
        allowed_fields=MOVIE_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=MOVIE_OUTPUT_TEMPLATE_METADATA_SCOPES,
    ) == "/downloads/Originals/Run Hide Fight.ext"

    with pytest.raises(ValueError, match="Unsupported output template variable"):
        render_output_template(
            "/downloads/{{ meta_movie_collection }}/{{ title }}.ext",
            values,
            allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
            allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        )


def test_removing_shared_field_deletes_values_from_every_collection(db_session: Session) -> None:
    from backend.api.endpoints.custom_metadata.service import (
        remove_shared_custom_metadata_fields,
    )
    from backend.db.models import Collection
    from backend.db.models.Metadata import Metadata
    from backend.utils.custom_metadata import get_custom_metadata, replace_custom_metadata

    first = _make_collection(db_session, slug="first-collection")
    second = _make_collection(db_session, slug="second-collection")

    replace_custom_metadata(first, {"year": "2026", "library": "Plex"})
    replace_custom_metadata(second, {"year": "2025"})
    db_session.flush()

    remove_shared_custom_metadata_fields(
        db_session,
        first,
        parent_table=Collection.__tablename__,
        fields=["year"],
    )
    db_session.expire_all()

    remaining = list(db_session.scalars(
        select(Metadata).where(
            Metadata.parent_table == Collection.__tablename__,
            Metadata.key == "custom.year",
        )
    ))
    assert remaining == []
    assert get_custom_metadata(db_session.get(Collection, first.id)) == {"library": "Plex"}
    assert get_custom_metadata(db_session.get(Collection, second.id)) == {}


def test_collection_api_read_exposes_custom_metadata(db_session: Session) -> None:
    from backend.api.models.collection import CollectionAPIRead
    from backend.utils.custom_metadata import replace_custom_metadata

    collection = _make_collection(db_session, slug="metadata-collection")
    replace_custom_metadata(collection, {"library": "Plex"})
    db_session.flush()

    assert CollectionAPIRead.model_validate(collection).custom_metadata == {"library": "Plex"}


def test_custom_metadata_update_validates_removed_fields() -> None:
    from backend.api.models.custom_metadata import CustomMetadataAPIUpdate

    request = CustomMetadataAPIUpdate(
        customMetadata={"release_year": "2026"},
        removedFields=["old_field"],
    )
    assert request.custom_metadata == {"release_year": "2026"}
    assert request.removed_fields == ["old_field"]

    with pytest.raises(ValidationError):
        CustomMetadataAPIUpdate(customMetadata={"Release year": "2026"})

    with pytest.raises(ValidationError):
        CustomMetadataAPIUpdate(
            customMetadata={"year": "2026"},
            removedFields=["year"],
        )
