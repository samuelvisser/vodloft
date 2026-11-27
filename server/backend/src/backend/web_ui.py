"""The built UI, served by the backend itself when nothing in front of it does (the Debian package).

The Docker image keeps nginx for this; these routes give the same answers its configuration does.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

# Paths the backend answers itself. A page of the UI is never one of these, so a missing one is a 404.
BACKEND_PREFIXES = ("api/", "feeds/", "iptv/", "webdav/")

# Vite gives every built asset a content hash in its name, so a changed asset always has another URL.
_IMMUTABLE = "public, max-age=31536000, immutable"
# Files at a fixed URL that choose the current assets, or that must be checked after every update.
_REVALIDATE = {"index.html": "no-cache", "manifest.webmanifest": "no-cache", "offline.html": "no-cache", "sw.js": "no-store"}
_MEDIA_TYPES = {"manifest.webmanifest": "application/manifest+json"}


def add_web_ui(app: FastAPI, directory: Path) -> None:
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"The UI directory {root} has no index.html")

    def file_response(file: Path, name: str) -> FileResponse:
        if name.startswith("assets/"):
            cache = _IMMUTABLE
        else:
            cache = _REVALIDATE.get(name)
        headers = {"Cache-Control": cache} if cache else None
        return FileResponse(file, headers=headers, media_type=_MEDIA_TYPES.get(name))

    # The UI reads where the API is from here; the backend serves both, so it is always this one.
    @app.get("/config.json", include_in_schema=False)
    def ui_config():
        return JSONResponse({"API_URL": "/api"}, headers={"Cache-Control": "no-store"})

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def ui_file(path: str):
        if path.startswith(BACKEND_PREFIXES) or path in {"api", "feeds", "iptv", "webdav"}:
            raise HTTPException(status_code=404)
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            return file_response(file, path)
        if path.startswith("assets/"):
            raise HTTPException(status_code=404)
        # Any other path is a page of the single-page app, which React Router shows.
        return file_response(index, "index.html")
