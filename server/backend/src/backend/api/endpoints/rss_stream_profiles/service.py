from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from backend.api.models.rss_stream_profile import (
    RssStreamProfileAPICreate,
    RssStreamProfileAPIRead,
    RssStreamProfileAPIUpdate,
)
from backend.db.models.stream_profile import RssStreamProfile
from backend.utils.feed_urls import build_rss_feed_url, request_base_url
from backend.security.access import Access
from backend.services.stream_profile_owners import owned_by
from backend.utils.helpers import generate_stream_profile_token
from ..stream_profiles.service import change_profile, new_profile, owned_profile

_OWN_FIELDS = frozenset({"feed_url"})


def get_rss_stream_profiles_list(s: Session, access: Access) -> list[RssStreamProfileAPIRead]:
    items = (
        owned_by(s.query(RssStreamProfile), RssStreamProfile.owner_user_id, access)
        .order_by(RssStreamProfile.id)
        .all()
    )
    return [RssStreamProfileAPIRead.model_validate(item) for item in items]


def get_stream_profile_rss(
        s: Session,
        access: Access,
        stream_profile_id: int,
) -> RssStreamProfileAPIRead:
    return RssStreamProfileAPIRead.model_validate(owned_profile(s, access, RssStreamProfile, stream_profile_id))


def create_stream_profile_rss(
        s: Session,
        request: Request,
        body: RssStreamProfileAPICreate,
        access: Access,
) -> RssStreamProfileAPIRead:
    item = new_profile(
        s, access, RssStreamProfile, body, exclude_fields=_OWN_FIELDS, video_output_mode=body.video_output_mode,
    )
    item.feed_url = (body.feed_url or "").strip() or build_rss_feed_url(
        request_base_url(request),
        token=item.token,
        collection_slug=item.collection.slug,
    )
    s.flush()
    return RssStreamProfileAPIRead.model_validate(item)


def update_stream_profile_rss(
        s: Session,
        access: Access,
        stream_profile_id: int,
        body: RssStreamProfileAPIUpdate,
) -> RssStreamProfileAPIRead:
    item = owned_profile(s, access, RssStreamProfile, stream_profile_id)
    change_profile(item, body, exclude_fields=_OWN_FIELDS, video_output_mode=body.video_output_mode)
    item.feed_url = body.feed_url.strip()
    s.flush()
    return RssStreamProfileAPIRead.model_validate(item)


def regenerate_stream_profile_rss_token(
        s: Session,
        access: Access,
        request: Request,
        stream_profile_id: int,
) -> RssStreamProfileAPIRead:
    """Rotate a profile's secret token and invalidate its previous feed URLs.

    The new feed URL is always built on the address VODLoft was reached on, so
    regenerating also replaces an address the profile was imported with.
    """
    item = owned_profile(s, access, RssStreamProfile, stream_profile_id)
    item.token = generate_stream_profile_token()
    item.feed_url = build_rss_feed_url(
        request_base_url(request),
        token=item.token,
        collection_slug=item.collection.slug,
    )
    s.flush()
    return RssStreamProfileAPIRead.model_validate(item)


def delete_stream_profile_rss(
        s: Session,
        access: Access,
        stream_profile_id: int,
) -> RssStreamProfileAPIRead:
    item = owned_profile(s, access, RssStreamProfile, stream_profile_id)
    payload = RssStreamProfileAPIRead.model_validate(item)
    s.delete(item)
    s.flush()
    return payload
