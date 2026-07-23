"""Tests for internal GitHub MCP activity source functions."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

import app.mcp.github_activity_source as gmt
import app.tools.github_activity_tools as gat
from app.mcp.gateway_client import MCPGatewayError, MCPToolInfo


class FakeMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo("target-github-mcp_get_me", "Get me", {}),
            MCPToolInfo(
                "target-github-mcp_search_repositories",
                "Search repositories",
                {"properties": {"query": {}, "perPage": {}, "page": {}}},
            ),
            MCPToolInfo(
                "target-github-mcp_list_commits",
                "List commits",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "since": {},
                        "until": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_list_pull_requests",
                "List pull requests",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "state": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_list_issues",
                "List issues",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "state": {},
                        "since": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_get_issue_comments",
                "Get issue comments",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "issueNumber": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_get_pull_request_comments",
                "Get pull request comments",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "pullNumber": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_create_issue",
                "Create issue",
                {"properties": {"owner": {}, "repo": {}, "title": {}}},
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name.endswith("get_me"):
            return {"login": "T-1009"}
        if name.endswith("search_repositories"):
            return {
                "repositories": [
                    {
                        "name": "personal-assistant",
                        "full_name": "T-1009/personal-assistant",
                        "archived": False,
                    }
                ]
            }
        if name.endswith("list_commits"):
            return [
                {
                    "sha": "abcdef123456",
                    "html_url": "https://github.com/T-1009/personal-assistant/commit/abcdef",
                    "author": {"login": "T-1009"},
                    "commit": {
                        "message": "Implement feature 17",
                        "author": {"date": "2026-07-10T12:00:00Z"},
                    },
                    "stats": {"additions": 10, "deletions": 2},
                }
            ]
        if name.endswith("list_pull_requests"):
            return [
                {
                    "number": 17,
                    "title": "Feature 17",
                    "html_url": "https://github.com/T-1009/personal-assistant/pull/17",
                    "user": {"login": "T-1009"},
                    "state": "open",
                    "created_at": "2026-07-11T12:00:00Z",
                    "updated_at": "2026-07-12T12:00:00Z",
                    "comments": 1,
                }
            ]
        if name.endswith("list_issues"):
            return [
                {
                    "number": 99,
                    "title": "Track MCP smoke",
                    "html_url": "https://github.com/T-1009/personal-assistant/issues/99",
                    "user": {"login": "T-1009"},
                    "state": "open",
                    "created_at": "2026-07-09T12:00:00Z",
                    "updated_at": "2026-07-09T13:00:00Z",
                    "comments": 1,
                },
                {
                    "number": 17,
                    "pull_request": {
                        "url": (
                            "https://api.github.com/repos/T-1009/"
                            "personal-assistant/pulls/17"
                        )
                    },
                    "title": "PR issue shadow",
                },
            ]
        if name.endswith("get_issue_comments"):
            return {
                "comments": [
                    {
                        "id": 1,
                        "body": "Looks good",
                        "html_url": "https://github.com/T-1009/personal-assistant/issues/99#issuecomment-1",
                        "user": {"login": "T-1009"},
                        "created_at": "2026-07-09T14:00:00Z",
                    }
                ]
            }
        if name.endswith("get_pull_request_comments"):
            return {
                "comments": [
                    {
                        "id": 2,
                        "body": "Pull request comment",
                        "user": {"login": "T-1009"},
                        "created_at": "2026-07-12T14:00:00Z",
                    }
                ]
            }
        raise AssertionError(f"Unexpected tool: {name}")


class PaginatedMCPClient:
    def __init__(
        self,
        *,
        issues: list[dict[str, Any]] | None = None,
        fail_commits: bool = False,
        retryable_commits: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_commits = fail_commits
        self.retryable_commits = retryable_commits
        self.commits = [
            {
                "sha": f"commit-{index}",
                "author": {"login": "T-1009"},
                "commit": {
                    "message": f"Commit {index}",
                    "author": {"date": f"2026-07-0{index}T12:00:00Z"},
                },
            }
            for index in range(1, 4)
        ]
        self.pull_requests = [
            {
                "number": 17,
                "title": "Feature 17",
                "user": {"login": "T-1009"},
                "state": "open",
                "created_at": "2026-07-04T12:00:00Z",
                "updated_at": "2026-07-04T13:00:00Z",
            }
        ]
        self.issues = issues or [
            {
                "number": 99,
                "title": "Pagination issue",
                "user": {"login": "T-1009"},
                "state": "open",
                "created_at": "2026-07-05T12:00:00Z",
                "updated_at": "2026-07-05T13:00:00Z",
            }
        ]
        self.comments = [
            {
                "id": 100 + index,
                "body": f"Comment {index}",
                "user": {"login": "T-1009"},
                "created_at": f"2026-07-0{5 + index}T12:00:00Z",
            }
            for index in range(1, 4)
        ]
        self.pull_request_comments = [
            {
                "id": 300 + index,
                "body": f"Pull request comment {index}",
                "user": {"login": "T-1009"},
                "created_at": f"2026-07-0{5 + index}T14:00:00Z",
            }
            for index in range(1, 4)
        ]
        self.reviews = [
            {
                "id": 200 + index,
                "body": f"Review {index}",
                "state": "COMMENTED",
                "user": {"login": "T-1009"},
                "submitted_at": f"2026-07-0{5 + index}T13:00:00Z",
            }
            for index in range(1, 4)
        ]

    async def list_tools(self) -> list[MCPToolInfo]:
        common = {"owner": {}, "repo": {}, "perPage": {}, "page": {}}
        return [
            MCPToolInfo("target-github-mcp_get_me", "Get me", {}),
            MCPToolInfo(
                "target-github-mcp_list_commits",
                "List commits",
                {"properties": common | {"since": {}, "until": {}}},
            ),
            MCPToolInfo(
                "target-github-mcp_list_pull_requests",
                "List pull requests",
                {"properties": common | {"state": {}}},
            ),
            MCPToolInfo(
                "target-github-mcp_list_issues",
                "List issues",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "perPage": {},
                        "after": {},
                        "state": {},
                        "since": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_get_issue_comments",
                "Get issue comments",
                {
                    "properties": common
                    | {
                        "issueNumber": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_get_pull_request_reviews",
                "Get pull request reviews",
                {
                    "properties": common
                    | {
                        "pullNumber": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_get_pull_request_comments",
                "Get pull request comments",
                {
                    "properties": common
                    | {
                        "pullNumber": {},
                    }
                },
            ),
        ]

    @staticmethod
    def _page(items: list[dict[str, Any]], arguments: dict[str, Any]) -> Any:
        page_size = arguments["perPage"]
        page = arguments.get("page", 1)
        start = (page - 1) * page_size
        return items[start : start + page_size]

    def _issue_page(self, arguments: dict[str, Any]) -> dict[str, Any]:
        page_size = arguments["perPage"]
        after = arguments.get("after")
        start = int(after.split(":", maxsplit=1)[1]) if after else 0
        end = min(start + page_size, len(self.issues))
        has_next = end < len(self.issues)
        return {
            "issues": self.issues[start:end],
            "pageInfo": {
                "hasNextPage": has_next,
                "endCursor": f"issues:{end}" if has_next else None,
            },
        }

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name.endswith("get_me"):
            return {"login": "T-1009"}
        if name.endswith("list_commits"):
            if self.fail_commits:
                raise MCPGatewayError(
                    "permission_denied",
                    "Commit activity is not readable.",
                    retryable=self.retryable_commits,
                )
            return self._page(self.commits, arguments)
        if name.endswith("list_pull_requests"):
            return self._page(self.pull_requests, arguments)
        if name.endswith("list_issues"):
            return self._issue_page(arguments)
        if name.endswith("get_issue_comments"):
            return {"comments": self._page(self.comments, arguments)}
        if name.endswith("get_pull_request_comments"):
            return {"comments": self._page(self.pull_request_comments, arguments)}
        if name.endswith("get_pull_request_reviews"):
            return self._page(self.reviews, arguments)
        raise AssertionError(f"Unexpected tool: {name}")


class UnpageableMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo("target-github-mcp_get_me", "Get me", {}),
            MCPToolInfo(
                "target-github-mcp_list_commits",
                "List commits",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "perPage": {},
                    }
                },
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name.endswith("get_me"):
            return {"login": "T-1009"}
        return [
            {
                "sha": "only-page",
                "author": {"login": "T-1009"},
                "commit": {
                    "message": "Potentially truncated",
                    "author": {"date": "2026-07-10T12:00:00Z"},
                },
            }
        ]


class RepositoryDiscoveryMCPClient(PaginatedMCPClient):
    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(
                "target-github-mcp_search_repositories",
                "Search repositories",
                {
                    "properties": {
                        "query": {},
                        "perPage": {},
                        "after": {},
                    }
                },
            ),
            *(await super().list_tools()),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name.endswith("search_repositories"):
            self.calls.append((name, arguments))
            return {
                "repositories": [
                    {
                        "name": "personal-assistant",
                        "full_name": "T-1009/personal-assistant",
                        "archived": False,
                    }
                ],
                "pageInfo": {
                    "hasNextPage": True,
                    "endCursor": "repositories:1",
                },
            }
        return await super().call_tool(name, arguments)


class DetailMCPClient:
    def __init__(
        self,
        tool_name: str,
        number_argument: str,
        payload: dict[str, Any],
    ) -> None:
        self.tool_name = tool_name
        self.number_argument = number_argument
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(
                self.tool_name,
                "Read activity detail",
                {
                    "properties": {
                        "method": {},
                        "owner": {},
                        "repo": {},
                        self.number_argument: {},
                    }
                },
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return self.payload


class CompleteIssueReadMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.payloads = {
            "get": {"number": 17, "title": "Feature 17 issue", "state": "open"},
            "get_comments": [{"id": 1, "body": "First comment"}],
            "get_sub_issues": {"sub_issues": [{"number": 18}]},
            "get_parent": {"number": 10, "title": "Parent issue"},
            "get_labels": [{"name": "feature"}],
        }

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(
                "target-github-mcp_issue_read",
                "Read issue data",
                {
                    "properties": {
                        "method": {"enum": list(self.payloads)},
                        "owner": {},
                        "repo": {},
                        "issue_number": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_get_issue",
                "Get issue",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "issue_number": {},
                    }
                },
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        assert name == "target-github-mcp_issue_read"
        self.calls.append((name, arguments))
        return self.payloads[arguments["method"]]


class ReviewCommentDetailMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reviews = [
            {"id": 700, "state": "COMMENTED", "body": "Other review"},
            {"id": 701, "state": "APPROVED", "body": "Approved"},
        ]
        self.comments = {
            "comments": [
                {"id": 800, "body": "Other comment"},
                {"id": 801, "body": "Target comment"},
            ]
        }

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(
                "target-github-mcp_pull_request_read",
                "Read pull request data",
                {
                    "properties": {
                        "method": {"enum": ["get_comments", "get_reviews"]},
                        "owner": {},
                        "repo": {},
                        "pullNumber": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_issue_read",
                "Read issue data",
                {
                    "properties": {
                        "method": {"enum": ["get_comments"]},
                        "owner": {},
                        "repo": {},
                        "issue_number": {},
                    }
                },
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name.endswith("pull_request_read"):
            return self.reviews
        if name.endswith("issue_read"):
            return self.comments
        raise AssertionError(f"Unexpected tool: {name}")


class ConsolidatedPRActivityMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo("target-github-mcp_get_me", "Get me", {}),
            MCPToolInfo(
                "target-github-mcp_list_issues",
                "List issues and pull requests",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "state": {},
                        "since": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_list_pull_requests",
                "List pull requests",
                {
                    "properties": {
                        "owner": {},
                        "repo": {},
                        "state": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_issue_read",
                "Read issue data",
                {
                    "properties": {
                        "method": {"enum": ["get_comments"]},
                        "owner": {},
                        "repo": {},
                        "issue_number": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
            MCPToolInfo(
                "target-github-mcp_pull_request_read",
                "Read pull request data",
                {
                    "properties": {
                        "method": {"enum": ["get_comments", "get_reviews"]},
                        "owner": {},
                        "repo": {},
                        "pullNumber": {},
                        "perPage": {},
                        "page": {},
                    }
                },
            ),
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name.endswith("get_me"):
            return {"login": "git-malu"}
        if name.endswith("list_issues"):
            return [
                {
                    "number": 99,
                    "title": "Regular issue",
                    "user": {"login": "git-malu"},
                    "updated_at": "2026-07-15T08:00:00Z",
                }
            ]
        if name.endswith("list_pull_requests"):
            return [
                {
                    "number": 15,
                    "title": "Feature 17 pull request",
                    "user": {"login": "git-malu"},
                    "updated_at": "2026-07-16T08:00:00Z",
                }
            ]
        if name.endswith("issue_read"):
            parent = arguments["issue_number"]
            return {
                "comments": [
                    {
                        "id": 1501 if parent == 15 else 9901,
                        "body": "Pull request comment"
                        if parent == 15
                        else "Issue comment",
                        "user": {"login": "git-malu"},
                        "created_at": "2026-07-16T09:00:00Z",
                    }
                ]
            }
        if name.endswith("pull_request_read"):
            if arguments["method"] == "get_comments":
                return {
                    "comments": [
                        {
                            "id": 1501,
                            "body": "Pull request comment",
                            "user": {"login": "git-malu"},
                            "created_at": "2026-07-16T09:00:00Z",
                        }
                    ]
                }
            return [
                {
                    "id": 1502,
                    "state": "COMMENTED",
                    "body": "Pull request review",
                    "user": {"login": "git-malu"},
                    "submitted_at": "2026-07-16T10:00:00Z",
                }
            ]
        raise AssertionError(f"Unexpected tool: {name}")


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    return client


def test_github_mcp_public_schema_is_secret_free():
    assert gmt.github_mcp_public_schema_is_secret_free() is True


def test_read_only_activity_tool_allowlist_blocks_writes():
    assert gmt.is_read_only_activity_tool("target-github-mcp_get_me") is True
    assert gmt.is_read_only_activity_tool("target-github-mcp_create_issue") is False
    assert gmt.is_read_only_activity_tool("target-github-mcp_delete_file") is False


@pytest.mark.asyncio
async def test_resolve_identity_returns_platform_account(fake_client):
    result = await gmt.github_mcp_resolve_identity()

    assert result == {"login": "T-1009"}
    assert fake_client.calls[0] == ("target-github-mcp_get_me", {})


@pytest.mark.asyncio
async def test_list_repositories_uses_search_repositories(fake_client):
    result = await gmt.github_mcp_list_repositories(limit=5)

    assert isinstance(result, list)
    assert result[0]["full_name"] == "T-1009/personal-assistant"
    search_call = fake_client.calls[-1]
    assert search_call[0] == "target-github-mcp_search_repositories"
    assert search_call[1]["query"] == "user:T-1009"


@pytest.mark.asyncio
async def test_search_activity_normalizes_events(fake_client):
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00+08:00",
        end_at="2026-07-13T23:59:59+08:00",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit", "pull_request", "issue", "comment"],
        limit=10,
    )

    assert isinstance(result, gmt.GitHubActivityResult)
    assert result.identity_scope == "platform"
    assert result.warnings == []
    assert result.next_cursor is None
    event_types = {event.event_type for event in result.events}
    assert event_types == {"commit", "pull_request", "issue", "comment"}
    commit = next(event for event in result.events if event.event_type == "commit")
    assert commit.external_id == "abcdef123456"
    assert commit.metrics["additions"] == 10
    issue = next(event for event in result.events if event.event_type == "issue")
    assert issue.external_id == "99"


@pytest.mark.asyncio
async def test_agent_search_activity_returns_json_safe_result(fake_client):
    result = await gat.github_search_activity(
        start_at="2026-07-01T00:00:00+08:00",
        end_at="2026-07-13T23:59:59+08:00",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=10,
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["events"][0]["event_type"] == "commit"
    assert result["events"][0]["repository"] == "T-1009/personal-assistant"
    assert result["warnings"] == []
    assert result["next_cursor"] is None
    assert result["identity_scope"] == "platform"


@pytest.mark.asyncio
async def test_search_activity_maps_gateway_error_to_warning(monkeypatch):
    async def fake_run(operation):
        raise MCPGatewayError(
            "permission_denied",
            "GitHub MCP Gateway rejected the caller permissions.",
        )

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00+08:00",
        end_at="2026-07-13T23:59:59+08:00",
    )

    assert isinstance(result, gmt.GitHubActivityResult)
    assert result.events == []
    assert result.warnings[0].warning_type == "permission_denied"
    assert "permissions" in result.warnings[0].message


@pytest.mark.asyncio
async def test_search_activity_continues_all_event_types_without_duplicates(
    monkeypatch,
):
    client = PaginatedMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    cursor = None
    events = []
    for _ in range(10):
        result = await gmt.github_mcp_search_activity(
            start_at="2026-07-01T00:00:00Z",
            end_at="2026-07-13T23:59:59Z",
            repositories=["T-1009/personal-assistant"],
            event_types=[
                "commit",
                "pull_request",
                "issue",
                "comment",
                "review",
            ],
            limit=2,
            cursor=cursor,
        )

        assert isinstance(result, gmt.GitHubActivityResult)
        assert result.identity_scope == "platform"
        assert result.warnings == []
        events.extend(result.events)
        cursor = result.next_cursor
        if cursor is None:
            break

    assert cursor is None
    event_keys = [
        (
            event.repository,
            event.event_type,
            event.parent_external_id,
            event.external_id,
        )
        for event in events
    ]
    assert len(event_keys) == len(set(event_keys)) == 14
    assert {event.event_type for event in events} == {
        "commit",
        "pull_request",
        "issue",
        "comment",
        "review",
    }

    comment_pages = [
        arguments["page"]
        for name, arguments in client.calls
        if name.endswith("get_issue_comments")
    ]
    assert comment_pages == [1, 1, 2]
    pull_request_comment_pages = [
        arguments["page"]
        for name, arguments in client.calls
        if name.endswith("get_pull_request_comments")
    ]
    assert pull_request_comment_pages == [1, 2]
    assert any(
        name.endswith("list_commits") and arguments["page"] == 2
        for name, arguments in client.calls
    )
    assert any(
        name.endswith("get_pull_request_reviews") and arguments["page"] == 2
        for name, arguments in client.calls
    )


@pytest.mark.asyncio
async def test_search_activity_uses_schema_after_cursor(monkeypatch):
    issues = [
        {
            "number": number,
            "title": f"Issue {number}",
            "user": {"login": "T-1009"},
            "state": "open",
            "created_at": f"2026-07-0{number}T12:00:00Z",
            "updated_at": f"2026-07-0{number}T13:00:00Z",
        }
        for number in range(1, 4)
    ]
    client = PaginatedMCPClient(issues=issues)

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    first = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["issue"],
        limit=2,
    )
    second = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["issue"],
        limit=2,
        cursor=first.next_cursor,
    )

    assert first.next_cursor is not None
    assert second.next_cursor is None
    assert [event.external_id for event in first.events + second.events] == [
        "1",
        "2",
        "3",
    ]
    issue_calls = [
        arguments for name, arguments in client.calls if name.endswith("list_issues")
    ]
    assert "after" not in issue_calls[0]
    assert issue_calls[1]["after"] == "issues:2"


@pytest.mark.asyncio
async def test_search_activity_rejects_invalid_cursor_before_mcp_call(fake_client):
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        cursor="not-a-valid-cursor",
    )

    assert result.events == []
    assert result.next_cursor is None
    assert result.warnings[0].warning_type == "configuration_error"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_search_activity_keeps_partial_events_with_typed_warning(monkeypatch):
    client = PaginatedMCPClient(fail_commits=True)

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit", "issue"],
        limit=10,
    )

    assert [event.event_type for event in result.events] == ["issue"]
    assert result.warnings[0].warning_type == "permission_denied"
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_search_activity_retains_retryable_task_in_cursor(monkeypatch):
    client = PaginatedMCPClient(
        fail_commits=True,
        retryable_commits=True,
    )

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit", "issue"],
        limit=10,
    )

    assert result.events == []
    assert result.warnings[0].retryable is True
    assert result.next_cursor is not None


@pytest.mark.asyncio
async def test_search_activity_warns_when_full_page_cannot_continue(monkeypatch):
    client = UnpageableMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=1,
    )

    assert [event.external_id for event in result.events] == ["only-page"]
    assert result.next_cursor is None
    assert result.warnings[0].warning_type == "pagination_unsupported"


@pytest.mark.asyncio
async def test_search_activity_warns_for_unpageable_nonempty_default_page(
    monkeypatch,
):
    client = UnpageableMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=100,
    )

    assert [event.external_id for event in result.events] == ["only-page"]
    assert result.warnings[0].warning_type == "pagination_unsupported"


@pytest.mark.asyncio
async def test_search_activity_reports_missing_selected_capability(monkeypatch):
    client = UnpageableMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["issue"],
        limit=10,
    )

    assert result.events == []
    assert result.next_cursor is None
    assert result.warnings[0].warning_type == "capability_missing"
    assert "issue" in result.warnings[0].message


@pytest.mark.asyncio
async def test_search_activity_deduplicates_repository_tasks(monkeypatch):
    client = PaginatedMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=[
            "T-1009/personal-assistant",
            "T-1009/personal-assistant",
        ],
        event_types=["commit"],
        limit=100,
    )

    assert [event.external_id for event in result.events] == [
        "commit-1",
        "commit-2",
        "commit-3",
    ]
    assert len([name for name, _ in client.calls if name.endswith("list_commits")]) == 1


@pytest.mark.asyncio
async def test_search_activity_warns_when_repository_discovery_has_more(monkeypatch):
    client = RepositoryDiscoveryMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        event_types=["commit"],
        limit=1,
    )

    warning_types = {warning.warning_type for warning in result.warnings}
    assert "repository_discovery_truncated" in warning_types
    repository_call = next(
        arguments
        for name, arguments in client.calls
        if name.endswith("search_repositories")
    )
    assert repository_call["perPage"] == 100


@pytest.mark.asyncio
async def test_search_activity_rejects_duplicate_cursor_tasks(monkeypatch):
    client = PaginatedMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    first = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=2,
    )
    assert first.next_cursor is not None

    padded = first.next_cursor + "=" * (-len(first.next_cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    payload["tasks"].append(dict(payload["tasks"][0]))
    forged_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    calls_before = len(client.calls)

    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=2,
        cursor=forged_cursor,
    )

    assert result.events == []
    assert result.warnings[0].warning_type == "configuration_error"
    assert len(client.calls) == calls_before


@pytest.mark.asyncio
async def test_search_activity_warns_when_page_budget_requires_continuation(
    monkeypatch,
):
    client = PaginatedMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    monkeypatch.setattr(gmt, "_MAX_PAGE_CALLS_PER_SEARCH", 1)
    first = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit", "issue"],
        limit=10,
    )
    second = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit", "issue"],
        limit=10,
        cursor=first.next_cursor,
    )

    assert first.next_cursor is not None
    assert first.warnings[0].warning_type == "pagination_budget_exhausted"
    assert [event.event_type for event in second.events] == ["issue"]
    assert second.next_cursor is None
    assert second.warnings == []


@pytest.mark.asyncio
async def test_agent_search_activity_passes_continuation_cursor(monkeypatch):
    client = PaginatedMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)
    first = await gat.github_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=2,
    )
    second = await gat.github_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-13T23:59:59Z",
        repositories=["T-1009/personal-assistant"],
        event_types=["commit"],
        limit=2,
        cursor=first["next_cursor"],
    )

    assert first["count"] == 2
    assert first["next_cursor"] is not None
    assert second["count"] == 1
    assert second["next_cursor"] is None
    assert second["identity_scope"] == "platform"


@pytest.mark.parametrize(
    ("event_type", "tool_name", "number_argument", "payload"),
    [
        (
            "pull_request",
            "target-github-mcp_pull_request_read",
            "pullNumber",
            {"number": 17, "title": "Feature 17", "state": "open"},
        ),
        (
            "issue",
            "target-github-mcp_issue_read",
            "issue_number",
            {"number": 17, "title": "Feature 17 issue", "state": "open"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_get_detail_sets_get_method_for_aggregate_read_tools(
    monkeypatch,
    event_type,
    tool_name,
    number_argument,
    payload,
):
    client = DetailMCPClient(tool_name, number_argument, payload)

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_get_detail(
        event_type=event_type,
        repository="T-1009/personal-assistant",
        external_id="17",
    )

    assert isinstance(result, gmt.GitHubActivityEvent)
    assert client.calls == [
        (
            tool_name,
            {
                "method": "get",
                "owner": "T-1009",
                "repo": "personal-assistant",
                number_argument: 17,
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_issue_detail_calls_every_supported_issue_read_method(monkeypatch):
    client = CompleteIssueReadMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_get_detail(
        event_type="issue",
        repository="T-1009/personal-assistant",
        external_id="17",
    )

    assert isinstance(result, gmt.GitHubActivityEvent)
    assert [arguments["method"] for _, arguments in client.calls] == [
        "get",
        "get_comments",
        "get_sub_issues",
        "get_parent",
        "get_labels",
    ]
    assert all(
        arguments["owner"] == "T-1009"
        and arguments["repo"] == "personal-assistant"
        and arguments["issue_number"] == 17
        for _, arguments in client.calls
    )
    assert result.details == {
        "issue": client.payloads["get"],
        "comments": client.payloads["get_comments"],
        "sub_issues": client.payloads["get_sub_issues"],
        "parent": client.payloads["get_parent"],
        "labels": client.payloads["get_labels"],
    }


@pytest.mark.asyncio
async def test_search_comment_event_includes_parent_external_id(fake_client):
    result = await gmt.github_mcp_search_activity(
        start_at="2026-07-01T00:00:00+08:00",
        end_at="2026-07-13T23:59:59+08:00",
        repositories=["T-1009/personal-assistant"],
        event_types=["issue", "comment"],
        limit=10,
    )

    assert isinstance(result, gmt.GitHubActivityResult)
    comment = next(event for event in result.events if event.event_type == "comment")
    assert comment.external_id == "1"
    assert comment.parent_external_id == "99"


@pytest.mark.asyncio
async def test_search_comment_includes_pull_request_conversation_comments(monkeypatch):
    client = ConsolidatedPRActivityMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_search_activity(
        start_at="2026-06-14T00:00:00+08:00",
        end_at="2026-07-17T23:59:59+08:00",
        repositories=["git-malu/personal-assistant"],
        event_types=["comment"],
        limit=10,
    )

    pr_comment = next(
        event for event in result.events if event.parent_external_id == "15"
    )
    assert pr_comment.external_id == "1501"
    assert pr_comment.summary == "Pull request comment"
    assert any(
        name.endswith("pull_request_read")
        and arguments["method"] == "get_comments"
        and arguments["pullNumber"] == 15
        for name, arguments in client.calls
    )


@pytest.mark.asyncio
async def test_get_detail_supports_pull_request_conversation_comment(monkeypatch):
    client = ConsolidatedPRActivityMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_get_detail(
        event_type="comment",
        repository="git-malu/personal-assistant",
        external_id="1501",
        parent_external_id="15",
    )

    assert isinstance(result, gmt.GitHubActivityEvent)
    assert result.event_type == "comment"
    assert result.external_id == "1501"
    assert result.parent_external_id == "15"
    assert result.details["comment"]["body"] == "Pull request comment"
    assert client.calls[-1] == (
        "target-github-mcp_issue_read",
        {
            "method": "get_comments",
            "owner": "git-malu",
            "repo": "personal-assistant",
            "issue_number": 15,
        },
    )


@pytest.mark.asyncio
async def test_search_reviews_uses_consolidated_pull_request_read(monkeypatch):
    client = ConsolidatedPRActivityMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_search_activity(
        start_at="2026-06-14T00:00:00+08:00",
        end_at="2026-07-17T23:59:59+08:00",
        repositories=["git-malu/personal-assistant"],
        event_types=["review"],
        limit=10,
    )

    review = next(event for event in result.events if event.event_type == "review")
    assert review.external_id == "1502"
    assert review.parent_external_id == "15"
    assert any(
        name.endswith("pull_request_read")
        and arguments["method"] == "get_reviews"
        and arguments["pullNumber"] == 15
        for name, arguments in client.calls
    )


@pytest.mark.parametrize(
    (
        "event_type",
        "external_id",
        "parent_external_id",
        "method",
        "number_argument",
        "detail_key",
    ),
    [
        ("review", "701", "17", "get_reviews", "pullNumber", "review"),
        ("comment", "801", "99", "get_comments", "issue_number", "comment"),
    ],
)
@pytest.mark.asyncio
async def test_get_detail_supports_review_and_comment(
    monkeypatch,
    event_type,
    external_id,
    parent_external_id,
    method,
    number_argument,
    detail_key,
):
    client = ReviewCommentDetailMCPClient()

    async def fake_run(operation):
        return await operation(client)

    monkeypatch.setattr(gmt, "run_with_github_mcp_sts", fake_run)

    result = await gmt.github_mcp_get_detail(
        event_type=event_type,
        repository="T-1009/personal-assistant",
        external_id=external_id,
        parent_external_id=parent_external_id,
    )

    assert isinstance(result, gmt.GitHubActivityEvent)
    assert result.event_type == event_type
    assert result.external_id == external_id
    assert result.parent_external_id == parent_external_id
    assert result.details[detail_key]["id"] == int(external_id)
    assert client.calls == [
        (
            client.calls[0][0],
            {
                "method": method,
                "owner": "T-1009",
                "repo": "personal-assistant",
                number_argument: int(parent_external_id),
            },
        )
    ]


@pytest.mark.parametrize("event_type", ["review", "comment"])
@pytest.mark.asyncio
async def test_get_detail_requires_parent_external_id(event_type):
    result = await gmt.github_mcp_get_detail(
        event_type=event_type,
        repository="T-1009/personal-assistant",
        external_id="123",
    )

    assert isinstance(result, gmt.GitHubMCPWarning)
    assert result.warning_type == "configuration_error"
    assert "parent_external_id" in result.message


def test_get_detail_agent_schema_includes_parent_external_id():
    detail_tool = next(
        tool
        for tool in gat.GITHUB_ACTIVITY_TOOLS
        if tool.name == "github_get_activity_detail"
    )
    schema = detail_tool.args_schema.model_json_schema()

    assert "parent_external_id" in schema["properties"]
    assert set(schema["properties"]["event_type"]["enum"]) == {
        "commit",
        "pull_request",
        "issue",
        "review",
        "comment",
    }
