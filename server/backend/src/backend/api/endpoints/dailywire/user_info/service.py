from __future__ import annotations

from sources.dailywire.api.dw_api.client import MiddlewareClient
from sources.dailywire.api.records import DwUserInfo


def get_user_info() -> DwUserInfo:
    """
    Fetch the current user's information from the DailyWire middleware API
    and normalize it into the UserInfo model.
    """
    client = MiddlewareClient(request_priority="interactive")
    return client.get_user_info()
