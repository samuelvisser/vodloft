from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.auth import AuthMeRead, AuthUserRead, SourceLimitRead
from backend.db.models import User
from backend.security.access import Access
from backend.services import users


def describe_access(session: Session, access: Access) -> AuthMeRead:
    user = session.get(User, access.user_id) if access.user_id is not None else None
    return AuthMeRead(
        accounts_enabled=users.accounts_enabled(session),
        recovery=access.recovery,
        user=None if user is None else AuthUserRead.model_validate(user),
        levels={area.value: level.value for area, level in access.levels.items()},
        administrator=access.is_administrator,
        sources=None if access.source_limits is None else [
            SourceLimitRead(source_key=limit.source_key, domains=None if limit.domains is None else list(limit.domains))
            for limit in access.source_limits.values()
        ],
        members_only=access.members_only,
        delete_files=access.delete_files,
    )
