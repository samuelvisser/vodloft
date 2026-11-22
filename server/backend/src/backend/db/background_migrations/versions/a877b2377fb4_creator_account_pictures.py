"""Look up the picture and banner of each account of a creator on several Sites.

A creator's account on a second Site, such as their SoundCloud next to their YouTube channel, used to have no
picture of its own, so the creator's page showed the picture from the other Site. This looks each such account up on
its Site and keeps its picture and banner.

Revision ID: a877b2377fb4
Revises: ecb0f787c77a
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, or_, select

from backend.db.core import get_session, run_write_transaction
from backend.db.models import CreatorAccount
from backend.services.creators import take_account_pictures
from sources import get_source

logger = logging.getLogger(__name__)

revision = "a877b2377fb4"
down_revision = "ecb0f787c77a"
title = "Look up the pictures of creators' accounts on each Site"


def _accounts() -> list[tuple[int, str, str]]:
    """The accounts of creators on several Sites, and the accounts without a picture of their own."""
    session = get_session()
    try:
        several = select(CreatorAccount.creator_id).group_by(CreatorAccount.creator_id).having(func.count() > 1)
        query = select(CreatorAccount).where(or_(
            CreatorAccount.creator_id.in_(several), CreatorAccount.avatar_path.is_(None),
        )).order_by(CreatorAccount.id)
        return [(account.id, account.source_key, account.url or account.site_ref) for account in session.scalars(query)]
    finally:
        session.rollback()
        session.close()


def _store(account_id: int, avatar: str | None, banner: str | None) -> None:
    def work(session):
        account = session.get(CreatorAccount, account_id)
        if account is not None:
            take_account_pictures(account, avatar=avatar, banner=banner)

    run_write_transaction(work)


async def migrate(context) -> None:
    accounts = _accounts()
    for done, (account_id, source_key, ref) in enumerate(accounts):
        context.raise_if_canceled()
        context.update_progress(done, len(accounts), f"Looking up the pictures of account {done + 1} of {len(accounts)}")
        try:
            details = await asyncio.to_thread(get_source(source_key).creator_details, ref)
        except Exception as exc:  # A Site that is down leaves the account with the picture it has.
            logger.warning("Could not look up the pictures of creator account %s: %s", account_id, exc)
            continue
        await asyncio.to_thread(_store, account_id, details.avatar_url, details.banner_url)
    context.update_progress(len(accounts), len(accounts), "Looked up the pictures of creators' accounts")
