"""Tests for app.tools.github_tools."""

from __future__ import annotations

import base64
import inspect

import pytest
from httpx import Request, Response

import app.tools.github_tools as gh
from app.tools.github_tools import (
    GITHUB_API_BASE_URL,
    _raw_github_request,
    get_file_content,
    list_repo_contents,
    list_repositories,
    search_code,
    star_repository,
)


def test_github_public_tool_signatures_exclude_access_token():
    signatures = {
        "list_repositories": list_repositories,
        "list_repo_contents": list_repo_contents,
        "get_file_content": get_file_content,
        "search_code": search_code,
        "star_repository": star_repository,
    }

    for name, func in signatures.items():
        assert "access_token" not in inspect.signature(func).parameters, name


def test_github_oauth_tool_descriptions_exclude_mcp_routing():
    for github_tool in gh.GITHUB_TOOLS:
        assert "end-user OAuth" in github_tool.description
        assert "GitHub MCP" in github_tool.description


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
    assert result[0]["private"] is True


@pytest.mark.asyncio
async def test_list_repo_contents_encodes_path(monkeypatch):
    async def fake_request(method, path, *, params=None):
        assert path == "/repos/alice/repo/contents/src/app"
        return [{"path": "src/app", "type": "dir", "name": "app"}]

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await list_repo_contents("alice", "repo", "src/app")
    assert isinstance(result, dict)
    assert result["count"] == 1
    assert result["items"][0]["path"] == "src/app"
    assert result["items"][0]["type"] == "dir"


@pytest.mark.asyncio
async def test_list_repo_contents_wraps_file_items_to_avoid_content_blocks(
    monkeypatch,
):
    async def fake_request(method, path, *, params=None):
        return [{"path": "README.md", "type": "file", "name": "README.md"}]

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await list_repo_contents("alice", "repo")
    assert isinstance(result, dict)
    assert result["items"][0]["type"] == "file"


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
        assert params == {"q": "print('x')"}
        return {"items": [{"name": "main.py"}]}

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await search_code("print('x')")
    assert isinstance(result, list)
    assert result[0]["name"] == "main.py"


@pytest.mark.asyncio
async def test_star_repository_confirm_false_returns_preview(monkeypatch):
    async def fake_request(method, path, *, params=None):
        raise AssertionError("star_repository should not call GitHub before confirm")

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await star_repository("alice", "repo")
    assert result["starred"] is False
    assert result["requires_confirmation"] is True
    assert result["repository"] == "alice/repo"
    assert result["preview"]["owner"] == "alice"
    assert "请确认" in result["error"]


@pytest.mark.asyncio
async def test_star_repository_confirm_true_puts_starred_endpoint(monkeypatch):
    async def fake_request(method, path, *, params=None):
        assert method == "PUT"
        assert path == "/user/starred/alice/repo"
        assert params is None
        return None

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await star_repository("alice", "repo", confirm=True)
    assert result == {"starred": True, "repository": "alice/repo", "error": None}


@pytest.mark.asyncio
async def test_star_repository_requires_owner_and_repo(monkeypatch):
    async def fake_request(method, path, *, params=None):
        raise AssertionError("star_repository should validate before GitHub request")

    monkeypatch.setattr("app.tools.github_tools._github_request", fake_request)

    result = await star_repository("", "repo", confirm=True)
    assert result["starred"] is False
    assert "owner and repo" in result["error"]


@pytest.mark.asyncio
async def test_raw_github_request_handles_put_no_content(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout):
            assert base_url == GITHUB_API_BASE_URL
            assert timeout == 30.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, path, *, headers, params=None):
            captured["method"] = method
            captured["path"] = path
            captured["headers"] = headers
            captured["params"] = params
            return Response(204, request=Request(method, str(GITHUB_API_BASE_URL)))

    monkeypatch.setattr("app.tools.github_tools.httpx.AsyncClient", FakeAsyncClient)

    result = await _raw_github_request("token", "PUT", "/user/starred/alice/repo")
    assert result is None
    assert captured["headers"]["Content-Length"] == "0"


@pytest.mark.asyncio
async def test_github_request_without_token_is_programming_error():
    """Raw auth boundary requires decorator-injected token."""
    raw_request = gh._github_request
    while hasattr(raw_request, "__wrapped__"):
        raw_request = raw_request.__wrapped__

    with pytest.raises(RuntimeError, match="access_token"):
        await raw_request("GET", "/user/repos", access_token=None)
