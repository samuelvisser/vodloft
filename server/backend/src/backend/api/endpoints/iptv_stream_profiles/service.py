from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.iptv_stream_profile import (
    IptvStreamProfileAPICreate,
    IptvStreamProfileAPIRead,
    IptvStreamProfileAPIUpdate,
)
from backend.db.models.stream_profile import IptvStreamProfile
from backend.security.access import Access
from backend.services.iptv import next_channel_number
from backend.services.stream_profile_owners import owned_by
from backend.utils.helpers import generate_stream_profile_token
from ..stream_profiles.service import change_profile, new_profile, owned_profile

_OWN_FIELDS = frozenset({"channel_number"})


def get_iptv_stream_profiles_list(s: Session, access: Access) -> list[IptvStreamProfileAPIRead]:
    items = (
        owned_by(s.query(IptvStreamProfile), IptvStreamProfile.owner_user_id, access)
        .order_by(IptvStreamProfile.channel_number, IptvStreamProfile.id)
        .all()
    )
    return [IptvStreamProfileAPIRead.model_validate(item) for item in items]


def get_stream_profile_iptv(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfileAPIRead:
    return IptvStreamProfileAPIRead.model_validate(owned_profile(s, access, IptvStreamProfile, stream_profile_id))


def get_next_channel_number(s: Session, access: Access) -> int:
    return next_channel_number(s, access.user_id)


def create_stream_profile_iptv(
        s: Session,
        body: IptvStreamProfileAPICreate,
        access: Access,
) -> IptvStreamProfileAPIRead:
    channel_number = body.channel_number or next_channel_number(s, access.user_id)
    item = new_profile(s, access, IptvStreamProfile, body, exclude_fields=_OWN_FIELDS)
    item.channel_number = channel_number
    s.flush()
    return IptvStreamProfileAPIRead.model_validate(item)


def update_stream_profile_iptv(
        s: Session,
        access: Access,
        stream_profile_id: int,
        body: IptvStreamProfileAPIUpdate,
) -> IptvStreamProfileAPIRead:
    item = owned_profile(s, access, IptvStreamProfile, stream_profile_id)
    change_profile(item, body, exclude_fields=_OWN_FIELDS)
    if body.channel_number is not None:
        item.channel_number = body.channel_number
    s.flush()
    return IptvStreamProfileAPIRead.model_validate(item)


def regenerate_stream_profile_iptv_token(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfileAPIRead:
    """Rotate the channel's secret token, so its previous playlist, guide and channel addresses stop working."""
    item = owned_profile(s, access, IptvStreamProfile, stream_profile_id)
    item.token = generate_stream_profile_token()
    s.flush()
    return IptvStreamProfileAPIRead.model_validate(item)


def delete_stream_profile_iptv(s: Session, access: Access, stream_profile_id: int) -> IptvStreamProfileAPIRead:
    item = owned_profile(s, access, IptvStreamProfile, stream_profile_id)
    payload = IptvStreamProfileAPIRead.model_validate(item)
    s.delete(item)
    s.flush()
    return payload
