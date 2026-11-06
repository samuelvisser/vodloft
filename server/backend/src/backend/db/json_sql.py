"""JSON SQL that SQLAlchemy does not translate between SQLite and PostgreSQL itself."""
from __future__ import annotations

from sqlalchemy import JSON, column, literal_column
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
