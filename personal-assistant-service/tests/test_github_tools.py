"""Unit tests for GitHub AgentArts Identity tools."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.tools.github_tools import (
    GITHUB_API_BASE,
    PROJECT_OWNER,
    PROJECT_REPO,
    GitHubToolError,
    _list_project_issues_impl,
    fetch_project_issues,
    fetch_project_pull_requests,
    list_project_issues,
    list_project_pull_requests,
)


def _response(status_code: int, json_data):
    request = httpx.Request("GET", "https://api.github.com/test")
    return httpx.Response(status_code, json=json_data, request=request)


class _AsyncClientMock:
    def __init__(self, response):
        self.response = response
        self.get = AsyncMock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_fetch_project_issues_filters_pull_requests():
    issue = {
        "number": 12,
        "title": "Bug report",
        "state": "open",
        "html_url": "https://github.com/git-malu/personal-assistant/issues/12",
        "user": {"login": "alice"},
        "updated_at": "2026-06-12T10:00:00Z",
        "labels": [{"name": "bug"}],
    }
    pull_request = {
        "number": 13,
        "title": "Feature PR",
        "state": "open",
        "html_url": "https://github.com/git-malu/personal-assistant/pull/13",
        "user": {"login": "bob"},
        "updated_at": "2026-06-12T11:00:00Z",
        "labels": [],
        "pull_request": {"url": "https://api.github.com/pr/13"},
    }
    client_mock = _AsyncClientMock(_response(200, [issue, pull_request]))

    with patch("app.tools.github_tools.httpx.AsyncClient", return_value=client_mock):
        result = await fetch_project_issues(
            access_token="token",
            state="open",
            limit=20,
        )

    assert result == [
        {
            "number": 12,
            "title": "Bug report",
            "state": "open",
            "html_url": "https://github.com/git-malu/personal-assistant/issues/12",
            "author": "alice",
            "updated_at": "2026-06-12T10:00:00Z",
            "labels": ["bug"],
        }
    ]
    client_mock.get.assert_awaited_once()
    args, kwargs = client_mock.get.await_args
    assert args[0] == f"{GITHUB_API_BASE}/repos/{PROJECT_OWNER}/{PROJECT_REPO}/issues"
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert kwargs["params"] == {"state": "open", "per_page": 20}


@pytest.mark.asyncio
async def test_fetch_project_pull_requests_parses_pr_fields():
    pr = {
        "number": 5,
        "title": "Add tool",
        "state": "open",
        "html_url": "https://github.com/git-malu/personal-assistant/pull/5",
        "user": {"login": "carol"},
        "updated_at": "2026-06-12T12:00:00Z",
        "labels": [{"name": "feature"}],
        "draft": False,
        "base": {"ref": "main"},
        "head": {"ref": "feature/github-tool"},
    }
    client_mock = _AsyncClientMock(_response(200, [pr]))

    with patch("app.tools.github_tools.httpx.AsyncClient", return_value=client_mock):
        result = await fetch_project_pull_requests(
            access_token="token",
            state="open",
            limit=20,
        )

    assert result == [
        {
            "number": 5,
            "title": "Add tool",
            "state": "open",
            "html_url": "https://github.com/git-malu/personal-assistant/pull/5",
            "author": "carol",
            "updated_at": "2026-06-12T12:00:00Z",
            "labels": ["feature"],
            "draft": False,
            "base": "main",
            "head": "feature/github-tool",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "reconnect your GitHub account"),
        (403, "permission or rate limit"),
        (404, f"{PROJECT_OWNER}/{PROJECT_REPO} was not found"),
        (500, "status 500"),
    ],
)
async def test_fetch_project_issues_converts_github_errors(status_code, expected):
    client_mock = _AsyncClientMock(_response(status_code, {"message": "bad things"}))

    with (
        patch("app.tools.github_tools.httpx.AsyncClient", return_value=client_mock),
        pytest.raises(GitHubToolError, match=expected),
    ):
        await fetch_project_issues(access_token="token")


@pytest.mark.asyncio
async def test_list_project_issues_original_function_requires_access_token():
    with pytest.raises(GitHubToolError, match="Missing GitHub access token"):
        await _list_project_issues_impl(access_token=None)


@pytest.mark.asyncio
async def test_list_project_issues_delegates_to_fetcher():
    with patch(
        "app.tools.github_tools.fetch_project_issues",
        AsyncMock(return_value=[{"number": 1}]),
    ) as mock_fetch:
        result = await _list_project_issues_impl(
            state="closed",
            limit=5,
            access_token="token",
        )

    assert result == [{"number": 1}]
    mock_fetch.assert_awaited_once_with(
        access_token="token",
        state="closed",
        limit=5,
    )


def test_access_token_is_not_part_of_tool_schema():
    issue_schema = list_project_issues.tool_call_schema.model_json_schema()
    pr_schema = list_project_pull_requests.tool_call_schema.model_json_schema()

    assert "access_token" not in issue_schema["properties"]
    assert "access_token" not in pr_schema["properties"]
