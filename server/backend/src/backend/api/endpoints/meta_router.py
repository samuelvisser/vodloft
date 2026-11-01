from fastapi import APIRouter

from .meta_service import *
from ..models.meta import *
from backend.security.deps import signed_in

router = APIRouter(tags=["Meta"])


@router.get("/health", dependencies=[signed_in()], response_model=HealthAPIRead)
def health():
    return get_health()