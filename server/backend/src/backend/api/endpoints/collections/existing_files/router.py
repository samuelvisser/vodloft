"""Match existing files: find the files already on disk for a Collection, and adopt them."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import db_session
from backend.db.models import Collection, CollectionLocalMediaProfile, DownloadProfile, ExistingFileScan
from backend.security.access import Area, Level
from backend.security.deps import requires
from backend.services.adoption import AdoptionError
from backend.services.existing_files import (
    ExistingFilesError,
    adopt_matches,
    finish_scan,
    list_folders,
    profile_review,
    request_scan,
    scan_folder_for,
    scan_view,
)

from ....models.existing_files import (
    ExistingFilesAdoptAPIRequest,
    ExistingFilesAdoptAPIResult,
    ExistingFilesFinishAPIRequest,
    ExistingFilesFinishAPIResult,
    ExistingFilesOpenScanAPIRead,
    ExistingFilesProfileReviewAPIRead,
    ExistingFilesScanAPIRead,
    ExistingFilesScanAPIRequest,
    ExistingFilesScanSummaryAPIRead,
    FolderListAPIRead,
)

router = APIRouter()
_MANAGE = [requires(Area.LIBRARY, Level.MANAGE)]


def _collection(s: Session, slug: str) -> Collection:
    collection = s.scalar(select(Collection).where(Collection.slug == slug))
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _profile(s: Session, profile_id: int) -> CollectionLocalMediaProfile:
    profile = s.get(CollectionLocalMediaProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Local Media Profile not found")
    return profile


def _scan(s: Session, collection: Collection, profile_id: int) -> ExistingFileScan | None:
    return s.scalar(select(ExistingFileScan).where(
        ExistingFileScan.collection_id == collection.id,
        ExistingFileScan.local_media_profile_id == profile_id,
    ))


def _read(s: Session, collection: Collection, profile: CollectionLocalMediaProfile) -> ExistingFilesScanAPIRead:
    scan = _scan(s, collection, profile.id)
    base = {"default_folder": scan_folder_for(collection, profile), "local_media_profile_id": profile.id}
    if scan is None:
        return ExistingFilesScanAPIRead(status="none", **base)
    view = scan_view(s, scan)
    view.pop("local_media_profile_id", None)
    return ExistingFilesScanAPIRead.model_validate({**view, **base})


@router.get("/existing-files/folders", dependencies=_MANAGE, response_model=FolderListAPIRead)
def existing_files_folders(folder: str = Query(default="/downloads")):
    """The folders inside a /downloads/ folder, for picking the folder to scan."""
    try:
        return FolderListAPIRead.model_validate(list_folders(folder))
    except (ExistingFilesError, AdoptionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/existing-files/open", dependencies=_MANAGE, response_model=list[ExistingFilesOpenScanAPIRead])
def existing_files_open():
    """Every scan of every Collection that still needs a person, without its files."""
    with db_session() as s:
        rows = s.execute(
            select(ExistingFileScan, Collection, CollectionLocalMediaProfile)
            .join(Collection, Collection.id == ExistingFileScan.collection_id)
            .join(CollectionLocalMediaProfile, CollectionLocalMediaProfile.id == ExistingFileScan.local_media_profile_id)
            .where(ExistingFileScan.status != "finished")
            .order_by(Collection.title, CollectionLocalMediaProfile.name)
        ).all()
        return [
            ExistingFilesOpenScanAPIRead.model_validate({
                **scan_view(s, scan), "collection_slug": collection.slug, "collection_title": collection.title,
                "local_media_profile_name": profile.name,
            })
            for scan, collection, profile in rows
        ]


@router.get(
    "/existing-files/profiles/{local_media_profile_id}", dependencies=_MANAGE,
    response_model=ExistingFilesProfileReviewAPIRead,
)
def existing_files_profile(local_media_profile_id: int):
    """The open scans of one Local Media Profile, as one review of its whole folder."""
    with db_session() as s:
        return ExistingFilesProfileReviewAPIRead.model_validate(profile_review(s, _profile(s, local_media_profile_id)))


@router.get("/{collection_slug}/existing-files/scans", dependencies=_MANAGE, response_model=list[ExistingFilesScanSummaryAPIRead])
def existing_files_scans(collection_slug: str):
    """Every scan of this Collection that still needs a person, without its files."""
    with db_session() as s:
        collection = _collection(s, collection_slug)
        scans = s.scalars(select(ExistingFileScan).where(
            ExistingFileScan.collection_id == collection.id, ExistingFileScan.status != "finished",
        ))
        out = []
        for scan in scans:
            view = scan_view(s, scan)
            out.append(ExistingFilesScanSummaryAPIRead.model_validate({
                key: view[key] for key in ("status", "local_media_profile_id", "held_download_profiles", "counts")
            }))
        return out


@router.get("/{collection_slug}/existing-files", dependencies=_MANAGE, response_model=ExistingFilesScanAPIRead)
def existing_files_read(collection_slug: str, local_media_profile_id: int = Query(gt=0)):
    """The latest scan for this Collection and Local Media Profile, with its matches."""
    with db_session() as s:
        collection = _collection(s, collection_slug)
        return _read(s, collection, _profile(s, local_media_profile_id))


@router.post("/{collection_slug}/existing-files/scan", dependencies=_MANAGE, response_model=ExistingFilesScanAPIRead)
def existing_files_scan(collection_slug: str, body: ExistingFilesScanAPIRequest):
    """Scan a folder for this Collection's files. A new scan replaces the last one."""
    with db_session() as s:
        collection = _collection(s, collection_slug)
        profile = _profile(s, body.local_media_profile_id)
        try:
            request_scan(s, collection, profile, folder=body.folder, template=body.template)
            s.commit()
        except (ExistingFilesError, AdoptionError) as exc:
            s.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _read(s, collection, profile)


@router.post("/{collection_slug}/existing-files/adopt", dependencies=_MANAGE, response_model=ExistingFilesAdoptAPIResult)
def existing_files_adopt(collection_slug: str, body: ExistingFilesAdoptAPIRequest):
    """Adopt matched files: VODLoft records them as downloaded and won't download those episodes again."""
    with db_session() as s:
        collection = _collection(s, collection_slug)
        scan = _scan(s, collection, body.local_media_profile_id)
        if scan is None or scan.status not in ("ready", "finished"):
            raise HTTPException(status_code=409, detail="There are no matches to adopt yet")
        result = adopt_matches(s, scan, [(match.path, match.episode_id) for match in body.matches])
        s.commit()
        return ExistingFilesAdoptAPIResult.model_validate(result)


@router.post("/{collection_slug}/existing-files/finish", dependencies=_MANAGE, response_model=ExistingFilesFinishAPIResult)
def existing_files_finish(collection_slug: str, body: ExistingFilesFinishAPIRequest):
    """Done matching: switch the Download Profiles that waited for it back on."""
    with db_session() as s:
        collection = _collection(s, collection_slug)
        scan = _scan(s, collection, body.local_media_profile_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="No scan for this profile")
        enabled = finish_scan(s, scan)
        s.commit()
        return ExistingFilesFinishAPIResult(download_profiles_enabled=enabled)
