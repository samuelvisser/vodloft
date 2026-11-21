"""Looking up the pictures of creators' accounts on each Site."""
from __future__ import annotations

import asyncio
import importlib

from sqlalchemy import select

from backend.db.background_migrations.registry import get_background_migration_history
from backend.db.background_migrations.runner import BackgroundMigrationContext
from sources import registry
from test_creators import ClipsSource, _add_clips, _one_show, client, forget_lookups, tube  # noqa: F401
from test_ytdlp_collections import session  # noqa: F401

migration = importlib.import_module("backend.db.background_migrations.versions.a877b2377fb4_creator_account_pictures")


class Progress:
    def __init__(self):
        self.reports = []

    def set(self, percent, message, meta=None):
        self.reports.append((percent, message, meta))


def _run():
    progress = Progress()
    context = BackgroundMigrationContext(
        migration=next(m for m in get_background_migration_history() if m.revision == migration.revision),
        migration_index=1, migration_total=1, progress=progress,
    )
    asyncio.run(migration.migrate(context))
    return progress.reports


def test_a_library_without_creator_accounts_to_look_up_finishes(session):
    reports = _run()

    assert reports[-1][0] == 100
    assert reports[-1][2]["item_total"] == 0


def test_an_account_on_a_second_site_gets_its_own_pictures(client, tube, session):
    from backend.db.core import run_write_transaction
    from backend.db.models import CreatorAccount

    registry.register(ClipsSource())
    _one_show(client)
    assert _add_clips(client, into="workshop").status_code == 201

    def as_before(s):
        account = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == "clips"))
        account.avatar_path = account.banner_path = None
        account.main_collection.thumbnail_landscape_path = None
    run_write_transaction(as_before)

    reports = _run()

    def pictures(s):
        account = s.scalar(select(CreatorAccount).where(CreatorAccount.site_key == "clips"))
        return account.avatar_path, account.banner_path, account.main_collection.thumbnail_landscape_path
    assert run_write_transaction(pictures) == (
        "https://clips.example/northwind.jpg", "https://clips.example/banner.jpg", "https://clips.example/northwind.jpg",
    )
    assert reports[-1][0] == 100
