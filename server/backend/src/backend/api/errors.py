# errors.py
import re
from typing import List, cast
from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic.alias_generators import to_camel
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.exc import IntegrityError

from backend.db import Base
import backend.db.models  # noqa: F401  (registers every table)
from backend.services.errors import FieldValueError
from backend.services.sites import CollectionAlreadyAddedError
from backend.services.source_requests import SourceRequestError

def _constraint_columns(table_name: str | None, constraint_name: str | None) -> List[str]:
    """The columns of a unique constraint or unique index, looked up by name in the models."""
    table = Base.metadata.tables.get(table_name or "")
    if table is None or not constraint_name:
        return []
    for constraint in (*table.constraints, *table.indexes):
        if isinstance(constraint, (UniqueConstraint, Index)) and str(constraint.name) == constraint_name:
            return [column.name for column in constraint.columns]
    return []


def _failed_columns(exc: IntegrityError) -> tuple[str, List[str]]:
    """Which kind of constraint failed, and on which columns, when the database says so."""
    orig = exc.orig
    # PostgreSQL (psycopg) names the constraint, its table and, for NOT NULL, the column.
    diag = getattr(orig, "diag", None)
    if diag is not None:
        if getattr(orig, "sqlstate", None) == "23502" and getattr(diag, "column_name", None):
            return "missing", [diag.column_name]
        columns = _constraint_columns(getattr(diag, "table_name", None), getattr(diag, "constraint_name", None))
        if columns:
            return "unique_violation", columns

    # SQLite: "UNIQUE constraint failed: items.a, items.b" and "NOT NULL constraint failed: items.a".
    message = str(orig)
    match = re.search(r"(UNIQUE|NOT NULL) constraint failed: ([\w.]+(?:, [\w.]+)*)", message)
    if match:
        kind = "unique_violation" if match.group(1) == "UNIQUE" else "missing"
        return kind, [column.rsplit(".", 1)[-1] for column in match.group(2).split(", ")]
    return "integrity_error", []


async def integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Put a database constraint error under the form fields of the columns it is about.

    API models take camelCase field names, so a column ``output_template`` is
    the field ``outputTemplate``. A form shows each error under its field.
    """
    err = cast(IntegrityError, exc)
    kind, columns = _failed_columns(err)
    if not columns:
        # Not about one field, such as a foreign key that still points here.
        return JSONResponse(
            status_code=409,
            content={"detail": [{"loc": ["body", "__all__"], "msg": str(err.orig), "type": "integrity_error"}]},
        )

    if kind == "missing":
        message = "This field is required."
    elif len(columns) == 1:
        message = "This is already in use."
    else:
        names = ", ".join(column.replace("_", " ") for column in columns)
        message = f"Another one already uses this combination of {names}."
    return JSONResponse(
        status_code=409 if kind == "unique_violation" else 422,
        content={"detail": [{"loc": ["body", to_camel(column)], "msg": message, "type": kind} for column in columns]},
    )


def _with_field(error: dict) -> dict:
    cause = (error.get("ctx") or {}).get("error")
    if not isinstance(cause, FieldValueError):
        return error
    return {**error, "loc": (*error["loc"], to_camel(cause.field)), "msg": str(cause)}


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422 answer, with each model validator's FieldValueError moved under its field."""
    err = cast(RequestValidationError, exc)
    moved = RequestValidationError([_with_field(error) for error in err.errors()], body=err.body)
    return await request_validation_exception_handler(request, moved)


async def source_request_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A Source that could not answer is a bad gateway."""
    return JSONResponse(status_code=502, content={"detail": str(cast(SourceRequestError, exc))})


async def collection_already_added_handler(request: Request, exc: Exception) -> JSONResponse:
    """The Site's collection is already in VODLoft, possibly through another Source."""
    return JSONResponse(status_code=409, content={"detail": str(cast(CollectionAlreadyAddedError, exc))})
