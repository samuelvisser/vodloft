"""Nothing left to do: 9c25f5b4d4d1 looks up the pictures of YouTube playlists again.

This step looked them up before VODLoft checked which sizes YouTube serves. It stays in the history so a database
that ran it still knows where it is.

Revision ID: 7aaaa88fe96d
Revises: 7c2e91d4a6f0
"""

from __future__ import annotations

revision = "7aaaa88fe96d"
down_revision = "7c2e91d4a6f0"
title = "Look up the pictures of YouTube playlists (replaced)"


async def migrate(context) -> None:
    return None
