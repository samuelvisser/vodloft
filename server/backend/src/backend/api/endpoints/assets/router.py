from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.security.access import Area, Level
from backend.security.deps import requires
from backend.services.thumbnails import thumbnail_file

router = APIRouter(prefix="/assets", tags=["Assets"])

# A thumbnail's name never changes for its video, but a new frame may replace it.
_CACHE_CONTROL = "private, max-age=86400"


@router.get("/thumbnails/{name}", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_class=FileResponse)
def thumbnail(name: str):
    """A thumbnail VODLoft made from a video's first frame."""
    path = thumbnail_file(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})
