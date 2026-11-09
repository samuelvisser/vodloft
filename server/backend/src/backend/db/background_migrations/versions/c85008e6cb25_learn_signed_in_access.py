"""Learn what each Source's sign-in gives, such as the Daily Wire account's membership level.

VODLoft now keeps the membership level of the Daily Wire account beside the sign-in, so that
episodes the account may watch show an open lock. It learns the level when the account signs in;
this asks once for a sign-in made before VODLoft kept it.

Revision ID: c85008e6cb25
Revises: 305a9510537f
"""

from __future__ import annotations

import asyncio


revision = "c85008e6cb25"
down_revision = "305a9510537f"
title = "Learn what each Source's sign-in gives"


async def migrate(context) -> None:
    from sources import all_sources

    sources = list(all_sources())
    for done, source in enumerate(sources):
        context.raise_if_canceled()
        context.update_progress(done, len(sources), f"Asking {source.name} what its sign-in gives")
        await asyncio.to_thread(source.learn_access)
    context.update_progress(len(sources), len(sources), "Learned what each sign-in gives")
