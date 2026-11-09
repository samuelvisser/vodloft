from __future__ import annotations

from typing import Union

from pydantic import AwareDatetime, Field

from sources.dailywire.api.records.BaseRecord import BaseRecord
from sources.dailywire.api.types.user_info import DwMembershipLevel


class DwUserInfo(BaseRecord):

    person_id: str
    subscription_id: str
    recurly_account_code: str
    username: str
    email: str
    first_name: str
    last_name: str
    avatar: str
    access_level: Union[DwMembershipLevel, str] = Field(union_mode="left_to_right")
    """The account's membership level; text only for a level VODLoft does not know yet."""
    plan_type: str
    account_created_at: AwareDatetime
