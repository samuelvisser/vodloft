from fastapi import APIRouter, status

from .service import (
    create_stream_profile_webdav,
    delete_stream_profile_webdav,
    get_webdav_stream_profiles_list,
    get_stream_profile_webdav,
    regenerate_stream_profile_webdav_token,
    update_stream_profile_webdav,
)
from ...models.webdav_stream_profile import (
    WebdavStreamProfileAPICreate,
    WebdavStreamProfileAPIRead,
    WebdavStreamProfileAPIUpdate,
)
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, requires_any, signed_in

router = APIRouter(prefix="/webdav-stream-profiles", tags=["Stream Profiles (webdav)"])


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[WebdavStreamProfileAPIRead])
def webdav_stream_profiles_list(access: Access = signed_in()):
    """The WebDAV stream profiles the user may see."""
    with db_session() as s:
        return get_webdav_stream_profiles_list(s, access)


@router.post("", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=WebdavStreamProfileAPIRead, status_code=status.HTTP_201_CREATED)
def webdav_stream_profiles_create(body: WebdavStreamProfileAPICreate, access: Access = signed_in()):
    """Create a WebDAV stream profile: a share of the collection as a TV show."""
    return run_write_transaction(lambda s: create_stream_profile_webdav(s, body, access))


@router.get("/{webdav_stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=WebdavStreamProfileAPIRead)
def webdav_stream_profiles_detail(webdav_stream_profile_id: int, access: Access = signed_in()):
    with db_session() as s:
        return get_stream_profile_webdav(s, access, webdav_stream_profile_id)


@router.patch("/{webdav_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=WebdavStreamProfileAPIRead)
def webdav_stream_profiles_update(webdav_stream_profile_id: int, body: WebdavStreamProfileAPIUpdate, access: Access = signed_in()):
    return run_write_transaction(lambda s: update_stream_profile_webdav(s, access, webdav_stream_profile_id, body))


@router.post("/{webdav_stream_profile_id}/regenerate-token", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=WebdavStreamProfileAPIRead)
def webdav_stream_profiles_regenerate_token(webdav_stream_profile_id: int, access: Access = signed_in()):
    """Rotate the secret token in the share's address, so a leaked one stops working."""
    return run_write_transaction(lambda s: regenerate_stream_profile_webdav_token(s, access, webdav_stream_profile_id))


@router.delete("/{webdav_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=WebdavStreamProfileAPIRead)
def webdav_stream_profiles_delete(webdav_stream_profile_id: int, access: Access = signed_in()):
    return run_write_transaction(lambda s: delete_stream_profile_webdav(s, access, webdav_stream_profile_id))
