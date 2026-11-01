"""Who asked for the work being created.

The API sets the signed-in user for each request; operations created while
handling it remember that user, so people without access to Tasks only see
their own operations. Work VODLoft starts by itself has no requester.
"""
from __future__ import annotations

from contextvars import ContextVar

current_requester: ContextVar[int | None] = ContextVar("vodloft_operation_requester", default=None)
