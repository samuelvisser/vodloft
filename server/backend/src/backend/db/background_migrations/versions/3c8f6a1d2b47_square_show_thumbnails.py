"""Historical WireLoft migration, superseded by normalized VodLoft media.

Old episode identifiers and show thumbnail fields are retained as history;
active media is converted by the later VodLoft migration without provider I/O.
"""
revision = "3c8f6a1d2b47"
down_revision = "f6a1c3d8b427"
title = "Retain historical WireLoft indexing and artwork"

async def migrate(context):
    context.raise_if_cancelled()
