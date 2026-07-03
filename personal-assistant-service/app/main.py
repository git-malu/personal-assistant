import hmac
import html as html_lib
import json
import logging
import time
from contextlib import asynccontextmanager
from json import JSONDecodeError
from pathlib import Path
from typing import Literal

logger = logging.getLogger("app")

from agentarts.sdk import IdentityClient  # noqa: E402
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext  # noqa: E402
from agentarts.sdk.utils.constant import get_region  # noqa: E402
from chainlit.utils import mount_chainlit  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from huaweicloudsdkagentidentity.v1.model import UserIdentifier  # noqa: E402
from pydantic import (  # noqa: E402
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
)

from app.agent_handler import AgentHandler, get_agent_handler  # noqa: E402
from app.auth import (  # noqa: E402
    ensure_jwt_mode_workload_access_token,
    extract_authorization_user_token,
    extract_gateway_session_id,
    extract_gateway_user_id,
)
from app.logging_config import RequestLoggingMiddleware  # noqa: E402
from app.oauth2_callback_store import OAuth2CallbackStore  # noqa: E402
from app.oauth2_state import (  # noqa: E402
    OAuth2StateError,
    create_oauth2_state,
    verify_oauth2_state,
)
from app.settings import get_settings  # noqa: E402

OAUTH2_CALLBACK_BFF_SECRET_HEADER = "x-pa-oauth2-callback-secret"


class InvocationRequest(BaseModel):
    """Agent invocation request."""

    message: str = Field(description="User message sent to the Agent.")
    stream: StrictBool = Field(
        default=False,
        description="Return a Server-Sent Events stream instead of JSON.",
    )


class InvocationResponse(BaseModel):
    """Successful non-streaming invocation response."""

    response: str


class ErrorResponse(BaseModel):
    """HTTP error response."""

    detail: str


class OAuth2CallbackQuery(BaseModel):
    """OAuth2 Resource Token Auth callback query."""

    session_uri: str | None = Field(
        default=None,
        description="AgentArts Resource Token Auth session URI.",
    )
    state: str | None = Field(default=None, description="OAuth2 state.")
    custom_state: str | None = Field(
        default=None,
        description="AgentArts custom state fallback.",
    )
    error: str | None = Field(default=None, description="OAuth2 callback error code.")
    error_description: str | None = Field(
        default=None,
        description="OAuth2 callback error description.",
    )


class OAuth2CallbackResponse(BaseModel):
    """Calendar OAuth2 callback status returned to the BFF result page."""

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["m365-calendar-auth"] = Field(
        description="Calendar OAuth2 callback envelope type.",
    )
    request_id: str = Field(
        alias="requestId",
        description="OAuth2 state used as the UI request id.",
    )
    provider: str = Field(description="AgentArts resource credential provider name.")
    status: Literal["complete", "failed", "pending"] = Field(
        description="Backend-owned OAuth2 completion status.",
    )
    message: str = Field(description="Human-readable callback status message.")
    state: str | None = Field(default=None, description="OAuth2 state.")


OAUTH2_CALLBACK_RESPONSES = {
    200: {
        "description": (
            "Callback status as HTML for direct browser opens or JSON for the "
            "local development fallback."
        ),
        "content": {
            "text/html": {"schema": {"type": "string"}},
            "application/json": {"schema": OAuth2CallbackResponse.model_json_schema()},
        },
    }
}


def _parse_invocation_request(body: object) -> InvocationRequest:
    """Validate an invocation body while preserving the public 400 contract."""
    try:
        invocation = InvocationRequest.model_validate(body)
    except ValidationError as e:
        errors = e.errors()
        if any(
            error["loc"] == ("message",) and error["type"] == "missing"
            for error in errors
        ):
            detail = "message is required"
        elif any(error["loc"] == ("message",) for error in errors):
            detail = "message must be a string"
        elif any(error["loc"] == ("stream",) for error in errors):
            detail = "stream must be a boolean"
        else:
            detail = "invalid request body"
        raise HTTPException(status_code=400, detail=detail) from e

    if not invocation.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    return invocation


def _accepts_media_type(accept: str | None, media_type: str) -> bool:
    """Return whether an Accept header permits the selected response type."""
    if not accept:
        return True

    expected_type, expected_subtype = media_type.lower().split("/", maxsplit=1)
    for entry in accept.split(","):
        parts = [part.strip() for part in entry.split(";")]
        accepted_type = parts[0].lower()
        if "/" not in accepted_type:
            continue

        quality = 1.0
        for parameter in parts[1:]:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality <= 0:
            continue

        accepted_main, accepted_subtype = accepted_type.split("/", maxsplit=1)
        if accepted_main in {"*", expected_type} and accepted_subtype in {
            "*",
            expected_subtype,
        }:
            return True
    return False


