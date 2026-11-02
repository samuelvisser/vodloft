"""File and folder names, cleaned the way yt-dlp cleans them.

Each value a template fills in is cleaned like yt-dlp's ``sanitize_filename``
(:func:`clean_value`), so a converted Pinchflat template names new downloads
like the old ones. Each finished folder and file name is then cleaned again
with the same rules (:func:`clean_component`), so text typed in the template
follows them too, and VODLoft's own guards apply.

The rules follow yt-dlp (Unlicense), with VODLoft's three modes:

- Unrestricted: only ``/`` (as ``⧸``) and control characters change.
- Windows: ``: " * < > ? | / \\`` become look-alikes, as in yt-dlp's default.
- Restricted: ASCII only, as in ``--restrict-filenames``, with a larger
  transliteration table.
"""
from __future__ import annotations

import re
import unicodedata

from config.settings.submodels import FilenameRestrictionMode

# A name with nothing ASCII left, in Restricted mode.
NO_ASCII_FILE_NAME = "no_ascii_file_name"
# Left by a value that had letters but none in ASCII, so the whole name can
# tell "nothing ASCII left" from "nothing there". The name pass drops it.
_NO_ASCII_MARK = "\ue000"

_WINDOWS_LOOKALIKES = {
    "/": "⧸",
    "\\": "⧹",
    **{char: chr(ord(char) + 0xFEE0) for char in ':"*<>?|'},
}
_TIMESTAMP = re.compile(r"[0-9]+(?::[0-9]+)+")
_WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)
_RESTRICTED_PUNCTUATION = set("!&'()[]{}$;`^,#")
_RESTRICTED_OUTSIDE = re.compile(r"[^A-Za-z0-9._-]")

# Starts from yt-dlp's ACCENT_CHARS; letters without a decomposition and
# common punctuation are added so they keep their meaning in ASCII.
_TRANSLITERATION: dict[str, str] = {
    **dict(zip(
        "ÂÃÄÀÁÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖŐØŒÙÚÛÜŰÝÞßàáâãäåæçèéêëìíîïðñòóôõöőøœùúûüűýþÿ",
        [*"AAAAAA", "AE", *"CEEEEIIIIDNOOOOOOO", "OE", *"UUUUUY", "TH", "ss",
         *"aaaaaa", "ae", *"ceeeeiiiionooooooo", "oe", *"uuuuuy", "th", "y"],
        strict=True,
    )),
    "Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Ħ": "H", "ħ": "h", "ı": "i",
    "Ŋ": "N", "ŋ": "n", "Ŧ": "T", "ŧ": "t", "ĸ": "k", "ſ": "s", "ẞ": "SS",
    "Ĳ": "IJ", "ĳ": "ij", "Ŀ": "L", "ŀ": "l",
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "′": "'", "″": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "−": "-", "…": "...", "×": "x", "÷": "_", "·": ".",
    "•": "-", "©": "(c)", "®": "(r)", "™": "TM", "€": "EUR",
    "£": "GBP", "¥": "JPY", "°": "deg", "½": "1_2", "¼": "1_4",
    "¾": "3_4", "²": "2", "³": "3", "¹": "1",
}


def _ascii(char: str) -> str:
    """One character as ASCII: the table first, then its letters without accents."""
    if char in _TRANSLITERATION:
        return _TRANSLITERATION[char]
    if char.isascii():
        return char
    decomposed = unicodedata.normalize("NFKD", char)
    return "".join(
        part for part in decomposed
        if part.isascii() and unicodedata.category(part)[0] not in "CM"
    )


def _timestamps(value: str) -> str:
    return _TIMESTAMP.sub(lambda match: match.group(0).replace(":", "_"), value)


def _is_control(char: str) -> bool:
    return ord(char) < 32 or ord(char) == 127


def _unrestricted(value: str) -> str:
    return "".join(
        "⧸" if char == "/" else "" if _is_control(char) and char != "\t" else char
        for char in value
    )


def _windows_characters(value: str) -> str:
    value = _timestamps(value)
    return "".join(
        _WINDOWS_LOOKALIKES.get(char) or ("_" if _is_control(char) else char)
        for char in value
    )


