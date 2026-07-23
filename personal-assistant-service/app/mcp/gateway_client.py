"""AgentArts MCP Gateway client with per-request IAM signing."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx
from agentarts.sdk import require_sts_token
from agentarts.sdk.identity.types import StsCredentials
from huaweicloudsdkcore.auth.credentials import GlobalCredentials
from huaweicloudsdkcore.sdk_request import SdkRequest
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession

from app.identity import get_github_mcp_config

logger = logging.getLogger(__name__)

_GITHUB_MCP_SERVER_NAME = "github"
_UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
_DEFAULT_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
}
_REMOTE_DISCONNECT_MARKERS = (
    "remoteprotocolerror",
    "server disconnected without sending a response",
)


@dataclass(frozen=True, slots=True)
class MCPGatewayConfig:
    enabled: bool
    gateway_url: str
    auth_mode: str
    sts_provider_name: str
    sts_agency_session_name: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class MCPToolInfo:
    name: str
    description: str | None
    input_schema: dict[str, Any]


class MCPGatewayError(RuntimeError):
    """Typed MCP Gateway failure without credential-bearing details."""

    def __init__(
        self,
        warning_type: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.warning_type = warning_type
        self.retryable = retryable


class HuaweiCloudIAMAuth(httpx.Auth):
    """Sign each outgoing MCP HTTP request with temporary IAM credentials.

    Body-less requests (e.g. MCP session termination DELETE) must also be
    signed, so we do NOT set ``requires_request_body``.
    """

    def __init__(self, sts_credentials: StsCredentials) -> None:
        self._sts_credentials = sts_credentials

    def auth_flow(
        self,
        request: httpx.Request,
    ):
        signed_headers = sign_httpx_request(request, self._sts_credentials)
        request.headers.update(signed_headers)
        yield request


def load_mcp_gateway_config() -> MCPGatewayConfig:
    raw = get_github_mcp_config()
    return MCPGatewayConfig(
        enabled=bool(raw["enabled"]),
        gateway_url=str(raw["gateway_url"]).rstrip("/"),
        auth_mode=str(raw["auth_mode"]),
        sts_provider_name=str(raw["sts_provider_name"]),
        sts_agency_session_name=str(raw["sts_agency_session_name"]),
        timeout_seconds=float(raw["timeout_seconds"]),
    )


def _credentials_to_global_credentials(
    sts_credentials: StsCredentials,
) -> GlobalCredentials:
    return GlobalCredentials(
        sts_credentials.access_key_id,
        sts_credentials.secret_access_key,
    ).with_security_token(sts_credentials.security_token)


def _host_with_port(url: SplitResult) -> str:
    if url.port is None:
        return url.hostname or ""
    return f"{url.hostname}:{url.port}"


def _request_headers_for_signing(request: httpx.Request) -> dict[str, str]:
    headers: dict[str, str] = dict(_DEFAULT_MCP_HEADERS)
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    mcp_session_id = request.headers.get("mcp-session-id")
    if mcp_session_id:
        headers["mcp-session-id"] = mcp_session_id
    protocol_version = request.headers.get("mcp-protocol-version")
    if protocol_version:
        headers["mcp-protocol-version"] = protocol_version
    headers["X-Sdk-Content-Sha256"] = _UNSIGNED_PAYLOAD
    return headers


def sign_httpx_request(
    request: httpx.Request,
    sts_credentials: StsCredentials,
) -> dict[str, str]:
    """Return IAM signed headers for an httpx request.

    The returned mapping deliberately contains only transport headers needed by
    AgentArts Gateway; callers must not log it or expose it to LLM-visible data.
    """
    parsed = urlsplit(str(request.url))
    credentials = _credentials_to_global_credentials(sts_credentials)
    # AgentArts Gateway uses huaweicloud-agentarts.com which is a non-standard
    # endpoint → requires V11-HMAC-SHA256 derived signing (not SDK-HMAC-SHA256).
    credentials.with_derived_predicate(
        GlobalCredentials.get_default_derived_predicate()
    )
    credentials._process_derived_auth_params("apic", "cn-southwest-2")
    sdk_request = SdkRequest(
        method=request.method,
        schema=parsed.scheme,
        host=_host_with_port(parsed),
        resource_path=parsed.path or "/",
        query_params=list(request.url.params.multi_items()),
        header_params=_request_headers_for_signing(request),
        body=request.content,
    )
    signed_request = credentials.sign_request(sdk_request)
    return dict(signed_request.header_params)


def _mcp_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an MCP HTTP client without inheriting local proxy settings."""
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "trust_env": False,
    }
    if headers is not None:
        kwargs["headers"] = headers
    if timeout is not None:
        kwargs["timeout"] = timeout
    if auth is not None:
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)


