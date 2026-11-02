"""Taking over a Daily Wire sign-in another program kept, such as WireLoft's."""
from __future__ import annotations

from collections.abc import Mapping

from sources.dailywire.auth.storage import TokenStore


def save_imported_sign_in(records: Mapping[str, str]) -> None:
    """Store each sign-in record, already in the token store's JSON form, under its store key."""
    store = TokenStore()
    for store_key, record in records.items():
        store._set(store_key, str(record))  # noqa: SLF001  (the record is already the stored JSON)
