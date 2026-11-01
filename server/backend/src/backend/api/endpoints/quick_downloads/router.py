from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.api.models.quick_download import (
    QuickDownloadAPICreate,
    QuickDownloadHistoryAPIRead,
    QuickDownloadOperationAccepted,
    QuickDownloadOptionsAPIRead,
    QuickDownloadOptionsAPIRequest,
    QuickDownloadPreviewAPIRead,
    QuickDownloadsAPIRead,
)
from backend.api.models.settings import QuickDownloadPreferencesValue, QuickDownloadSettingsForUser
from backend.app import db_session
from backend.services.quick_downloads import QuickDownloadRefused

from .service import (
    PreferencesNeedAnAccount,
    RangeNotSatisfiable,
    clear_quick_download_history,
    quick_download_settings_for,
    save_quick_download_preferences,
    quick_download_history,
    file_delivery,
    list_quick_downloads,
    quick_download_options,
    quick_download_preview,
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


@router.post("/preview", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=Optional[QuickDownloadPreviewAPIRead])
def quick_download_link_preview(body: QuickDownloadOptionsAPIRequest, access: Access = signed_in()):
    """A link's title and thumbnail from a faster lookup, to show while ``/options`` runs; null when there is none."""
    with db_session() as s:
        return quick_download_preview(s, access, body)


@router.post("/options", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadOptionsAPIRead)
def quick_download_option_list(body: QuickDownloadOptionsAPIRequest, access: Access = signed_in()):
    """What a link can be quick downloaded as, with sizes where its Source reports them."""
    from backend.api.endpoints.sources.service import LinkNotRecognisedError

    with db_session() as s:
        try:
            return quick_download_options(s, access, body)
        except LinkNotRecognisedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/settings", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadSettingsForUser)
def quick_download_settings(access: Access = signed_in()):
    """The rules in Settings › Quick download, with the user's own defaults where they saved them."""
    with db_session() as s:
        return quick_download_settings_for(s, access)


@router.put("/preferences", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadSettingsForUser)
def quick_download_preferences_save(body: QuickDownloadPreferencesValue, access: Access = signed_in()):
    """Save the user's own Quick download defaults, to start from next time."""
    with db_session() as s:
        try:
            result = save_quick_download_preferences(s, access, body)
        except PreferencesNeedAnAccount as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        s.commit()
        return result


@router.delete("/preferences", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadSettingsForUser)
def quick_download_preferences_forget(access: Access = signed_in()):
    """Go back to the install's Quick download defaults."""
    with db_session() as s:
        try:
            result = save_quick_download_preferences(s, access, None)
        except PreferencesNeedAnAccount as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        s.commit()
        return result


@router.get("", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=QuickDownloadsAPIRead)
def quick_download_list(access: Access = signed_in()):
    """Quick downloads still working, and files ready to download: the user's own, or everyone's for those who manage them."""
    with db_session() as s:
        return list_quick_downloads(s, access)


@router.get("/history", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], response_model=list[QuickDownloadHistoryAPIRead])
def quick_download_history_list(access: Access = signed_in()):
    """Past quick downloads, newest first, and how each one ended."""
    with db_session() as s:
        return quick_download_history(s, access)


@router.delete("/history", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], status_code=status.HTTP_204_NO_CONTENT)
def quick_download_history_clear(access: Access = signed_in()):
    """Forget every finished quick download. Ones still working or waiting to be downloaded stay."""
    with db_session() as s:
        clear_quick_download_history(s, access)
    return Response(status_code=204)


@router.api_route("/{quick_id}/file", dependencies=[requires(Area.QUICK_DOWNLOADS, Level.VIEW)], methods=["GET", "HEAD"])
def quick_download_file(quick_id: str, request: Request, access: Access = signed_in()):
    """The ready file, as an attachment. Range requests resume a download.

    VODLoft deletes the file a while after every byte of it has been sent.
    """
    try:
        delivery = file_delivery(access, quick_id, request.headers.get("range"))
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
def quick_download_delete(quick_id: str, access: Access = signed_in()):
    """Cancel a quick download that is still working, or delete a file that is ready."""
    with db_session() as s:
        if not remove_quick_download(s, access, quick_id):
            raise HTTPException(status_code=404, detail="Quick download not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
