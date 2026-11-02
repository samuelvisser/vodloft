"""What an importer hands the application: neutral descriptions, no database rows.

Every plan names things by the other program's own ids (``external_id``), so a
repeat import can find what an earlier run wrote. Nothing here is VODLoft's
model; the backend decides how each part becomes a Collection, a profile or a
download, and refuses what it can't apply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .uploads import UploadFile

Support = Literal["exact", "close", "unsupported"]


@dataclass(frozen=True)
class ImportWarning:
    """Something the person should know: what it was, and what the import did instead."""

    subject: str
    message: str
    support: Support = "unsupported"


@dataclass(frozen=True)
class ImportLocation:
    """Where the other program's data is, and where VODLoft sees its files."""

    database: Path
    """The other program's database, a private copy the importer may open for writing."""
    extras: Path | None = None
    """Extra files next to the database, such as yt-dlp option files."""
    path_map: tuple[str, str] = ("/downloads", "/downloads")
    """A folder as the other program sees it, and the ``/downloads/…`` folder that is the same folder in VODLoft."""


@dataclass(frozen=True)
class CustomIndexPlan:
    key: str
    name: str
    keep_numbers: bool = False
    start: int = 1
    step: int = 1
    """The template reads the n-th number as ``start + (n - 1) * step``."""

    def ordinal(self, value: int) -> int | None:
        """Which number ``value`` is, as VODLoft stores it (1 and up), or None when it can't be one."""
        if self.step == 0:
            return None
        count, rest = divmod(value - self.start, self.step)
        return count + 1 if rest == 0 and count >= 0 else None


@dataclass(frozen=True)
class ProfilePlan:
    external_id: str
    name: str
    output_template: str | None
    """None when no valid VODLoft template could be made; the profile then needs attention."""
    custom_indexes: tuple[CustomIndexPlan, ...] = ()
    settings: dict[str, object] = field(default_factory=dict)
    """Local Media Profile fields by their VODLoft name, such as ``preferred_format``."""
    warnings: tuple[ImportWarning, ...] = ()
    original_template: str | None = None
    """The template as the other program had it."""
    report: tuple[str, ...] = ()
    """How the template and its options were converted, one line per part that is not exact."""
    support: Support = "exact"


@dataclass(frozen=True)
class CollectionPlan:
    external_id: str
    url: str
    title: str
    profile_external_id: str | None = None
    settings: dict[str, object] = field(default_factory=dict)
    """Collection fields by their VODLoft name, such as ``type``."""
    download_profile: dict[str, object] | None = None
    """Download Profile fields by their VODLoft name, or None for no Download Profile."""
    warnings: tuple[ImportWarning, ...] = ()
    assets: tuple[tuple[str, str], ...] = ()
    """Collection artwork and NFO files as (kind, path), such as ("poster", "/downloads/…/poster.jpg")."""


FileKind = Literal["file", "suppressed", "missing"]


@dataclass(frozen=True)
class FilePlan:
    """An item the other program knew, and what VODLoft should record for it.

    ``file`` is a downloaded file to adopt at ``path``. ``suppressed`` is an
    item the other program was told not to download, which VODLoft won't
    download either. ``missing`` is an item whose file was deleted on purpose.
    """

    collection_external_id: str
    media_site_id: str
    path: str | None
    """A ``/downloads/…`` path, as VODLoft sees it."""
    kind: FileKind = "file"
    custom_index_values: dict[str, int] = field(default_factory=dict)
    """VODLoft's numbers (1 and up) for the profile's Custom Indexes."""
    title: str | None = None
    published: str | None = None
    """When the item was published, as an ISO date or time."""


@dataclass(frozen=True)
class SettingPlan:
    key: str
    value: object
    support: Support = "exact"
    note: str | None = None
    secret: bool = False
    """A sign-in or key: only applied when the person asks, and never shown."""


@dataclass(frozen=True)
class ImportPlan:
    importer: str
    profiles: tuple[ProfilePlan, ...] = ()
    collections: tuple[CollectionPlan, ...] = ()
    files: tuple[FilePlan, ...] = ()
    settings: tuple[SettingPlan, ...] = ()
    warnings: tuple[ImportWarning, ...] = ()
    version: str | None = None
    """The other program's database version."""


@runtime_checkable
class Importer(Protocol):
    key: str
    name: str
    upload_files: tuple["UploadFile", ...]
    """The files an upload of the other program's config folder takes."""
    database: str
    """The database inside the config folder, such as ``db/pinchflat.db``."""
    extras: str | None
    """The folder of extra files inside the config folder, or None."""

    def read(self, location: ImportLocation) -> ImportPlan:
        """Describe everything at ``location`` that VODLoft can take over."""
        ...
