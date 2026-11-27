"""The versions of VODLoft's HTTP API.

Every endpoint lives under ``/api/<version>/``. A client that is released apart from the server, such as the
browser extension, asks ``GET /api/versions`` which versions this server answers and picks one it speaks. A
version stays as long as it is listed here, so a client built for it keeps working while the server moves on.
"""
from __future__ import annotations

API_ROOT = "/api"

# Every version this server answers, oldest first. The UI ships with the server and uses the newest.
API_VERSIONS: tuple[str, ...] = ("v1",)
CURRENT_API_VERSION = API_VERSIONS[-1]
CURRENT_API_PREFIX = f"{API_ROOT}/{CURRENT_API_VERSION}"

# What a client calls to learn the versions above. It is outside every version, so any client can read it.
VERSIONS_PATH = f"{API_ROOT}/versions"


def is_api_path(path: str) -> bool:
    """Whether ``path`` is one of the API's, of any version."""
    return path == API_ROOT or path.startswith(API_ROOT + "/")


def api_version_of(path: str) -> tuple[str | None, str]:
    """The API version ``path`` is under, if it is one this server answers, and the path within it.

    ``/api/v1/collections`` is ``("v1", "/collections")``; ``/api/collections`` is ``(None, "/collections")``.
    """
    if not is_api_path(path):
        return None, path
    rest = path[len(API_ROOT):]
    version, slash, inner = rest.lstrip("/").partition("/")
    if version in API_VERSIONS:
        return version, slash + inner
    return None, rest
