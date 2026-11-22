"""Make a collection made from one of its creator's lists one season, numbered in the list's order.

Replaced by ec22487a3a11, which does this for every collection of one list once collections know whether their link
is a channel or a list. A database that ran this already is not changed again by it.

Revision ID: b64eb88d81ac
Revises: a877b2377fb4
"""

from __future__ import annotations

revision = "b64eb88d81ac"
down_revision = "a877b2377fb4"
title = "Make collections of one list one season"


async def migrate(context) -> None:
    """Replaced by ec22487a3a11."""
