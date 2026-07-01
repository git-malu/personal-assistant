from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from fastapi import HTTPException, Request


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


def extract_workload_access_token(request: Request) -> None:
    """提取并存入 AgentArts Gateway 注入的 Workload Access Token。

    生产环境中，AgentArts Gateway 在转发请求时通过
    ACCESS_TOKEN_HEADER 注入短期凭证。
    提取后存入 AgentArtsRuntimeContext，使 @require_access_token
    等装饰器可以直接使用，跳过本地认证 fallback。

    若 header 不存在或为空（本地开发环境），显式设为 None，
    确保 context 干净。SDK 的 _get_workload_access_token() 自动
    fallback 到本地认证。
    """
    token = request.headers.get(ACCESS_TOKEN_HEADER, "").strip()
    AgentArtsRuntimeContext.set_workload_access_token(token or None)
