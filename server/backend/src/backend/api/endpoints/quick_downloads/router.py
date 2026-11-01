from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.api.models.quick_download import (
    QuickDownloadAPICreate,
    QuickDownloadHistoryAPIRead,
    QuickDownloadOperationAccepted,
    QuickDownloadOptionsAPIRead,
    QuickDownloadOptionsAPIRequest,
    QuickDownloadsAPIRead,
)
from backend.app import db_session
from backend.services.quick_downloads import QuickDownloadRefused

from .service import (
    RangeNotSatisfiable,
    clear_quick_download_history,
    quick_download_history,
    file_delivery,
    list_quick_downloads,
    quick_download_options,
    remove_quick_download,
    start_quick_download,
)
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in


router = APIRouter(prefix="/quick-downloads", tags=["Quick downloads"])


@router.post("", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadOperationAccepted, status_code=status.HTTP_202_ACCEPTED)
def quick_download_create(body: QuickDownloadAPICreate, access: Access = signed_in()):
    """Fetch one video, episode or movie as a file to download, without adding it to the library."""
    from backend.api.endpoints.sources.service import LinkNotRecognisedError

    with db_session() as s:
        try:
            result = start_quick_download(s, access, body)
            s.commit()
            return result
        except (LinkNotRecognisedError, QuickDownloadRefused) as exc:
            s.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            s.rollback()
            raise


@router.post("/options", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadOptionsAPIRead)
def quick_download_option_list(body: QuickDownloadOptionsAPIRequest, access: Access = signed_in()):
    """What a link can be quick downloaded as, with sizes where its Source reports them."""
    from backend.api.endpoints.sources.service import LinkNotRecognisedError

    with db_session() as s:
        try:
            return quick_download_options(s, access, body)
        except LinkNotRecognisedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadsAPIRead)
def quick_download_list():
    """Quick downloads still working, and files ready to download."""
    with db_session() as s:
        return list_quick_downloads(s)


@router.get("/history", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=list[QuickDownloadHistoryAPIRead])
def quick_download_history_list():
    """Past quick downloads, newest first, and how each one ended."""
    with db_session() as s:
        return quick_download_history(s)


@router.delete("/history", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], status_code=status.HTTP_204_NO_CONTENT)
def quick_download_history_clear():
    """Forget every finished quick download. Ones still working or waiting to be downloaded stay."""
    with db_session() as s:
        clear_quick_download_history(s)
    return Response(status_code=204)


@router.api_route("/{quick_id}/file", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], methods=["GET", "HEAD"])
def quick_download_file(quick_id: str, request: Request):
    """The ready file, as an attachment. Range requests resume a download.

    VODLoft deletes the file a while after every byte of it has been sent.
    """
    try:
        delivery = file_delivery(quick_id, request.headers.get("range"))
    except RangeNotSatisfiable as exc:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{exc.args[0]}"})
    if delivery is None:
        raise HTTPException(status_code=404, detail="This file is no longer available")
    status_code = 206 if delivery.partial else 200
    if request.method == "HEAD":
        return Response(status_code=status_code, headers=delivery.headers, media_type=delivery.media_type)
    return StreamingResponse(
        delivery.chunks(), status_code=status_code, headers=delivery.headers, media_type=delivery.media_type,
    )


@router.delete("/{quick_id}", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], status_code=status.HTTP_204_NO_CONTENT)
def quick_download_delete(quick_id: str):
    """Cancel a quick download that is still working, or delete a file that is ready."""
    with db_session() as s:
        if not remove_quick_download(s, quick_id):
            raise HTTPException(status_code=404, detail="Quick download not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
