"""Which API versions this server answers. Outside every version, and open to anyone, so a client such as the
browser extension can find out before it signs in whether it speaks this server's API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config import get_settings

from backend.api.models.api_versions import ApiVersionsRead, UnknownApiVersionRead
from backend.api.versions import API_ROOT, API_VERSIONS, CURRENT_API_VERSION, VERSIONS_PATH, api_version_of


router = APIRouter(tags=["API versions"])


@router.get(VERSIONS_PATH, response_model=ApiVersionsRead)
def api_versions():
    return ApiVersionsRead(
        versions=list(API_VERSIONS), current=CURRENT_API_VERSION, app_version=get_settings().app_version,
    )


@router.api_route(
    API_ROOT + "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def unknown_api_version(path: str):
    """A path under ``/api`` that no route answered. Within a version it is simply not there; outside every version
    the client speaks a version this server does not, and is told which ones it does."""
    version, _ = api_version_of(f"{API_ROOT}/{path}")
    if version is not None:
        raise HTTPException(status_code=404, detail="Not Found")
    body = UnknownApiVersionRead(
        detail=(
            f"This VODLoft server does not answer {API_ROOT}/{path}. Its API answers under "
            + ", ".join(f"{API_ROOT}/{v}/" for v in API_VERSIONS) + "."
        ),
        versions=list(API_VERSIONS),
        current=CURRENT_API_VERSION,
    )
    return JSONResponse(body.model_dump(mode="json", by_alias=True), status_code=404)
