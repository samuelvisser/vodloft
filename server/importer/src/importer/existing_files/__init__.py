"""Files already on disk, matched to the episodes they hold. No database: facts in, matches out."""
from .matching import (
    Confidence,
    EpisodeFacts,
    Evidence,
    FileMatch,
    MatchResult,
    match_files,
)
from .normal import normalise, normalise_path
from .patterns import PathPattern, template_patterns
from .scanning import FoundFile, is_media_file, scan_folder

__all__ = [
    "Confidence",
    "EpisodeFacts",
    "Evidence",
    "FileMatch",
    "FoundFile",
    "MatchResult",
    "PathPattern",
    "is_media_file",
    "match_files",
    "normalise",
    "normalise_path",
    "scan_folder",
    "template_patterns",
]
