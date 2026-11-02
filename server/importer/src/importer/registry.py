"""Importers register themselves by key, as Sources do."""
from __future__ import annotations

from .contract import Importer

_IMPORTERS: dict[str, Importer] = {}


def register(importer: Importer) -> Importer:
    if importer.key in _IMPORTERS:
        raise ValueError(f"An importer named {importer.key!r} is already registered")
    _IMPORTERS[importer.key] = importer
    return importer


def get_importer(key: str) -> Importer:
    try:
        return _IMPORTERS[key]
    except KeyError:
        raise KeyError(f"No importer named {key!r}") from None


def all_importers() -> tuple[Importer, ...]:
    return tuple(_IMPORTERS.values())