def _redacted_prefix(value: str | None, *, length: int = 32) -> str | None:
    """Return a short non-secret prefix for correlation logs."""
    if not value:
        return None
    return value[:length]


def _verify_oauth2_callback_bff_secret(request: Request) -> None:
    """Verify the optional server-to-server callback secret from the BFF."""
    settings = get_settings()
    expected = settings.oauth2_callback_bff_secret
    if not expected:
        return

    supplied = request.headers.get(OAUTH2_CALLBACK_BFF_SECRET_HEADER)
    if not supplied or not hmac.compare_digest(supplied, expected):
        logger.warning("OAuth2 callback rejected due to invalid BFF secret")
        raise HTTPException(status_code=403, detail="invalid OAuth2 callback secret")


def _oauth2_callback_page(
    *,
    status: str,
    provider: str,
    message: str,
    state: str | None,
) -> HTMLResponse:
    """Return a tiny callback page that only reports backend completion status."""
    # The callback page deliberately broadcasts only UI status. OAuth completion
    # already happened in the backend route, so extra browser tabs cannot race to
    # finish the same AgentArts session with a different foreground identity.
    payload = {
        "type": "m365-calendar-auth",
        "requestId": state or "",
        "provider": provider,
        "status": status,
        "message": message,
        "state": state,
    }
    if status == "complete":
        title = "授权完成"
        icon = "✓"
        color = "#15803d"
    elif status == "failed":
        title = "授权失败"
        icon = "!"
        color = "#b91c1c"
    else:
        title = "授权处理中"
        icon = "..."
        color = "#2563eb"
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    escaped_title = html_lib.escape(title)
    escaped_message = html_lib.escape(message)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{
      align-items: center;
      background: #f8fafc;
      color: #0f172a;
      display: flex;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      justify-content: center;
      margin: 0;
      min-height: 100vh;
      padding: 24px;
    }}
    main {{
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      box-shadow: 0 1px 3px rgb(15 23 42 / 0.08);
      max-width: 420px;
      padding: 28px;
      text-align: center;
      width: 100%;
    }}
    .icon {{
      align-items: center;
      background: #f1f5f9;
      border-radius: 999px;
      color: {color};
      display: inline-flex;
      font-size: 28px;
      height: 56px;
      justify-content: center;
      margin-bottom: 16px;
      width: 56px;
    }}
    h1 {{ font-size: 20px; margin: 0 0 12px; }}
    p {{ color: #475569; line-height: 1.6; margin: 0; }}
    button {{
      background: #0f172a;
      border: 0;
      border-radius: 8px;
      color: white;
      cursor: pointer;
      font-size: 14px;
      margin-top: 24px;
      padding: 10px 16px;
    }}
  </style>
</head>
<body>
  <main>
    <div class="icon">{icon}</div>
    <h1>{escaped_title}</h1>
    <p>{escaped_message}</p>
    <button type="button" onclick="window.close()">关闭窗口</button>
  </main>
  <script>
    const response = {payload_json};
    try {{
      const channel = new BroadcastChannel("m365-calendar-auth");
      channel.postMessage(response);
      setTimeout(() => channel.close(), 1000);
    }} catch (error) {{}}
    try {{
      window.opener?.postMessage(response, window.location.origin);
    }} catch (error) {{}}
    if (response.status === "complete") {{
      setTimeout(() => window.close(), 1200);
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def _oauth2_callback_response(
    request: Request,
    *,
    status: str,
    provider: str,
    message: str,
    state: str | None,
) -> HTMLResponse | JSONResponse:
    """Return callback status as JSON for local fallback, HTML for direct opens."""
    payload = {
        "type": "m365-calendar-auth",
        "requestId": state or "",
        "provider": provider,
        "status": status,
        "message": message,
        "state": state,
    }
    if "application/json" in request.headers.get("accept", "").lower():
        return JSONResponse(content=payload, headers={"Cache-Control": "no-store"})
    return _oauth2_callback_page(
        status=status,
        provider=provider,
        message=message,
        state=state,
    )


def _is_identity_permission_error(error: Exception) -> bool:
    """Return whether AgentArts Identity rejected the runtime agency permissions."""
    status_code = getattr(error, "status_code", None)
    text = str(error)
    return (
        status_code == 403
        and "completeResourceTokenAuth" in text
        and (
            "AgentIdentityTokenVault.1007" in text
            or "not authorized to perform" in text
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI application."""
    # Validate LLM provider metadata. The Agent Bundle is built lazily after
    # the first request places the Gateway workload token in Runtime Context.
    from app.llm_config import validate_model_config

    settings = get_settings()
    try:
        validate_model_config()
    except ValueError as e:
        raise RuntimeError(f"LLM 配置错误: {e}") from e

    # Initialize the shared handler and persistent Checkpointer before serving.
    handler = get_agent_handler()
    await handler.startup()
    app.state.agent_handler = handler
    oauth2_callback_store = OAuth2CallbackStore(settings=settings)
    await oauth2_callback_store.startup()
    app.state.oauth2_callback_store = oauth2_callback_store

    try:
        yield
    finally:
        await oauth2_callback_store.shutdown()
        await handler.shutdown()


app = FastAPI(
    title="Personal Assistant",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/ping")
async def ping():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post(
    "/invocations",
    response_model=InvocationResponse,
    responses={
        200: {
            "description": (
                "JSON response when stream is false, or a Server-Sent Events "
                "stream when stream is true."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "description": "Server-Sent Events stream.",
                    },
                    "example": (
                        'data: {"token":"你","done":false}\n\n'
                        'data: {"token":"","done":true}\n\n'
                    ),
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid JSON or invocation request.",
        },
        406: {
            "model": ErrorResponse,
            "description": "The Accept header excludes the selected response type.",
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": InvocationRequest.model_json_schema(),
                }
            },
        }
    },
)
async def invocations(request: Request):
    """Agent invocation endpoint, supporting sync JSON and SSE streaming."""
    try:
        body = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="invalid JSON body") from e

    invocation = _parse_invocation_request(body)
    message = invocation.message
    stream = invocation.stream
    user_id = extract_gateway_user_id(request)
    session_id = extract_gateway_session_id(request)
    ensure_jwt_mode_workload_access_token(request, required=False)
    settings = get_settings()
    oauth2_state = create_oauth2_state(
        settings=settings,
        user_id=user_id,
        session_id=session_id,
        provider=settings.m365_calendar_provider_name,
    )
    AgentArtsRuntimeContext.set_oauth2_custom_state(oauth2_state)
    logger.info(
        "OAuth2 authorization context prepared provider=%s user_id=%s "
        "gateway_session_id=%s runtime_context_user_id=%s state_prefix=%s",
        settings.m365_calendar_provider_name,
        user_id,
        session_id,
        AgentArtsRuntimeContext.get_user_id(),
        _redacted_prefix(oauth2_state),
    )

    mode = "stream" if stream else "sync"
    response_media_type = "text/event-stream" if stream else "application/json"
    if not _accepts_media_type(request.headers.get("accept"), response_media_type):
        raise HTTPException(
            status_code=406,
            detail=f"Accept header must allow {response_media_type}",
        )

    handler: AgentHandler = request.app.state.agent_handler
    started_at = time.perf_counter()
    logger.info("Invocation started mode=%s", mode)

    if stream:

        async def event_generator():
            status = "cancelled"
            try:
                async for sse_data in handler.handle_stream(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                ):
                    yield sse_data
                status = "success"
            except Exception as e:
                status = "error"
                logger.error(
                    "Invocation failed mode=stream duration_ms=%.2f: %s",
                    (time.perf_counter() - started_at) * 1000,
                    e,
                    exc_info=True,
                )
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
            finally:
                logger.info(
                    "Invocation completed mode=stream status=%s duration_ms=%.2f",
                    status,
                    (time.perf_counter() - started_at) * 1000,
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        result = await handler.handle(
            message=message,
            user_id=user_id,
            session_id=session_id,
        )
    except Exception as e:
        logger.error(
            "Invocation failed mode=sync duration_ms=%.2f: %s",
            (time.perf_counter() - started_at) * 1000,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

    logger.info(
        "Invocation completed mode=sync status=success duration_ms=%.2f",
        (time.perf_counter() - started_at) * 1000,
    )
    return JSONResponse(content=InvocationResponse(response=result).model_dump())


@app.get(
    "/auth/oauth2/callback/m365-calendar",
    response_class=HTMLResponse,
    responses=OAUTH2_CALLBACK_RESPONSES,
)
async def calendar_oauth2_callback(request: Request):
    """Complete Calendar OAuth2 from the backend-owned callback endpoint."""
    _verify_oauth2_callback_bff_secret(request)
    settings = get_settings()
    provider = settings.m365_calendar_provider_name
    try:
        callback = OAuth2CallbackQuery.model_validate(dict(request.query_params))
    except ValidationError:
        return _oauth2_callback_response(
            request,
            status="failed",
            provider=provider,
            message="授权回调参数无效，请重新发起日历授权。",
            state=None,
        )

    state = callback.state or callback.custom_state
    if callback.error:
        logger.warning(
            "Calendar OAuth2 callback returned error provider=%s error=%s",
            provider,
            callback.error,
        )
        return _oauth2_callback_response(
            request,
            status="failed",
            provider=provider,
            message=callback.error_description or "日历授权失败，请重新发起授权。",
            state=state,
        )

    if not callback.session_uri or not state:
        logger.warning(
            "Calendar OAuth2 callback missing required params "
            "provider=%s has_session_uri=%s has_state=%s",
            provider,
            bool(callback.session_uri),
            bool(state),
        )
        return _oauth2_callback_response(
            request,
            status="failed",
            provider=provider,
            message="授权回调缺少必要参数，请重新发起日历授权。",
            state=state,
        )

    try:
        state_claims = verify_oauth2_state(
            state,
            settings=settings,
            expected_provider=provider,
        )
    except OAuth2StateError as e:
        logger.warning(
            "Calendar OAuth2 callback state rejected provider=%s state_prefix=%s: %s",
            provider,
            _redacted_prefix(state),
            e,
        )
        return _oauth2_callback_response(
            request,
            status="failed",
            provider=provider,
            message="授权状态无效或已过期，请重新发起日历授权。",
            state=state,
        )

    store = getattr(request.app.state, "oauth2_callback_store", None)
    if store is None:
        store = OAuth2CallbackStore(settings=settings)

    begin_status = await store.begin_completion(state_claims)
    if begin_status == "completed":
        logger.info(
            "Calendar OAuth2 callback replay ignored provider=%s user_id=%s "
            "state_prefix=%s",
            provider,
            state_claims.user_id,
            _redacted_prefix(state),
        )
        return _oauth2_callback_response(
            request,
            status="complete",
            provider=provider,
            message="日历授权已完成，可以关闭此窗口并重试刚才的问题。",
            state=state,
        )

    if begin_status == "active":
        logger.info(
            "Calendar OAuth2 callback duplicate already active provider=%s "
            "user_id=%s state_prefix=%s",
            provider,
            state_claims.user_id,
            _redacted_prefix(state),
        )
        return _oauth2_callback_response(
            request,
            status="pending",
            provider=provider,
            message="日历授权正在完成，请回到聊天窗口稍后重试刚才的问题。",
            state=state,
        )

    try:
        user_token = extract_authorization_user_token(request)
        logger.info(
            "Calling Identity complete_resource_token_auth from callback. "
            "provider=%s user_id=%s identity_strategy=user_token "
            "session_uri_prefix=%s state_session_id=%s",
            provider,
            state_claims.user_id,
            _redacted_prefix(callback.session_uri),
            state_claims.session_id,
        )
        client = IdentityClient(region=get_region())
        # The BFF only protects transport to the callback endpoint. Signed state
        # still binds the callback to the request that created the auth session,
        # while AgentArts Identity verifies the session against the original
        # inbound user token.
        client.complete_resource_token_auth(
            session_uri=callback.session_uri,
            user_identifier=UserIdentifier(user_token=user_token),
        )
    except HTTPException as e:
        logger.warning(
            "Calendar OAuth2 backend callback missing user token provider=%s "
            "user_id=%s status_code=%s detail=%s",
            provider,
            state_claims.user_id,
            e.status_code,
            e.detail,
        )
        await store.clear_active(state_claims)
        return _oauth2_callback_response(
            request,
            status="failed",
            provider=provider,
            message="请保持原聊天窗口处于登录状态后，再重新完成日历授权。",
            state=state,
        )
    except Exception as e:
        logger.error(
            "Calendar OAuth2 backend callback complete failed provider=%s "
            "user_id=%s error_type=%s error=%s",
            provider,
            state_claims.user_id,
            type(e).__name__,
            e,
            exc_info=True,
        )
        if _is_identity_permission_error(e):
            message = (
                "日历授权服务权限尚未配置完成，"
                "请联系管理员检查 AgentArts Identity 权限。"
            )
        else:
            message = "日历授权完成失败，请重新发起授权。"
        await store.clear_active(state_claims)
        return _oauth2_callback_response(
            request,
            status="failed",
            provider=provider,
            message=message,
            state=state,
        )

    await store.mark_completed(state_claims)
    logger.info(
        "Calendar OAuth2 backend callback complete succeeded provider=%s user_id=%s",
        provider,
        state_claims.user_id,
    )
    return _oauth2_callback_response(
        request,
        status="complete",
        provider=provider,
        message="日历授权已完成，可以关闭此窗口并重试刚才的问题。",
        state=state,
    )


# === Chainlit Playground（Agent 调试 UI）===


@app.get("/invocations/playground", include_in_schema=False)
async def playground_redirect():
    """Redirect /playground to /playground/ (Chainlit mount requires trailing slash)."""
    return RedirectResponse(url="/invocations/playground/")


mount_chainlit(
    app=app,
    target=str(Path(__file__).parent / "playground.py"),
    path="/invocations/playground",
)
