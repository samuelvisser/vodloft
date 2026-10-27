"""Rename the WireLoft names that are stored in the database.

Shows that follow the account's highest membership level stored "WL_ANY",
and two episode publication timing markers start with "wireloft:".

Revision ID: f4abb559e3ab
Revises: 65b6125a39bb
Create Date: 2026-10-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f4abb559e3ab"
down_revision = "65b6125a39bb"
branch_labels = None
depends_on = None


# (old, new)
_MEMBERSHIP_LEVEL = ("WL_ANY", "HIGHEST_ALLOWED")
_TIMING_VALUE_PREFIXES = (
    ("wireloft:last_known_pending:", "vodloft:last_known_pending:"),
    ("wireloft:recorded_published_final:", "vodloft:recorded_published_final:"),
)


def _rename(*, reverse: bool) -> None:
    old, new = reversed(_MEMBERSHIP_LEVEL) if reverse else _MEMBERSHIP_LEVEL
    op.execute(sa.text(
        "UPDATE shows SET membership_level = :new WHERE membership_level = :old"
    ).bindparams(old=old, new=new))
    for prefixes in _TIMING_VALUE_PREFIXES:
        old, new = reversed(prefixes) if reverse else prefixes
        op.execute(sa.text(
            "UPDATE metadata SET value = :new || substr(value, :start) WHERE substr(value, 1, :length) = :old"
        ).bindparams(old=old, new=new, start=len(old) + 1, length=len(old)))


def upgrade() -> None:
    _rename(reverse=False)


def downgrade() -> None:
    _rename(reverse=True)
