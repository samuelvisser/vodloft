"""VODLoft's browser extension, which adds the media of the page a browser shows to VODLoft, quick downloads it, and
sends a site's cookies to VODLoft, as the zip VODLoft offers for download: the user unzips it and loads it into their
browser. The UI's build makes it, from the UI's own code, into ui/dist-extension."""
from __future__ import annotations

import io
import zipfile

from backend.config import PROJECT_ROOT

EXTENSION_DIRECTORY = PROJECT_ROOT / "ui" / "dist-extension"
ZIP_NAME = "vodloft-browser-extension.zip"


def extension_zip() -> bytes:
    """The extension's files, in a folder of their own inside the zip. Raises FileNotFoundError when this VODLoft
    has no copy of the extension."""
    if not (EXTENSION_DIRECTORY / "manifest.json").is_file():
        raise FileNotFoundError("This VODLoft has no copy of its browser extension. Build the UI to make it.")
    folder = ZIP_NAME.removesuffix(".zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION_DIRECTORY.rglob("*")):
            if path.is_file():
                archive.write(path, f"{folder}/{path.relative_to(EXTENSION_DIRECTORY).as_posix()}")
    return buffer.getvalue()
