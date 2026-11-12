from __future__ import annotations

import asyncio
import json
import sqlite3

from sqlalchemy.exc import IntegrityError


def test_integrity_error_handler_serializes_generic_database_error() -> None:
    from backend.api.errors import integrity_error_handler

    exc = IntegrityError(
        "DELETE FROM local_media_profiles WHERE id = ?",
        {"id": 1},
        sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
    )

    response = asyncio.run(integrity_error_handler(None, exc))  # type: ignore[arg-type]
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["detail"][0]["type"] == "integrity_error"
    assert payload["detail"][0]["msg"] == "FOREIGN KEY constraint failed"


def _handle(orig: Exception) -> tuple[int, list[dict]]:
    from backend.api.errors import integrity_error_handler

    exc = IntegrityError("INSERT INTO local_media_profiles ...", {}, orig)
    response = asyncio.run(integrity_error_handler(None, exc))  # type: ignore[arg-type]
    return response.status_code, json.loads(response.body)["detail"]


def test_sqlite_unique_error_lands_on_the_camel_case_form_fields() -> None:
    status, detail = _handle(sqlite3.IntegrityError(
        "UNIQUE constraint failed: local_media_profiles.type, local_media_profiles.output_template, "
        "local_media_profiles.preferred_format"
    ))

    assert status == 409
    assert [item["loc"] for item in detail] == [
        ["body", "type"], ["body", "outputTemplate"], ["body", "preferredFormat"],
    ]
    assert {item["type"] for item in detail} == {"unique_violation"}


def test_sqlite_not_null_error_lands_on_its_field() -> None:
    status, detail = _handle(sqlite3.IntegrityError("NOT NULL constraint failed: local_media_profiles.output_template"))

    assert status == 422
    assert detail == [{"loc": ["body", "outputTemplate"], "msg": "This field is required.", "type": "missing"}]


class _PostgresError(Exception):
    def __init__(self, sqlstate: str, **diag: str) -> None:
        super().__init__("postgres error")
        self.sqlstate = sqlstate
        self.diag = type("Diag", (), diag)()


def test_postgres_unique_error_finds_the_constraint_columns_by_name() -> None:
    # Table names hold underscores, so the columns cannot be read from the constraint name itself.
    status, detail = _handle(_PostgresError(
        "23505", table_name="local_media_profiles", constraint_name="uq_local_media_profiles_name",
    ))

    assert status == 409
    assert [item["loc"] for item in detail] == [["body", "name"]]


def test_postgres_unique_index_error_finds_its_columns() -> None:
    _, detail = _handle(_PostgresError(
        "23505", table_name="local_media_profiles", constraint_name="ix_local_media_profiles_slug",
    ))

    assert [item["loc"] for item in detail] == [["body", "slug"]]


def test_postgres_not_null_error_lands_on_its_field() -> None:
    _, detail = _handle(_PostgresError(
        "23502", table_name="local_media_profiles", column_name="preferred_format",
    ))

    assert [item["loc"] for item in detail] == [["body", "preferredFormat"]]


def test_model_validator_field_errors_land_on_their_field() -> None:
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError
    import pytest

    from backend.api.errors import validation_error_handler
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    with pytest.raises(ValidationError) as invalid:
        CollectionLocalMediaProfileAPICreate.model_validate({
            "name": "Profile", "preferredFormat": "format_1080p", "outputTemplate": "/downloads/{{ title }}.ext",
            "indexingValues": [{"key": "part", "name": "Part"}, {"key": "part", "name": "Other part"}],
        })
    errors = [{**error, "loc": ("body", *error["loc"])} for error in invalid.value.errors()]

    response = asyncio.run(validation_error_handler(None, RequestValidationError(errors)))  # type: ignore[arg-type]
    detail = json.loads(response.body)["detail"]

    assert response.status_code == 422
    assert [(item["loc"], item["msg"]) for item in detail] == [
        (["body", "indexingValues"], "Indexing Value keys must be unique"),
    ]
