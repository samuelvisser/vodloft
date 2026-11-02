"""The loose form names are compared in: no case, no accents, punctuation as spaces."""
from __future__ import annotations

import re
import unicodedata

_SEPARATORS = re.compile(r"[\W_]+")


def normalise(text: str) -> str:
    """``Amélie： Test？`` and ``Amelie_-_Test`` both become ``amelie test``."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _SEPARATORS.sub(" ", stripped.casefold()).strip()


def normalise_words(text: str) -> list[str]:
    return normalise(text).split()


def normalise_path(path: str) -> str:
    """Each folder and the file name normalised, still separated by ``/``."""
    return "/".join(normalise(part) for part in path.split("/") if part)
