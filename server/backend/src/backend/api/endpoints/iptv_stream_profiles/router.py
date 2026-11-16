from fastapi import APIRouter, status

from .service import (
    create_stream_profile_iptv,
    delete_stream_profile_iptv,
    get_iptv_stream_profiles_list,
    get_next_channel_number,
    get_stream_profile_iptv,
    regenerate_stream_profile_iptv_token,
    update_stream_profile_iptv,
)
from ...models.iptv_stream_profile import (
    IptvStreamProfileAPICreate,
    IptvStreamProfileAPIRead,
    IptvStreamProfileAPIUpdate,
)
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, requires_any, signed_in

router = APIRouter(prefix="/iptv-stream-profiles", tags=["Stream Profiles (iptv)"])


@router.get("", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=list[IptvStreamProfileAPIRead])
def iptv_stream_profiles_list(access: Access = signed_in()):
    """The IPTV stream profiles the user may see, in channel number order."""
    with db_session() as s:
        return get_iptv_stream_profiles_list(s, access)


@router.get("/next-channel-number", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=int)
def iptv_stream_profiles_next_channel_number(access: Access = signed_in()):
    """The number a new channel of the user gets when it is left empty."""
    with db_session() as s:
        return get_next_channel_number(s, access)


@router.post("", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=IptvStreamProfileAPIRead, status_code=status.HTTP_201_CREATED)
def iptv_stream_profiles_create(body: IptvStreamProfileAPICreate, access: Access = signed_in()):
    """Create an IPTV stream profile: a channel for the collection."""
    return run_write_transaction(lambda s: create_stream_profile_iptv(s, body, access))


@router.get("/{iptv_stream_profile_id}", dependencies=[requires_any((Area.STREAM_PROFILES, Level.VIEW), (Area.LIBRARY, Level.MANAGE))], response_model=IptvStreamProfileAPIRead)
def iptv_stream_profiles_detail(iptv_stream_profile_id: int, access: Access = signed_in()):
    with db_session() as s:
        return get_stream_profile_iptv(s, access, iptv_stream_profile_id)


@router.patch("/{iptv_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=IptvStreamProfileAPIRead)
def iptv_stream_profiles_update(iptv_stream_profile_id: int, body: IptvStreamProfileAPIUpdate, access: Access = signed_in()):
    return run_write_transaction(lambda s: update_stream_profile_iptv(s, access, iptv_stream_profile_id, body))


@router.post("/{iptv_stream_profile_id}/regenerate-token", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=IptvStreamProfileAPIRead)
def iptv_stream_profiles_regenerate_token(iptv_stream_profile_id: int, access: Access = signed_in()):
    """Rotate the secret token in the channel's addresses, so a leaked one stops working."""
    return run_write_transaction(lambda s: regenerate_stream_profile_iptv_token(s, access, iptv_stream_profile_id))


@router.delete("/{iptv_stream_profile_id}", dependencies=[requires(Area.STREAM_PROFILES, Level.VIEW)], response_model=IptvStreamProfileAPIRead)
def iptv_stream_profiles_delete(iptv_stream_profile_id: int, access: Access = signed_in()):
    return run_write_transaction(lambda s: delete_stream_profile_iptv(s, access, iptv_stream_profile_id))
