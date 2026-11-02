"""Which files of another program's config folder an upload takes, and where they go.

The browser filters the folder before sending it, and the server filters again:
only the files an importer reads are kept, under the same relative path as in
the other program's config folder. Anything else, such as gigabytes of
thumbnails, is never stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath


@dataclass(frozen=True)
class UploadFile:
    pattern: str
    """A path inside the config folder, such as ``db/pinchflat.db``; ``*`` matches one name."""
    required: bool = False
    secret: bool = False
    """Holds a sign-in or key: only kept when the person asks for it."""


def normalise_upload_path(path: str, files: tuple[UploadFile, ...]) -> tuple[str, UploadFile] | None:
    """The path inside the config folder and its rule, or None when the upload doesn't take it.

    A folder picker includes the picked folder's name (``config/db/pinchflat.db``)
    and an archive may hold one more folder level, so leading folders are dropped
    until the rest matches a rule. A single database file matches on its name.
    """
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if not parts or any(part in ("..", "") for part in parts) or parts[0] == "/":
        return None
    for start in range(len(parts)):
        candidate = "/".join(parts[start:])
        for rule in files:
            if fnmatchcase(candidate, rule.pattern) and candidate.count("/") == rule.pattern.count("/"):
                return candidate, rule
    name = parts[-1]
    for rule in files:
        if "*" not in rule.pattern and PurePosixPath(rule.pattern).name == name:
            return rule.pattern, rule
    return None
