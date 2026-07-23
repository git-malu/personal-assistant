"""Tests for AgentArts MCP Gateway IAM signing."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import httpx
import pytest

import app.mcp.gateway_client as gateway_client
from app.mcp.gateway_client import (
    MCPGatewayClient,
    MCPGatewayConfig,
    MCPGatewayError,
    _map_generic_mcp_error,
    extract_mcp_payload,
    sign_httpx_request,
)


def _enabled_config() -> MCPGatewayConfig:
    return MCPGatewayConfig(
        enabled=True,
        gateway_url="https://gateway.example.com/mcp",
        auth_mode="iam",
        sts_provider_name="github-mcp-gateway",
        sts_agency_session_name="personal-assistant-github-mcp",
        timeout_seconds=30.0,
    )


def _sts_credentials() -> SimpleNamespace:
    return SimpleNamespace(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        security_token="test-security-token",
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://gateway.example.com/mcp")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"MCP Gateway returned {status_code}",
        request=request,
        response=response,
    )


def _install_gateway_session_harness(
    monkeypatch,
    *,
    adapter_error: Exception | None = None,
    enter_error: BaseException | None = None,
    call_error: Exception | None = None,
    task_group_session: bool = False,
) -> SimpleNamespace:
    state = SimpleNamespace(
        adapter_constructions=0,
        session_enters=0,
        session_exits=0,
        requests=[],
    )

    class FakeSession:
        async def list_tools(self):
            state.requests.append(("list_tools", None))
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="target-github-mcp-get_me",
                        description="Resolve the current user",
                        inputSchema={},
                    )
                ]
            )

        async def call_tool(self, name, arguments):
            state.requests.append((name, arguments))
            if call_error is not None:
                raise call_error
            return SimpleNamespace(
                isError=False,
                structuredContent={"name": name, "arguments": arguments},
                content=[],
            )

    class FakeAdapter:
        @asynccontextmanager
        async def session(self, server_name):
            assert server_name == "github"
            state.session_enters += 1
            if enter_error is not None:
                raise enter_error
            try:
                if task_group_session:
                    async with anyio.create_task_group():
                        yield FakeSession()
                else:
                    yield FakeSession()
            finally:
                state.session_exits += 1

    def build_adapter(*args, **kwargs):
        state.adapter_constructions += 1
        if adapter_error is not None:
            raise adapter_error
        return FakeAdapter()

    def inject_sts_credentials(**decorator_kwargs):
        def decorator(operation):
            async def wrapped():
                return await operation(sts_credentials=_sts_credentials())

            return wrapped

        return decorator

    monkeypatch.setattr(gateway_client, "load_mcp_gateway_config", _enabled_config)
    monkeypatch.setattr(gateway_client, "require_sts_token", inject_sts_credentials)
    monkeypatch.setattr(gateway_client, "MultiServerMCPClient", build_adapter)
    return state


def test_sign_httpx_request_uses_sts_credentials_without_secret_leak():
    request = httpx.Request(
        "POST",
        "https://gateway.example.com/mcp?cursor=next",
        headers={
            "Content-Type": "application/json",
            "mcp-session-id": "session-id",
        },
        content=b'{"jsonrpc":"2.0","method":"tools/list"}',
    )
    sts = SimpleNamespace(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        security_token="test-security-token",
    )

    headers = sign_httpx_request(request, sts)

    assert headers["Authorization"].startswith("V11-HMAC-SHA256")
    assert "Credential=test-ak/" in headers["Authorization"]
    assert "test-sk" not in headers["Authorization"]
    assert headers["X-Security-Token"] == "test-security-token"
    assert headers["X-Sdk-Content-Sha256"] == "UNSIGNED-PAYLOAD"
    assert headers["mcp-session-id"] == "session-id"


def test_extract_mcp_payload_prefers_structured_content():
    result = SimpleNamespace(
        isError=False,
        structuredContent={"ok": True},
        content=[SimpleNamespace(text='{"ok": false}')],
    )

    assert extract_mcp_payload(result) == {"ok": True}


def test_extract_mcp_payload_parses_json_text_content():
    result = SimpleNamespace(
        isError=False,
        structuredContent=None,
        content=[SimpleNamespace(text='{"tools": [{"name": "get_me"}]}')],
    )

    assert extract_mcp_payload(result) == {"tools": [{"name": "get_me"}]}


def test_extract_mcp_payload_rejects_text_tool_error_without_leaking_details():
    result = SimpleNamespace(
        isError=True,
        structuredContent=None,
        content=[SimpleNamespace(text="upstream denied: secret detail")],
    )

    with pytest.raises(MCPGatewayError) as exc_info:
        extract_mcp_payload(result)

    error = exc_info.value
    assert error.warning_type == "mcp_error"
    assert error.retryable is False
    assert str(error) == "GitHub MCP tool execution failed."
    assert "upstream denied" not in str(error)


def test_extract_mcp_payload_rejects_structured_tool_error():
    result = SimpleNamespace(
        isError=True,
        structuredContent={"error": "upstream denied"},
        content=[],
    )

    with pytest.raises(MCPGatewayError) as exc_info:
        extract_mcp_payload(result)

    error = exc_info.value
    assert error.warning_type == "mcp_error"
    assert error.retryable is False
    assert str(error) == "GitHub MCP tool execution failed."


def test_mcp_http_client_factory_ignores_environment_proxies():
    client = MCPGatewayClient(
        config=_enabled_config(),
        sts_credentials=_sts_credentials(),
    )

    factory = client._client().connections["github"]["httpx_client_factory"]
    http_client = factory(headers={}, timeout=httpx.Timeout(1.0), auth=None)

    try:
        assert http_client._trust_env is False
    finally:
        anyio.run(http_client.aclose)


def test_mcp_client_does_not_seed_session_id():
    client = MCPGatewayClient(
        config=_enabled_config(),
        sts_credentials=_sts_credentials(),
    )

    headers = client._client().connections["github"]["headers"]

    assert all(name.lower() != "mcp-session-id" for name in headers)


async def test_run_with_github_mcp_sts_reuses_one_session_for_operation(
    monkeypatch,
):
    state = _install_gateway_session_harness(monkeypatch)

    async def operation(client):
        tools = await client.list_tools()
        first = await client.call_tool("get_issue", {"number": 1})
        second = await client.call_tool("get_issue", {"number": 2})
        assert state.session_enters == 1
        assert state.session_exits == 0
        return tools, first, second

    tools, first, second = await gateway_client.run_with_github_mcp_sts(operation)

    assert tools[0].name == "target-github-mcp-get_me"
    assert first["arguments"] == {"number": 1}
    assert second["arguments"] == {"number": 2}
    assert state.adapter_constructions == 1
    assert state.session_enters == 1
    assert state.session_exits == 1
    assert [request[0] for request in state.requests] == [
        "list_tools",
        "get_issue",
        "get_issue",
    ]


async def test_run_with_github_mcp_sts_closes_session_when_operation_raises(
    monkeypatch,
):
    state = _install_gateway_session_harness(monkeypatch)
    failure = RuntimeError("operation failed")

    async def operation(client):
        await client.list_tools()
        raise failure

    with pytest.raises(RuntimeError) as exc_info:
        await gateway_client.run_with_github_mcp_sts(operation)

    assert exc_info.value is failure
    assert state.session_enters == 1
    assert state.session_exits == 1


async def test_session_task_group_preserves_typed_operation_error(monkeypatch):
    state = _install_gateway_session_harness(
        monkeypatch,
        task_group_session=True,
    )
    failure = MCPGatewayError(
        "rate_limited",
        "GitHub MCP rate limit reached.",
        retryable=True,
    )

    async def operation(client):
        await client.list_tools()
        raise failure

    with pytest.raises(MCPGatewayError) as exc_info:
        await gateway_client.run_with_github_mcp_sts(operation)

    assert exc_info.value is failure
    assert exc_info.value.warning_type == "rate_limited"
    assert exc_info.value.retryable is True
    assert state.session_enters == 1
    assert state.session_exits == 1


@pytest.mark.parametrize(
    ("enter_error", "warning_type", "retryable"),
    [
        (_http_status_error(503), "gateway_unavailable", True),
        (RuntimeError("initialize failed"), "mcp_error", False),
    ],
)
async def test_run_with_github_mcp_sts_maps_session_initialization_error(
    monkeypatch,
    enter_error,
    warning_type,
    retryable,
):
    state = _install_gateway_session_harness(
        monkeypatch,
        enter_error=enter_error,
    )

    async def operation(client):
        pytest.fail("operation must not run when session initialization fails")

    with pytest.raises(MCPGatewayError) as exc_info:
        await gateway_client.run_with_github_mcp_sts(operation)

    assert exc_info.value.warning_type == warning_type
    assert exc_info.value.retryable is retryable
    assert state.session_enters == 1
    assert state.session_exits == 0


async def test_run_with_github_mcp_sts_maps_adapter_construction_error(monkeypatch):
    state = _install_gateway_session_harness(
        monkeypatch,
        adapter_error=ValueError("invalid MCP connection config"),
    )

    async def operation(client):
        pytest.fail("operation must not run when adapter construction fails")

    with pytest.raises(MCPGatewayError) as exc_info:
        await gateway_client.run_with_github_mcp_sts(operation)

    assert exc_info.value.warning_type == "mcp_error"
    assert exc_info.value.retryable is False
    assert state.adapter_constructions == 1
    assert state.session_enters == 0
    assert state.session_exits == 0


async def test_reused_session_maps_in_flight_http_error_and_closes(monkeypatch):
    request = httpx.Request("POST", "https://gateway.example.com/mcp")
    state = _install_gateway_session_harness(
        monkeypatch,
        call_error=httpx.ReadTimeout("read timed out", request=request),
    )

    async def operation(client):
        return await client.call_tool("get_issue", {"number": 1})

    with pytest.raises(MCPGatewayError) as exc_info:
        await gateway_client.run_with_github_mcp_sts(operation)

    assert exc_info.value.warning_type == "gateway_unavailable"
    assert exc_info.value.retryable is True
    assert state.session_enters == 1
    assert state.session_exits == 1


def test_generic_mcp_error_maps_nested_remote_disconnect():
    exc = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [httpx.RemoteProtocolError("Server disconnected without sending a response.")],
    )

    error = _map_generic_mcp_error(exc)

    assert error.warning_type == "gateway_unavailable"
    assert error.retryable is True
