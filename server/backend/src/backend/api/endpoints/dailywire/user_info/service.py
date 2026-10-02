from __future__ import annotations

from backend.source_manager.dailywire_legacy import MiddlewareClient
from dailywire_api.records import DwUserInfo


def get_user_info() -> DwUserInfo:
    """
    Fetch the current user's information from the DailyWire middleware API
    and normalize it into the UserInfo model.
    """
    client = MiddlewareClient(pace_requests=False)
    return client.get_user_info()
