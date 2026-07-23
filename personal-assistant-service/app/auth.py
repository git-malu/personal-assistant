import base64
import binascii
import json
import logging

from agentarts.sdk import IdentityClient
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from agentarts.sdk.utils.constant import get_region
from fastapi import HTTPException, Request
from huaweicloudsdkcore.exceptions.exceptions import SdkException

from app.settings import get_settings

logger = logging.getLogger(__name__)


def _decode_jwt_claims_for_log(token: str) -> dict[str, object]:
    """Decode non-sensitive JWT claims for local auth troubleshooting logs."""
    try:
        encoded_payload = token.split(".")[1]
        padded_payload = encoded_payload + "=" * (-len(encoded_payload) % 4)
        payload = base64.urlsafe_b64decode(padded_payload.encode())
        claims = json.loads(payload)
    except (IndexError, ValueError, json.JSONDecodeError):
        return {"decode_error": "invalid_jwt_payload"}

    return {
        key: claims.get(key)
        for key in ("aud", "azp", "appid", "client_id", "tid", "iss", "ver")
        if claims.get(key)
    }


def _exception_details(exc: BaseException) -> dict[str, object]:
    details = {
        key: getattr(exc, key, None)
        for key in ("status_code", "request_id", "error_code", "error_msg")
        if getattr(exc, key, None)
    }
    return details or {"error_type": type(exc).__name__, "error": str(exc)}


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


def extract_authenticated_user_id(request: Request) -> str:
    """Read `sub` from the JWT already validated by AgentArts Gateway."""
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="A Gateway-validated Bearer token is required",
        )

    try:
        segments = token.strip().split(".")
        if len(segments) != 3:
            raise ValueError
        encoded_payload = segments[1].encode("ascii")
        padded_payload = encoded_payload + b"=" * (-len(encoded_payload) % 4)
        payload = base64.b64decode(
            padded_payload,
            altchars=b"-_",
            validate=True,
        )
        claims = json.loads(payload)
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError
    except (
        UnicodeEncodeError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise HTTPException(
            status_code=401,
            detail="Invalid Gateway-validated Bearer token",
        ) from error

    user_id = subject.strip()
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


def ensure_jwt_workload_access_token(
    request: Request,
    *,
    wat_required: bool,
) -> str | None:
    """Ensure Runtime Context has a JWT-bound AgentArts workload token.

    Production requests receive a Gateway-injected workload token that is
    already bound to the inbound JWT identity. Local Calendar OAuth2 requests
    must create the same JWT-mode token from the inbound Authorization token
    before AgentArts SDK decorators can fall back to user_id mode.

    Args:
        wat_required: When true, missing or invalid WAT setup fails the request.
            Normal chat keeps this false; Calendar OAuth callback sets it true.
    """
    gateway_token = request.headers.get(ACCESS_TOKEN_HEADER, "").strip()
    if gateway_token:
        AgentArtsRuntimeContext.set_workload_access_token(gateway_token)
        logger.info("JWT-mode WAT ready source=gateway_wat identity_mode=jwt")
        return gateway_token

    try:
        user_token = extract_authorization_user_token(request)
    except HTTPException as e:
        AgentArtsRuntimeContext.set_workload_access_token(None)
        logger.info(
            "JWT-mode WAT unavailable source=missing_authorization_user_token "
            "identity_mode=jwt wat_required=%s",
            wat_required,
        )
        if wat_required:
            raise HTTPException(
                status_code=401,
                detail="Local Calendar OAuth2 requires an Authorization user token",
            ) from e
        return None

    settings = get_settings()
    region = get_region()
    try:
        client = IdentityClient(region=region)
        workload_token = client.create_workload_access_token(
            settings.agent_identity_local_jwt_workload_name,
            user_token=user_token,
        )
    except (SdkException, ValueError) as exc:
        AgentArtsRuntimeContext.set_workload_access_token(None)
        log = logger.error if wat_required else logger.warning
        log(
            "JWT-mode WAT exchange failed source=local_jwt_wat identity_mode=jwt "
            "wat_required=%s workload_name=%s jwt_claims=%s sdk_error=%s "
            "setup_hint=%s",
            wat_required,
            settings.agent_identity_local_jwt_workload_name,
            _decode_jwt_claims_for_log(user_token),
            _exception_details(exc),
            "Run: cd personal-assistant-infra && uv run python "
            "scripts/ensure_local_jwt_workload_identity.py "
            f"--region {region} --apply",
            exc_info=wat_required,
        )
        if wat_required:
            raise
        return None
    AgentArtsRuntimeContext.set_workload_access_token(workload_token)
    logger.info(
        "JWT-mode WAT ready source=local_jwt_wat identity_mode=jwt workload_name=%s",
        settings.agent_identity_local_jwt_workload_name,
    )
    return workload_token


def prepare_jwt_workload_access_token(request: Request) -> str | None:
    """Best-effort JWT-mode WAT preparation for normal chat requests."""
    return ensure_jwt_workload_access_token(request, wat_required=False)


def require_jwt_workload_access_token(request: Request) -> str:
    """Require JWT-mode WAT for OAuth flows that must not fall back to user_id."""
    workload_token = ensure_jwt_workload_access_token(request, wat_required=True)
    if workload_token is None:  # Defensive; required mode raises instead.
        raise HTTPException(
            status_code=401,
            detail="Local Calendar OAuth2 requires a workload access token",
        )
    return workload_token