async def run_with_github_mcp_sts(
    operation: Callable[[MCPGatewayClient], Awaitable[Any]],
) -> Any:
    """Run an MCP operation with decorator-injected STS credentials."""
    config = load_mcp_gateway_config()
    if not config.enabled:
        raise MCPGatewayError(
            "disabled",
            "GitHub MCP data source is disabled.",
            retryable=False,
        )
    if config.auth_mode != "iam":
        raise MCPGatewayError(
            "configuration_error",
            "GitHub MCP data source only supports IAM auth mode.",
            retryable=False,
        )

    @require_sts_token(
        provider_name=config.sts_provider_name,
        agency_session_name=config.sts_agency_session_name,
        into="sts_credentials",
    )
    async def _run(*, sts_credentials: StsCredentials) -> Any:
        async with MCPGatewayClient(
            config=config,
            sts_credentials=sts_credentials,
        ) as client:
            return await operation(client)

    return await _run()


class MCPGatewayClient:
    """Thin MCP adapter client for AgentArts MCP Gateway."""

    def __init__(
        self,
        *,
        config: MCPGatewayConfig,
        sts_credentials: StsCredentials,
    ) -> None:
        self.config = config
        self._sts_credentials = sts_credentials
        self._session_context: AbstractAsyncContextManager[ClientSession] | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> MCPGatewayClient:
        if self._session_context is not None:
            raise MCPGatewayError(
                "configuration_error",
                "GitHub MCP Gateway client session is already open.",
                retryable=False,
            )

        try:
            session_context = self._client().session(_GITHUB_MCP_SERVER_NAME)
            self._session_context = session_context
            self._session = await session_context.__aenter__()
        except httpx.HTTPStatusError as exc:
            self._session = None
            self._session_context = None
            raise _map_httpx_status_error(exc) from exc
        except httpx.HTTPError as exc:
            self._session = None
            self._session_context = None
            logger.error(
                "MCP Gateway HTTP transport error during session initialization | "
                "%s: %s",
                type(exc).__name__,
                exc,
            )
            raise MCPGatewayError(
                "gateway_unavailable",
                "GitHub MCP Gateway is unavailable.",
                retryable=True,
            ) from exc
        except Exception as exc:
            self._session = None
            self._session_context = None
            raise _map_generic_mcp_error(exc) from exc
        except BaseException:
            self._session = None
            self._session_context = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        session_context = self._session_context
        self._session = None
        self._session_context = None
        if session_context is None:
            return None

        try:
            return await session_context.__aexit__(
                exc_type,
                exc_value,
                traceback,
            )
        except BaseException as close_error:
            if exc_value is not None and _exception_only_wraps(
                close_error,
                exc_value,
            ):
                return False
            if isinstance(close_error, httpx.HTTPStatusError):
                raise _map_httpx_status_error(close_error) from close_error
            if not isinstance(close_error, httpx.HTTPError):
                if isinstance(close_error, Exception):
                    raise _map_generic_mcp_error(close_error) from close_error
                raise
            logger.error(
                "MCP Gateway HTTP transport error during session close | %s: %s",
                type(close_error).__name__,
                close_error,
            )
            raise MCPGatewayError(
                "gateway_unavailable",
                "GitHub MCP Gateway is unavailable.",
                retryable=True,
            ) from close_error

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise MCPGatewayError(
                "configuration_error",
                "GitHub MCP Gateway client session is not open.",
                retryable=False,
            )
        return self._session

    def _client(self) -> MultiServerMCPClient:
        return MultiServerMCPClient(
            {
                _GITHUB_MCP_SERVER_NAME: {
                    "transport": "streamable_http",
                    "url": self.config.gateway_url,
                    "headers": dict(_DEFAULT_MCP_HEADERS),
                    "timeout": self.config.timeout_seconds,
                    "sse_read_timeout": self.config.timeout_seconds,
                    "terminate_on_close": False,
                    "auth": HuaweiCloudIAMAuth(self._sts_credentials),
                    "httpx_client_factory": _mcp_http_client_factory,
                }
            },
            handle_tool_errors=False,
        )

    async def list_tools(self) -> list[MCPToolInfo]:
        session = self._require_session()
        try:
            result = await session.list_tools()
        except httpx.HTTPStatusError as exc:
            raise _map_httpx_status_error(exc) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "MCP Gateway HTTP transport error during list_tools | %s: %s",
                type(exc).__name__,
                exc,
            )
            raise MCPGatewayError(
                "gateway_unavailable",
                "GitHub MCP Gateway is unavailable.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise _map_generic_mcp_error(exc) from exc

        return [
            MCPToolInfo(
                name=tool.name,
                description=tool.description,
                input_schema=dict(tool.inputSchema or {}),
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        session = self._require_session()
        try:
            result = await session.call_tool(name, arguments)
        except httpx.HTTPStatusError as exc:
            raise _map_httpx_status_error(exc) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "MCP Gateway HTTP transport error during call_tool(%s) | %s: %s",
                name,
                type(exc).__name__,
                exc,
            )
            raise MCPGatewayError(
                "gateway_unavailable",
                "GitHub MCP Gateway is unavailable.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise _map_generic_mcp_error(exc) from exc

        return extract_mcp_payload(result)


def extract_mcp_payload(result: Any) -> Any:
    """Convert an MCP CallToolResult into JSON-like Python data."""
    if getattr(result, "isError", False):
        raise MCPGatewayError(
            "mcp_error",
            "GitHub MCP tool execution failed.",
            retryable=False,
        )

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    text_parts: list[str] = []
    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    if not text_parts:
        return None

    text = "\n".join(text_parts)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def _log_http_error(status: int, exc: httpx.HTTPStatusError) -> None:
    """Log HTTP error details, redacting credential-bearing fields."""
    response_text = ""
    try:
        response_text = exc.response.text[:1024]
    except Exception:
        response_text = "<unreadable>"
    logger.error(
        "MCP Gateway HTTP %d | url=%s | response=%s",
        status,
        str(exc.request.url) if exc.request else "?",
        response_text,
    )


def _map_httpx_status_error(exc: httpx.HTTPStatusError) -> MCPGatewayError:
    status = exc.response.status_code
    _log_http_error(status, exc)
    if status == 401:
        return MCPGatewayError(
            "authentication_error",
            "GitHub MCP Gateway IAM authentication failed.",
            retryable=False,
        )
    if status == 403:
        return MCPGatewayError(
            "permission_denied",
            "GitHub MCP Gateway rejected the caller permissions.",
            retryable=False,
        )
    if status == 429:
        return MCPGatewayError(
            "rate_limited",
            "GitHub MCP Gateway or target rate limit was reached.",
            retryable=True,
        )
    if status >= 500:
        return MCPGatewayError(
            "gateway_unavailable",
            "GitHub MCP Gateway is unavailable.",
            retryable=True,
        )
    return MCPGatewayError(
        "mcp_error",
        "GitHub MCP Gateway request failed.",
        retryable=False,
    )


def _exception_text(exc: BaseException, seen: set[int] | None = None) -> str:
    seen = set() if seen is None else seen
    if id(exc) in seen:
        return ""
    seen.add(id(exc))

    parts = [f"{type(exc).__name__}: {exc}".lower()]
    for nested in getattr(exc, "exceptions", []) or []:
        if isinstance(nested, BaseException):
            parts.append(_exception_text(nested, seen))
    if exc.__cause__ is not None:
        parts.append(_exception_text(exc.__cause__, seen))
    if exc.__context__ is not None:
        parts.append(_exception_text(exc.__context__, seen))
    return "\n".join(part for part in parts if part)


def _exception_only_wraps(
    candidate: BaseException,
    original: BaseException,
) -> bool:
    if candidate is original:
        return True
    if not isinstance(candidate, BaseExceptionGroup):
        return False
    return bool(candidate.exceptions) and all(
        _exception_only_wraps(nested, original) for nested in candidate.exceptions
    )


def _map_generic_mcp_error(exc: Exception) -> MCPGatewayError:
    text = _exception_text(exc)
    logger.error(
        "MCP Gateway error | type=%s | detail=%s",
        type(exc).__name__,
        text[:512],
    )
    if "401" in text or "unauthorized" in text:
        return MCPGatewayError(
            "authentication_error",
            "GitHub MCP Gateway IAM authentication failed.",
            retryable=False,
        )
    if "403" in text or "forbidden" in text:
        return MCPGatewayError(
            "permission_denied",
            "GitHub MCP Gateway rejected the caller permissions.",
            retryable=False,
        )
    if "429" in text or "rate limit" in text:
        return MCPGatewayError(
            "rate_limited",
            "GitHub MCP Gateway or target rate limit was reached.",
            retryable=True,
        )
    if any(marker in text for marker in _REMOTE_DISCONNECT_MARKERS):
        return MCPGatewayError(
            "gateway_unavailable",
            "GitHub MCP Gateway disconnected without sending a response.",
            retryable=True,
        )
    if "timed out" in text or "timeout" in text:
        return MCPGatewayError(
            "gateway_unavailable",
            "GitHub MCP Gateway timed out.",
            retryable=True,
        )
    return MCPGatewayError(
        "mcp_error",
        "GitHub MCP Gateway request failed.",
        retryable=False,
    )
