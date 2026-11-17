from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.webdav_stream_profile import (
    WebdavStreamProfileAPICreate,
    WebdavStreamProfileAPIRead,
    WebdavStreamProfileAPIUpdate,
)
from backend.db.models.stream_profile import WebdavStreamProfile
from backend.security.access import Access
from backend.services.stream_profile_owners import owned_by
from backend.utils.helpers import generate_stream_profile_token
from ..stream_profiles.service import change_profile, new_profile, owned_profile


def get_webdav_stream_profiles_list(s: Session, access: Access) -> list[WebdavStreamProfileAPIRead]:
    items = (
        owned_by(s.query(WebdavStreamProfile), WebdavStreamProfile.owner_user_id, access)
        .order_by(WebdavStreamProfile.id)
        .all()
    )
    return [WebdavStreamProfileAPIRead.model_validate(item) for item in items]


def get_stream_profile_webdav(s: Session, access: Access, stream_profile_id: int) -> WebdavStreamProfileAPIRead:
    return WebdavStreamProfileAPIRead.model_validate(owned_profile(s, access, WebdavStreamProfile, stream_profile_id))


def create_stream_profile_webdav(
        s: Session,
        body: WebdavStreamProfileAPICreate,
        access: Access,
) -> WebdavStreamProfileAPIRead:
    item = new_profile(s, access, WebdavStreamProfile, body)
    s.flush()
    return WebdavStreamProfileAPIRead.model_validate(item)


def update_stream_profile_webdav(
        s: Session,
        access: Access,
        stream_profile_id: int,
        body: WebdavStreamProfileAPIUpdate,
) -> WebdavStreamProfileAPIRead:
    item = owned_profile(s, access, WebdavStreamProfile, stream_profile_id)
    change_profile(item, body)
    s.flush()
    return WebdavStreamProfileAPIRead.model_validate(item)


def regenerate_stream_profile_webdav_token(
        s: Session, access: Access, stream_profile_id: int,
) -> WebdavStreamProfileAPIRead:
    """Rotate the share's secret token, so its previous address stops working."""
    item = owned_profile(s, access, WebdavStreamProfile, stream_profile_id)
    item.token = generate_stream_profile_token()
    s.flush()
    return WebdavStreamProfileAPIRead.model_validate(item)


def delete_stream_profile_webdav(s: Session, access: Access, stream_profile_id: int) -> WebdavStreamProfileAPIRead:
    item = owned_profile(s, access, WebdavStreamProfile, stream_profile_id)
    payload = WebdavStreamProfileAPIRead.model_validate(item)
    s.delete(item)
    s.flush()
    return payload
