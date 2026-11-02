"""What an importer hands the application: neutral descriptions, no database rows.

Every plan names things by the other program's own ids (``external_id``), so a
repeat import can find what an earlier run wrote. Nothing here is VODLoft's
model; the backend decides how each part becomes a Collection, a profile or a
download, and refuses what it can't apply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

Support = Literal["exact", "close", "unsupported"]


@dataclass(frozen=True)
class ImportWarning:
    """Something the person should know: what it was, and what the import did instead."""

    subject: str
    message: str
    support: Support = "unsupported"


@dataclass(frozen=True)
class ImportLocation:
    """Where the other program's data is: its database and the folder its files live in."""

    database: Path
    media_root: Path | None = None
    extras: Path | None = None
    """Extra files next to the database, such as yt-dlp option files."""


@dataclass(frozen=True)
class CustomIndexPlan:
    key: str
    name: str
    keep_numbers: bool = False


@dataclass(frozen=True)
class ProfilePlan:
    external_id: str
    name: str
    output_template: str | None
    """None when no valid VODLoft template could be made; the profile then needs attention."""
    custom_indexes: tuple[CustomIndexPlan, ...] = ()
    settings: dict[str, object] = field(default_factory=dict)
    warnings: tuple[ImportWarning, ...] = ()


@dataclass(frozen=True)
class CollectionPlan:
    external_id: str
    url: str
    title: str
    profile_external_id: str | None = None
    settings: dict[str, object] = field(default_factory=dict)
    warnings: tuple[ImportWarning, ...] = ()


@dataclass(frozen=True)
class FilePlan:
    """A file the other program downloaded, and what it belongs to."""

    collection_external_id: str
    media_site_id: str
    path: Path
    custom_index_values: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SettingPlan:
    key: str
    value: object
    support: Support = "exact"
    note: str | None = None


@dataclass(frozen=True)
class ImportPlan:
    importer: str
    profiles: tuple[ProfilePlan, ...] = ()
    collections: tuple[CollectionPlan, ...] = ()
    files: tuple[FilePlan, ...] = ()
    settings: tuple[SettingPlan, ...] = ()
    warnings: tuple[ImportWarning, ...] = ()


@runtime_checkable
class Importer(Protocol):
    key: str
    name: str

    def read(self, location: ImportLocation) -> ImportPlan:
        """Describe everything at ``location`` that VODLoft can take over."""
        ...
