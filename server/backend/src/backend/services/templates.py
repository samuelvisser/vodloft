from __future__ import annotations

import re

_TOKEN = re.compile(r"%\(([^)]+)\)[#0+\-.0-9]*[a-zA-Z]")
_SAMPLE = {
    "id": "dQw4w9WgXcQ",
    "title": "Example Video",
    "uploader": "Example Channel",
    "channel": "Example Channel",
    "playlist": "Example Playlist",
    "playlist_title": "Example Playlist",
    "upload_date": "20260913",
    "ext": "mkv",
}


def validate_output_template(template: str) -> None:
    if not template.startswith("/downloads/"):
        raise ValueError("Output template must start with /downloads/")
    if "\x00" in template:
        raise ValueError("Output template contains an invalid NUL character")
    if any(part == ".." for part in template.split("/")):
        raise ValueError("Output template may not traverse outside /downloads/")
    if "%(ext)" not in template:
        raise ValueError("Output template must contain the yt-dlp %(ext)s placeholder")


def ensure_unique_output_template(template: str) -> str:
    """Ensure two videos with the same title cannot resolve to the same path."""
    validate_output_template(template)
    if "%(id)" in template:
        return template
    marker = "%(ext)s"
    if ".%(ext)s" in template:
        return template.replace(".%(ext)s", " [%(id)s].%(ext)s", 1)
    if marker in template:
        return template.replace(marker, "[%(id)s].%(ext)s", 1)
    # validate_output_template currently prevents this branch, but keep a safe fallback.
    return f"{template} [%(id)s]"


def preview_output_template(template: str) -> str:
    validate_output_template(template)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _SAMPLE.get(key, f"<{key}>")

    return _TOKEN.sub(replace, ensure_unique_output_template(template))
