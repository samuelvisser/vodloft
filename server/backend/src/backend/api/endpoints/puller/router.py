from fastapi import APIRouter

from backend.security.access import Access

from backend.api.models.puller import FrontendPullAPIRead
from .service import get_frontend_pull
from backend.security.deps import signed_in


router = APIRouter(prefix="/pull", tags=["Frontend Puller"])


@router.get("", response_model=FrontendPullAPIRead)
def frontend_pull(access: Access = signed_in()):
    """Return VODLoft's generic changing-execution snapshot, as far as this user may see it."""
    return get_frontend_pull(access)
