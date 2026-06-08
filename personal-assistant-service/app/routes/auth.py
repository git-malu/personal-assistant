"""Authentication route stubs — API contract only.

Implementation will be provided in feature tasks 4.3-4.6.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.schemas.auth import AuthErrorResponse, UserInfoResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/login")
async def auth_login(request: Request):
    """Initiate Microsoft Entra ID OAuth login flow.

    Redirects the user to the Microsoft Entra ID authorization page.
    If the user already has a valid session cookie, redirects to /chat instead.
    """
    # Stub: redirect to placeholder
    raise HTTPException(
        status_code=501,
        detail="Not implemented: OAuth login flow will redirect to Microsoft Entra ID.",
    )


@router.get(
    "/callback",
    response_model=None,
    responses={
        302: {"description": "Redirect to /chat after successful authentication"},
        400: {"model": AuthErrorResponse},
    },
)
async def auth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter for CSRF protection"),
):
    """OAuth callback endpoint.

    Exchanges the authorization code for tokens, stores user info,
    sets a session cookie, and redirects to /chat.
    """
    # Stub: return error if no code (will be replaced with real OAuth logic)
    if not code:
        return JSONResponse(
            status_code=400,
            content={"error": "missing_code", "error_description": "Authorization code is required."},
        )

    raise HTTPException(
        status_code=501,
        detail="Not implemented: OAuth callback will exchange code for tokens.",
    )


@router.get(
    "/me",
    response_model=UserInfoResponse,
    responses={
        200: {"model": UserInfoResponse},
        401: {"description": "Not authenticated"},
    },
)
async def auth_me(request: Request):
    """Return the currently authenticated user's information.

    Reads identity from session cookie or X-AgentArts-User-Id header.
    Returns 401 if not authenticated.
    """
    # Stub: return 401 to indicate no authenticated user yet
    raise HTTPException(
        status_code=501,
        detail="Not implemented: will return UserInfoResponse when auth is wired.",
    )


@router.post("/logout")
async def auth_logout(request: Request):
    """Log out the current user by clearing the session cookie."""
    # Stub: return simple confirmation
    raise HTTPException(
        status_code=501,
        detail="Not implemented: logout will clear session cookie.",
    )