def _restricted_value(value: str) -> str:
    """yt-dlp's ``sanitize_filename(value, restricted=True)``, with the larger table."""
    value = _timestamps(unicodedata.normalize("NFKC", value))

    def replace(char: str) -> str:
        if char == "?" or _is_control(char) or char == '"':
            return ""
        if char == ":":
            return "\0_\0-"
        if char in "\\/|*<>":
            return "\0_"
        if not char.isascii():
            ascii_ = _ascii(char)
            if ascii_:
                return "".join(replace(part) for part in ascii_)
            return "" if unicodedata.category(char)[0] in "CM" else "\0_"
        if char in _RESTRICTED_PUNCTUATION or char.isspace():
            return "\0_"
        return char

    result = "".join(replace(char) for char in value)
    result = re.sub(r"(\0.)(?:(?=\1)..)+", r"\1", result)
    strip = r"(?:\0.|[ _-])*"
    result = re.sub(f"^\0.{strip}|{strip}\0.$", "", result)
    return result.replace("\0", "")


def clean_value(value: object, mode: FilenameRestrictionMode) -> str:
    """One value a template fills in, cleaned as yt-dlp cleans a field."""
    text = "" if value is None else str(value)
    if text == "":
        return ""
    if mode == FilenameRestrictionMode.UNRESTRICTED:
        return _unrestricted(text)
    if mode == FilenameRestrictionMode.WINDOWS:
        cleaned = _windows_characters(text)
    else:
        cleaned = _restricted_value(text)
        if not _has_letters(cleaned) and _has_letters(text):
            return _NO_ASCII_MARK
    # A value that cleans away entirely leaves nothing, rather than yt-dlp's
    # "_", so an empty title does not leave a stray "_" in a longer name.
    return cleaned


def _restricted_component(value: str) -> str:
    cleaned = "".join(_ascii(char) for char in _timestamps(value))
    cleaned = cleaned.replace(":", "_-")
    cleaned = _RESTRICTED_OUTSIDE.sub("_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" _")
    # Replaced punctuation right before an extension ("Test?.mp4") is not part of the name.
    return re.sub(r"_+(?=\.[A-Za-z0-9]+$)", "", cleaned)


def _has_letters(value: str) -> bool:
    return any(char.isalnum() for char in value)


def clean_component(value: str, mode: FilenameRestrictionMode, *, extension: str | None = None) -> str:
    """One whole folder or file name, typed text included.

    ``extension`` marks a file name, whose extension is kept apart from the
    name, so a Restricted name with nothing ASCII left still keeps it.
    """
    stem, suffix = value, ""
    if extension and value.endswith(f".{extension}"):
        stem, suffix = value[: -len(extension) - 1], f".{extension}"

    if mode == FilenameRestrictionMode.RESTRICTED:
        cleaned = _restricted_component(stem)
        if not _has_letters(cleaned) and (_has_letters(stem) or _NO_ASCII_MARK in stem):
            cleaned = NO_ASCII_FILE_NAME
        cleaned = f"{cleaned}{suffix}"
    elif mode == FilenameRestrictionMode.WINDOWS:
        cleaned = _windows_characters(f"{stem}{suffix}").rstrip(" .")
        if _WINDOWS_RESERVED.match(cleaned):
            cleaned = f"_{cleaned}"
    else:
        cleaned = _unrestricted(f"{stem}{suffix}")
    cleaned = cleaned.replace(_NO_ASCII_MARK, "")

    if cleaned in {"", ".", ".."} or cleaned == suffix:
        return f"_{suffix}" if cleaned == suffix and suffix else "_"
    return cleaned


def replaced_typed_characters(text: str, mode: FilenameRestrictionMode) -> list[str]:
    """The distinct characters of typed template text that ``mode`` changes, in order."""
    found: list[str] = []
    for char in text:
        if char == "/" or char in found:
            continue
        if mode == FilenameRestrictionMode.UNRESTRICTED:
            changed = _is_control(char) and char != "\t"
        elif mode == FilenameRestrictionMode.WINDOWS:
            changed = char in _WINDOWS_LOOKALIKES or _is_control(char)
        else:
            changed = _RESTRICTED_OUTSIDE.fullmatch(char) is not None
        if changed:
            found.append(char)
    return found


def is_no_ascii_name(component: str) -> bool:
    """Whether a cleaned name is the Restricted stand-in for a non-ASCII one."""
    stem = component.split(".", 1)[0]
    return re.fullmatch(rf"{NO_ASCII_FILE_NAME}(?:_[0-9]+)?", stem) is not None


def numbered_no_ascii_name(component: str, number: int) -> str:
    """``no_ascii_file_name.mp4`` as the ``number``-th such name: ``no_ascii_file_name_2.mp4``."""
    if number < 2:
        return component
    stem, dot, rest = component.partition(".")
    return f"{NO_ASCII_FILE_NAME}_{number}{dot}{rest}"
