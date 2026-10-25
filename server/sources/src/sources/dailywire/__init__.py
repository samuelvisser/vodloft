"""The Daily Wire Source.

``api`` (the Daily Wire middleware client and records) and ``auth`` (device
sign-in) are this Source's internals. Code outside this package uses
``DailyWireSource`` through the contract; the Daily Wire-only features that
still reach in directly are listed in tests/unit/test_source_boundaries.py.
"""
from .source import DailyWireSource

__all__ = ["DailyWireSource"]
