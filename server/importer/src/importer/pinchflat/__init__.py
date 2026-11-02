"""The Pinchflat importer: channels, playlists, media profiles and every downloaded video."""
from ..registry import register
from ..paths import DEFAULT_PATH_MAP, PathMap, detect_path_map, map_path, path_map_candidates
from .mapping import UPLOAD_FILES, PinchflatImporter, plan_import
from .reader import NEWEST_KNOWN_VERSION, PinchflatData, PinchflatReadError, private_copy, read_pinchflat

IMPORTER = register(PinchflatImporter())

__all__ = [
    "IMPORTER",
    "UPLOAD_FILES",
    "NEWEST_KNOWN_VERSION",
    "PinchflatData",
    "PinchflatImporter",
    "PinchflatReadError",
    "DEFAULT_PATH_MAP",
    "PathMap",
    "detect_path_map",
    "map_path",
    "path_map_candidates",
    "plan_import",
    "private_copy",
    "read_pinchflat",
]
