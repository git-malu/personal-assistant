"""Tests for app.tools.github_tools."""

from __future__ import annotations

import base64
import importlib

import pytest

from app.identity import AuthorizationRequired
from app.tools.github_tools import (
    _github_request,
    get_file_content,
    list_repo_contents,
    list_repositories,
    search_code,
)


@pytest.mark.asyncio
async def test_list_repositories_returns_structure(monkeypatch):
    async def fake_request(method, path, *, params=None):
        assert method == "GET"
        assert path == "/user/repos"
        return [
            {
                "name": "repo-a",
                "full_name": "alice/repo-a",
                "private": True,
                "default_branch": "main",
            }
        ]

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await list_repositories()
    assert isinstance(result, list)
    assert result[0]["full_name"] == "alice/repo-a"


@pytest.mark.asyncio
async def test_list_repo_contents_encodes_path(monkeypatch):
    async def fake_request(method, path, *, params=None):
        assert path == "/repos/alice/repo/contents/src/app"
        return [
            {
                "path": "src/app",
                "type": "dir",
                "name": "app",
            }
        ]

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await list_repo_contents("alice", "repo", "src/app")
    assert isinstance(result, list)
    assert result[0]["path"] == "src/app"


@pytest.mark.asyncio
async def test_get_file_content_decodes_base64(monkeypatch):
    encoded = base64.b64encode(b"hello world").decode()

    async def fake_request(method, path, *, params=None):
        return {
            "path": "README.md",
            "type": "file",
            "encoding": "base64",
            "content": encoded,
        }

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await get_file_content("alice", "repo", "README.md")
    assert result["content"] == "hello world"


@pytest.mark.asyncio
async def test_search_code_returns_items(monkeypatch):
    async def fake_request(method, path, *, params=None):
        assert path == "/search/code"
        return {"items": [{"name": "main.py"}]}

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await search_code("print('x')")
    assert isinstance(result, list)
    assert result[0]["name"] == "main.py"


@pytest.mark.asyncio
async def test_authorization_required_returns_structured_error(monkeypatch):
    async def fake_request(method, path, *, params=None):
        raise AuthorizationRequired(
            provider_name="github-provider",
            authorization_url="https://example.test/auth",
            message="authorization required",
        )

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await list_repositories()
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["provider_name"] == "github-provider"
    assert result["authorization_url"] == "https://example.test/auth"


@pytest.mark.asyncio
async def test_github_request_uses_sdk_require_access_token(monkeypatch, tmp_path):
    redacted_callback_url = (
        "https://agent-identity.example.test/v1/oauth2/callback/redacted-session"
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
identity:
  github:
    oauth2_callback_url: {redacted_callback_url}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.identity._CONFIG_PATH", config_path)
    monkeypatch.setattr("app.identity._service_config", None)
    github_tools_module = importlib.reload(
        importlib.import_module("app.tools.github_tools")
    )

    class FakeIdentityClient:
        async def get_resource_oauth2_token(
            self,
            *,
            provider_name,
            scopes,
            workload_access_token,
            on_auth_url,
            auth_flow,
            callback_url,
            force_authentication,
            token_poller,
            custom_state,
            custom_parameters,
        ):
            assert provider_name == "github-provider"
            assert scopes == ["repo", "read:user"]
            assert workload_access_token == "workload-token"
            assert auth_flow == "USER_FEDERATION"
            assert callback_url == redacted_callback_url
            assert force_authentication is False
            assert custom_state == "state-1"
            assert custom_parameters is None
            return "gh-token"

    async def fake_raw_request(access_token, method, path, *, params=None):
        assert access_token == "gh-token"
        assert method == "GET"
        assert path == "/user/repos"
        return [{"name": "repo-a"}]

    monkeypatch.setattr(
        "agentarts.sdk.identity.auth.IdentityClient",
        lambda *args, **kwargs: FakeIdentityClient(),
    )
    monkeypatch.setattr(github_tools_module, "_raw_github_request", fake_raw_request)

    from app.identity import runtime_context_scope

    with runtime_context_scope(
        workload_access_token="workload-token",
        oauth2_custom_state="state-1",
    ):
        assert await github_tools_module._github_request("GET", "/user/repos") == [
            {"name": "repo-a"}
        ]


@pytest.mark.asyncio
async def test_github_request_returns_authorization_required_url(monkeypatch):
    class FakeIdentityClient:
        async def get_resource_oauth2_token(
            self,
            *,
            provider_name,
            scopes,
            workload_access_token,
            on_auth_url,
            auth_flow,
            callback_url,
            force_authentication,
            token_poller,
            custom_state,
            custom_parameters,
        ):
            on_auth_url("https://github.example/authorize")
            return await token_poller.poll_for_token()

    monkeypatch.setattr(
        "agentarts.sdk.identity.auth.IdentityClient",
        lambda *args, **kwargs: FakeIdentityClient(),
    )

    from app.identity import runtime_context_scope

    with (
        runtime_context_scope(workload_access_token="workload-token"),
        pytest.raises(AuthorizationRequired) as exc_info,
    ):
        await _github_request("GET", "/user/repos")

    assert exc_info.value.authorization_url == "https://github.example/authorize"
