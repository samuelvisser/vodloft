"""The WireLoft importer: Daily Wire shows, movies, profiles, RSS feeds and downloads."""
from ..registry import register
from .mapping import UPLOAD_FILES, WireLoftImporter, download_paths, plan_import, rename_template_variables
from .reader import WireLoftData, WireLoftReadError, read_wireloft

IMPORTER = register(WireLoftImporter())

__all__ = [
    "IMPORTER",
    "UPLOAD_FILES",
    "WireLoftData",
    "WireLoftImporter",
    "WireLoftReadError",
    "download_paths",
    "plan_import",
    "read_wireloft",
    "rename_template_variables",
]
