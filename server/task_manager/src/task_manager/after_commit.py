"""Work kept in ``session.info`` until the transaction commits, through SAVEPOINTs.

Events, task dispatches and job cancellations wait in ``session.info`` until the
outer transaction commits. A SAVEPOINT that rolls back only undoes what was
queued inside it: what the outer transaction queued before it still happens.
"""
from __future__ import annotations

import copy

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction

_SAVEPOINTS_KEY = "vodloft.savepoint_queues"
_KEYS: set[str] = set()


def keep_until_commit(*keys: str) -> None:
    """Have a rolled-back SAVEPOINT restore these ``session.info`` queues to what they held before it."""
    _KEYS.update(keys)


@event.listens_for(Session, "after_transaction_create")
def _remember_queues(session: Session, transaction: SessionTransaction) -> None:
    if not transaction.nested:
        return
    snapshot = {key: copy.copy(session.info[key]) for key in _KEYS if key in session.info}
    session.info.setdefault(_SAVEPOINTS_KEY, {})[transaction] = snapshot


@event.listens_for(Session, "after_soft_rollback")
def _restore_queues(session: Session, previous_transaction: SessionTransaction) -> None:
    savepoints = session.info.get(_SAVEPOINTS_KEY, {})
    if not previous_transaction.nested or previous_transaction not in savepoints:
        for key in _KEYS:
            session.info.pop(key, None)
        session.info.pop(_SAVEPOINTS_KEY, None)
        return
    snapshot = savepoints.pop(previous_transaction)
    for key in _KEYS:
        if key in snapshot:
            session.info[key] = snapshot[key]
        else:
            session.info.pop(key, None)


@event.listens_for(Session, "after_transaction_end")
def _forget_savepoints(session: Session, transaction: SessionTransaction) -> None:
    # The snapshots are read after a SAVEPOINT ends, so they are only dropped with the outer transaction.
    if transaction.parent is None:
        session.info.pop(_SAVEPOINTS_KEY, None)
