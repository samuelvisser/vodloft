from backend.api.models.base import RequestBase, ResponseBase
from pydantic import Field


class LoginInput(RequestBase):
    """Input for login endpoint"""

    passwordHash: str
    username: str = Field(default="admin", min_length=1, max_length=80)


class AuthResponse(ResponseBase):
    """Response for authentication status"""

    authenticated: bool
