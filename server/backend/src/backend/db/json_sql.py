"""JSON SQL that SQLAlchemy does not translate between SQLite and PostgreSQL itself."""
from __future__ import annotations

from sqlalchemy import JSON, Integer, column, literal_column
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class _JsonArrayItems(FunctionElement):
    inherit_cache = True
    name = "json_array_items"

    def __init__(self, document, path: tuple[str, ...]):
        self.path = path
        super().__init__(document)


def json_array_items(document, *path: str):
    """The items of the JSON array at ``path`` in ``document``, as a table with a JSON ``value`` column.

    A missing path or a value that is not an array gives no rows, on every database.
    """
    return _JsonArrayItems(document, tuple(path)).table_valued(column("value", JSON))


def _quoted(key: str) -> str:
    return "'" + key.replace("'", "''") + "'"


@compiles(_JsonArrayItems)
def _compile_sqlite(element: _JsonArrayItems, compiler, **kw) -> str:
    document = compiler.process(element.clauses, **kw)
    sqlite_path = "$" + "".join(f'."{key}"' for key in element.path)
    return f"json_each({document}, {_quoted(sqlite_path)})"


@compiles(_JsonArrayItems, "postgresql")
def _compile_postgresql(element: _JsonArrayItems, compiler, **kw) -> str:
    document = compiler.process(element.clauses, **kw)
    value = f"({document})" + "".join(f" -> {_quoted(key)}" for key in element.path)
    # json_array_elements() fails on anything but an array; SQLite's json_each() does not.
    return f"json_array_elements(CASE WHEN json_typeof({value}) = 'array' THEN {value} END)"


class _JsonCount(FunctionElement):
    inherit_cache = True
    name = "json_count"
    type = Integer()

    def __init__(self, document, path: tuple[str, ...]):
        self.path = path
        super().__init__(document)


def json_count(document, *path: str):
    """How many the value at ``path`` in ``document`` counts: a number itself, an array its length, true 1, else 0."""
    return _JsonCount(document, tuple(path))


@compiles(_JsonCount)
def _compile_count_sqlite(element: _JsonCount, compiler, **kw) -> str:
    document = compiler.process(element.clauses, **kw)
    path = _quoted("$" + "".join(f'."{key}"' for key in element.path))
    return (
        f"(CASE json_type({document}, {path})"
        f" WHEN 'integer' THEN json_extract({document}, {path})"
        f" WHEN 'real' THEN json_extract({document}, {path})"
        f" WHEN 'array' THEN json_array_length({document}, {path})"
        " WHEN 'true' THEN 1"
        " ELSE 0 END)"
    )


@compiles(_JsonCount, "postgresql")
def _compile_count_postgresql(element: _JsonCount, compiler, **kw) -> str:
    document = compiler.process(element.clauses, **kw)
    value = f"({document})" + "".join(f" -> {_quoted(key)}" for key in element.path)
    return (
        f"(CASE json_typeof({value})"
        f" WHEN 'number' THEN ({value})::text::numeric"
        f" WHEN 'array' THEN json_array_length({value})"
        f" WHEN 'boolean' THEN (CASE WHEN ({value})::text = 'true' THEN 1 ELSE 0 END)"
        " ELSE 0 END)"
    )
