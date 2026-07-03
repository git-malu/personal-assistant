import logging
from contextvars import ContextVar

from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from fastapi import HTTPException, Request

from app.agentarts_wat import create_jwt_mode_workload_access_token

logger = logging.getLogger(__name__)

_WORKLOAD_ACCESS_TOKEN_SOURCE: ContextVar[str | None] = ContextVar(
    "workload_access_token_source",
    default=None,
)

LOCAL_CALENDAR_AUTH_REQUIRED_DETAIL = (
    "Local Calendar OAuth2 requires an Authorization user token"
)


def _set_workload_access_token(token: str | None, source: str) -> None:
    AgentArtsRuntimeContext.set_workload_access_token(token)
    _WORKLOAD_ACCESS_TOKEN_SOURCE.set(source)


def get_workload_access_token_source() -> str | None:
    """Return where the current request's WAT came from, for logs/tests."""
    return _WORKLOAD_ACCESS_TOKEN_SOURCE.get()


def extract_authorization_user_token(request: Request) -> str:
    """Extract the JWT from the Authorization header for AgentArts Identity."""
    authorization = request.headers.get("authorization", "").strip()
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
        )
    if authorization.lower() == "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header",
        )

    scheme, separator, token = authorization.partition(" ")
    if not separator:
        return authorization
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header",
        )
    return token.strip()


def extract_gateway_user_id(request: Request) -> str:
    """Extract verified user_id from AgentArts Gateway injected header.

    Production (CUSTOM_JWT): Gateway validates JWT then injects
    this header. It is guaranteed to be present and trustworthy.
    Development (key_auth or no Gateway): Manually inject this
    header to simulate identity.

    Raises:
        HTTPException(401): Fail-closed when header is missing.
    """
    user_id = request.headers.get(USER_ID_HEADER, "").strip()
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail=f"Missing {USER_ID_HEADER} header",
        )
    AgentArtsRuntimeContext.set_user_id(user_id)
    return user_id


def extract_gateway_session_id(request: Request) -> str:
    """Extract session_id from AgentArts Gateway injected header.

    Raises:
        HTTPException(400): Fail-closed when header is missing.
    """
    session_id = request.headers.get(SESSION_HEADER, "").strip()
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail=f"{SESSION_HEADER} header is required",
        )
    AgentArtsRuntimeContext.set_session_id(session_id)
    return session_id


def ensure_jwt_mode_workload_access_token(
    request: Request,
    *,
    required: bool,
) -> str | None:
    """Ensure RuntimeContext has a JWT-mode WAT when the request can provide one.

    Gateway-provided WAT wins in production. Local development can provide an
    inbound Authorization user token; the service exchanges it server-side for
    a JWT-mode WAT so AgentArts SDK does not fall back to user_id mode.
    """
    gateway_token = request.headers.get(ACCESS_TOKEN_HEADER, "").strip()
    if gateway_token:
        _set_workload_access_token(gateway_token, "gateway_wat")
        logger.info("AgentArts workload access token source=gateway_wat")
        return gateway_token

    try:
        user_token = extract_authorization_user_token(request)
    except HTTPException as e:
        _set_workload_access_token(None, "missing_authorization_user_token")
        if required:
            raise HTTPException(
                status_code=401,
                detail=LOCAL_CALENDAR_AUTH_REQUIRED_DETAIL,
            ) from e
        logger.info(
            "AgentArts workload access token source=missing_authorization_user_token"
        )
        return None

    try:
        workload_token = create_jwt_mode_workload_access_token(user_token)
    except Exception as e:
        _set_workload_access_token(None, "local_jwt_wat_failed")
        logger.warning(
            "AgentArts workload access token source=local_jwt_wat_failed "
            "required=%s error_type=%s",
            required,
            type(e).__name__,
            exc_info=True,
        )
        if required:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Local Calendar OAuth2 could not prepare AgentArts workload token"
                ),
            ) from e
        return None

    _set_workload_access_token(workload_token, "local_jwt_wat")
    logger.info("AgentArts workload access token source=local_jwt_wat")
    return workload_token
