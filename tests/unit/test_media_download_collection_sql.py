"""The statement behind the Downloads page joins each table it reads.

A table the statement names without joining it multiplies the downloads by every row of that table. On
production that made SQLite build a temporary table until the disk was full.
"""
import sys
import threading
import warnings

import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.sql import compiler

import backend.db.models  # noqa: F401  (registers every mapper)
from backend.services.media_download_collection import MediaDownloadCollectionQuery

_LINTING = compiler.COLLECT_CARTESIAN_PRODUCTS | compiler.WARN_LINTING


def _statements():
    query = MediaDownloadCollectionQuery.build()
    return [
        query.summary_statement(statuses=[], order="workflow"),
        query.summary_statement(statuses=["pending", "locked"], order="recent"),
        query.bulk_action_ids_statement(statuses=[], action="retry"),
    ]


def _compile_without_cartesian_products(statement, dialect) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return str(statement.compile(dialect=dialect, linting=_LINTING))


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()], ids=["sqlite", "postgresql"])
def test_download_collection_statements_join_every_table_they_read(dialect):
    for statement in _statements():
        sql = _compile_without_cartesian_products(statement, dialect)
        assert ", media_items)" not in sql


def test_download_collection_statements_built_at_once_join_every_table_they_read():
    """Requests build the statement on several threads at once. A shared alias of media_items once had its
    columns filled in by two of them together, and named the bare table from then on."""
    errors: list[BaseException] = []
    threads = 32
    start = threading.Barrier(threads)

    def build():
        try:
            start.wait()
            for statement in _statements():
                _compile_without_cartesian_products(statement, sqlite.dialect())
        except BaseException as error:  # noqa: BLE001  (reported by the test below)
            errors.append(error)

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        workers = [threading.Thread(target=build) for _ in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    finally:
        sys.setswitchinterval(interval)
    assert errors == []
