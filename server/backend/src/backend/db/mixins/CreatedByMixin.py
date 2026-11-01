from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from task_manager.scheduler.requester import current_requester


def _requester() -> Optional[int]:
    return current_requester.get()


class CreatedByMixin:
    """Remembers which user added a show, movie or video, for the library to show.

    Filled in from the request that adds it; empty without user accounts and
    for anything VODLoft adds on its own.
    """

    @declared_attr
    def created_by_user_id(cls) -> Mapped[Optional[int]]:
        return mapped_column(
            ForeignKey("users.id", ondelete="SET NULL"), default=_requester,
            comment="The user who added it; empty without user accounts",
        )

    @declared_attr
    def created_by_user(cls) -> Mapped[Optional["User"]]:  # noqa: F821
        return relationship("User", foreign_keys=lambda: [cls.created_by_user_id], lazy="selectin", viewonly=True)

    @property
    def added_by(self) -> Optional[str]:
        """The username of whoever added it, if they still exist."""
        return self.created_by_user.username if self.created_by_user is not None else None
