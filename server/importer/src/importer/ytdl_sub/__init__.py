"""The ytdl-sub importer: TV show and music subscriptions, their presets and every file in their download archives."""
from ..registry import register
from .archive import ArchiveEntry, archive_names, read_archive
from .mapping import UPLOAD_FILES, YtdlSubImporter, plan_import
from .reader import Subscription, YtdlSubData, YtdlSubReadError, read_ytdl_sub

IMPORTER = register(YtdlSubImporter())

__all__ = [
    "IMPORTER",
    "UPLOAD_FILES",
    "ArchiveEntry",
    "Subscription",
    "YtdlSubData",
    "YtdlSubImporter",
    "YtdlSubReadError",
    "archive_names",
    "plan_import",
    "read_archive",
    "read_ytdl_sub",
]
