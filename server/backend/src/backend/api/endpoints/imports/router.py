"""Imports from other programs: upload their config folder, preview, run, and read the report.

Only administrators import: an upload can hold another program's sign-ins.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from backend.app import db_session
from backend.db.models import ImportRun
from backend.security.access import Area, Level
from backend.security.deps import requires
from backend.services.adoption import AdoptionError, real_path
from backend.services.import_uploads import (
    UploadError, UploadOffsetError, begin_upload, finish_upload, remove_upload, upload_from_folder, upload_status,
    write_chunk,
)
from backend.services.imports import (
    ImportOptions, ImportServiceError, get_importer, preview, run_summary, run_view, start_run,
)
from backend.utils.feed_urls import request_base_url
from importer.registry import all_importers

from ...models.imports import (
    ImportChunkAPIRead, ImporterAPIRead, ImportFolderAPIRequest, ImportOptionsAPIRequest, ImportPreviewAPIRead,
    ImportRunAPIRead, ImportRunSummaryAPIRead, ImportUploadAPIRequest, ImportUploadStatusAPIRead,
)

router = APIRouter(prefix="/imports", tags=["imports"])
_ADMIN = [requires(Area.USERS, Level.MANAGE)]


def _importer(key: str):
    try:
        return get_importer(key)
    except ImportServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _options(body: ImportOptionsAPIRequest, request: Request) -> ImportOptions:
    return ImportOptions(
        path_map=tuple(body.path_map) if body.path_map else None,
        collections=tuple(body.collections) if body.collections is not None else None,
        settings=tuple(body.settings) if body.settings is not None else None,
        enable_download_profiles=body.enable_download_profiles,
        match_existing_files=body.match_existing_files,
        rename_existing_files=body.rename_existing_files,
        merge_profiles=body.merge_profiles,
        templates=body.templates,
        feed_base_url=request_base_url(request),
    )


@router.get("", dependencies=_ADMIN, response_model=list[ImporterAPIRead])
def importers_list():
    """Every importer, with its upload and its last run."""
    with db_session() as s:
        out = []
        for importer in all_importers():
            last = s.scalar(select(ImportRun).where(ImportRun.importer == importer.key)
                            .order_by(ImportRun.id.desc()).limit(1))
            out.append(ImporterAPIRead.model_validate({
                "key": importer.key, "name": importer.name, "upload": upload_status(importer),
                "files": [rule.pattern for rule in importer.upload_files if not rule.secret],
                "secret_files": [rule.pattern for rule in importer.upload_files if rule.secret],
                "last_run": run_summary(last) if last else None,
            }))
        return out


@router.get("/{importer_key}/upload", dependencies=_ADMIN, response_model=ImportUploadStatusAPIRead)
def import_upload_status(importer_key: str):
    return ImportUploadStatusAPIRead.model_validate(upload_status(_importer(importer_key)))


@router.post("/{importer_key}/upload", dependencies=_ADMIN, response_model=ImportUploadStatusAPIRead)
def import_upload_begin(importer_key: str, body: ImportUploadAPIRequest):
    """Start an upload. The answer lists the files to send; the rest of the folder is not needed."""
    try:
        result = begin_upload(_importer(importer_key), [(item.path, item.size) for item in body.files],
                              include_secrets=body.include_secrets)
    except UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportUploadStatusAPIRead.model_validate(result)


@router.put("/{importer_key}/upload/chunk", dependencies=_ADMIN, response_model=ImportChunkAPIRead)
async def import_upload_chunk(
    importer_key: str, request: Request, path: str = Query(min_length=1), offset: int = Query(ge=0),
):
    """One chunk of a file, at ``offset``. A chunk that doesn't continue the file says where it should."""
    importer = _importer(importer_key)
    data = await request.body()
    try:
        received = write_chunk(importer, path, offset, data)
    except UploadOffsetError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "received": exc.received}) from exc
    except UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportChunkAPIRead(received=received)


@router.post("/{importer_key}/upload/finish", dependencies=_ADMIN, response_model=ImportUploadStatusAPIRead)
def import_upload_finish(importer_key: str):
    try:
        return ImportUploadStatusAPIRead.model_validate(finish_upload(_importer(importer_key)))
    except UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{importer_key}/upload/from-folder", dependencies=_ADMIN, response_model=ImportUploadStatusAPIRead)
def import_upload_from_folder(importer_key: str, body: ImportFolderAPIRequest):
    """Use a config folder VODLoft can already see, instead of uploading it."""
    try:
        folder = real_path(body.folder.rstrip("/") + "/")
        return ImportUploadStatusAPIRead.model_validate(
            upload_from_folder(_importer(importer_key), folder, include_secrets=body.include_secrets),
        )
    except (UploadError, AdoptionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{importer_key}/upload", dependencies=_ADMIN, status_code=status.HTTP_204_NO_CONTENT)
def import_upload_remove(importer_key: str):
    remove_upload(_importer(importer_key))


@router.post("/{importer_key}/preview", dependencies=_ADMIN, response_model=ImportPreviewAPIRead)
def import_preview(importer_key: str, body: ImportOptionsAPIRequest, request: Request):
    """What the import would do. Nothing is written."""
    importer = _importer(importer_key)
    with db_session() as s:
        try:
            return ImportPreviewAPIRead.model_validate(preview(s, importer, _options(body, request)))
        except (UploadError, ImportServiceError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{importer_key}/runs", dependencies=_ADMIN, response_model=ImportRunSummaryAPIRead,
             status_code=status.HTTP_202_ACCEPTED)
def import_run(importer_key: str, body: ImportOptionsAPIRequest, request: Request):
    """Run the import as previewed. It runs as a task; its files are adopted once each Collection is indexed."""
    importer = _importer(importer_key)
    with db_session() as s:
        try:
            run = start_run(s, importer, _options(body, request))
        except ImportServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        s.commit()
        return ImportRunSummaryAPIRead.model_validate(run_summary(run))


@router.get("/{importer_key}/runs", dependencies=_ADMIN, response_model=list[ImportRunSummaryAPIRead])
def import_runs(importer_key: str):
    importer = _importer(importer_key)
    with db_session() as s:
        runs = s.scalars(select(ImportRun).where(ImportRun.importer == importer.key).order_by(ImportRun.id.desc()))
        return [ImportRunSummaryAPIRead.model_validate(run_summary(run)) for run in runs]


@router.get("/{importer_key}/runs/{run_id}", dependencies=_ADMIN, response_model=ImportRunAPIRead)
def import_run_read(importer_key: str, run_id: int):
    """A run with its full report."""
    importer = _importer(importer_key)
    with db_session() as s:
        run = s.get(ImportRun, run_id)
        if run is None or run.importer != importer.key:
            raise HTTPException(status_code=404, detail="Import run not found")
        return ImportRunAPIRead.model_validate(run_view(s, run))
