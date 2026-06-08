"""Pydantic schemas for authentication endpoints."""

from pydantic import BaseModel


class UserInfoResponse(BaseModel):
    """GET /api/auth/me response."""

    user_id: str  # internal user_id (e.g. "entra-<sub>")
    display_name: str  # Microsoft display name
    email: str  # Microsoft email
    channel: str  # "entra_id"
    is_authenticated: bool  # always True (unauthenticated returns 401 instead)


class AuthErrorResponse(BaseModel):
    """OAuth error response."""

    error: str
    error_description: str | None = None
