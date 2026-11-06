from __future__ import annotations

from sqlalchemy import DDL, MetaData, String, event
from sqlalchemy.types import TypeEngine


# PostgreSQL has no built-in case-insensitive collation like SQLite's NOCASE.
# An ICU collation that ignores case (but not accents) gives the same behaviour
# for equality and unique constraints.
POSTGRESQL_CASE_INSENSITIVE_COLLATION = "vodloft_case_insensitive"

_CREATE_POSTGRESQL_COLLATION = DDL(
    f"CREATE COLLATION IF NOT EXISTS {POSTGRESQL_CASE_INSENSITIVE_COLLATION} "
    "(provider = icu, locale = 'und-u-ks-level2', deterministic = false)"
)


def case_insensitive_string(length: int) -> TypeEngine[str]:
    """A string compared and kept unique regardless of upper or lower case."""
    return (
        String(length)
        .with_variant(String(length, collation="NOCASE"), "sqlite")
        .with_variant(String(length, collation=POSTGRESQL_CASE_INSENSITIVE_COLLATION), "postgresql")
    )


def create_case_insensitive_collation(metadata: MetaData) -> None:
    """Create the PostgreSQL collation before any table that uses it."""
    event.listen(metadata, "before_create", _CREATE_POSTGRESQL_COLLATION.execute_if(dialect="postgresql"))
