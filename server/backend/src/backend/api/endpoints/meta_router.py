from fastapi import APIRouter, HTTPException, Response

from .meta_service import *
from ..models.meta import *
from backend.security.access import Area, Level
from backend.security.deps import requires_any, signed_in
from backend.services.browser_extension import ZIP_NAME, extension_zip

router = APIRouter(tags=["Meta"])


@router.get("/health", dependencies=[signed_in()], response_model=HealthAPIRead)
def health():
    return get_health()


# Everyone the extension is of use to: who adds media or quick downloads, or sends a site's cookies.
@router.get(
    "/browser-extension", response_class=Response,
    dependencies=[requires_any((Area.ADD_MEDIA, Level.VIEW), (Area.QUICK_DOWNLOADS, Level.VIEW), (Area.SOURCES, Level.MANAGE))],
)
def browser_extension():
    """VODLoft's browser extension as a zip, to unzip and load into a browser."""
    try:
        content = extension_zip()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{ZIP_NAME}"'})
