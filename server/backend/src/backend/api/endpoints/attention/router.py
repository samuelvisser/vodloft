"""Needs attention: the open states the signed-in person may see, for Home."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.models.attention import AttentionRead
from backend.app import db_session
from backend.security.access import Access
from backend.security.deps import SignedIn
from backend.services.attention import open_states

router = APIRouter(prefix="/attention", tags=["Needs attention"])


@router.get("", response_model=list[AttentionRead])
def attention(access: Access = Depends(SignedIn())):
    with db_session() as s:
        return [AttentionRead.model_validate(row) for row in open_states(s, access)]
