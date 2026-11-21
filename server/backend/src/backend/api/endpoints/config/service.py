from __future__ import annotations

from config import get_settings

from backend.db import get_session
from backend.services.users import accounts_enabled

from backend.api.models.collection_contract import CollectionContractsAPIRead
from backend.api.models.config_public import *
from backend.types.collection_contracts import CONTRACTS, DEFAULT_WORDS


def get_public_config() -> ConfigPublicRead:
    s = get_settings()

    ## We assign values very explicitly to prevent ever exposing app secrets to the public API
    config = ConfigPublicRead(
        app_version=s.app_version,
        login_session=PublicSessionConfig(
            ttl_seconds=s.login_session.ttl_seconds
        ),
        admin_auth=PublicAdminAuth(
            enabled=s.admin_auth.enabled
        ),
        user_accounts=PublicUserAccounts(enabled=_accounts_enabled()),
        collection_contracts=get_collection_contracts(),
    )

    return config

def _accounts_enabled() -> bool:
    with get_session() as session:
        return accounts_enabled(session)


def get_collection_contracts() -> CollectionContractsAPIRead:
    """What each collection type calls its seasons and episodes. It is the same for everyone and holds nothing of the
    Library, so the UI gets it with the public config, before anyone signs in."""
    return CollectionContractsAPIRead.model_validate({"words": DEFAULT_WORDS, "types": list(CONTRACTS.values())})
