"""Tests for the curated Agent-facing GitHub activity facade."""

from __future__ import annotations

import pytest

import app.tools.github_activity_tools as gat
from app.mcp.github_activity_source import (
    GitHubActivityEvent,
    GitHubActivityResult,
    GitHubMCPWarning,
)


def test_agent_tool_collection_exposes_only_business_tools():
    assert {tool.name for tool in gat.GITHUB_ACTIVITY_TOOLS} == {
        "github_search_activity",
        "github_get_activity_detail",
    }


def test_agent_tool_schemas_exclude_credentials():
    credential_params = {"access_token", "api_key", "authorization", "sts"}

    for agent_tool in gat.GITHUB_ACTIVITY_TOOLS:
        fields = getattr(agent_tool.args_schema, "model_fields", {})
        assert credential_params.isdisjoint(fields)


def test_agent_tool_descriptions_route_mcp_without_oauth():
    for agent_tool in gat.GITHUB_ACTIVITY_TOOLS:
        assert "GitHub OAuth" in agent_tool.description
        assert "does not require" in agent_tool.description


@pytest.mark.asyncio
async def test_search_result_includes_platform_identity_scope(monkeypatch):
    async def fake_search(**kwargs):
        assert kwargs["cursor"] == "next-page"
        assert kwargs["actor"] is None
        return GitHubActivityResult(
            events=[
                GitHubActivityEvent(
                    provider="github",
                    event_type="commit",
                    repository="git-malu/personal-assistant",
                    external_id="abc123",
                    title="Fix MCP facade",
                )
            ],
            next_cursor="final-page",
        )

    monkeypatch.setattr(gat, "github_mcp_search_activity", fake_search)

    result = await gat.github_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-17T00:00:00Z",
        cursor="next-page",
    )

    assert result["identity_scope"] == "platform"
    assert result["next_cursor"] == "final-page"
    assert result["events"][0]["event_type"] == "commit"


@pytest.mark.asyncio
async def test_search_warning_includes_platform_identity_scope(monkeypatch):
    async def fake_search(**kwargs):
        return GitHubActivityResult(
            warnings=[
                GitHubMCPWarning(
                    ok=False,
                    warning_type="permission_denied",
                    message="GitHub denied access.",
                )
            ]
        )

    monkeypatch.setattr(gat, "github_mcp_search_activity", fake_search)

    result = await gat.github_search_activity(
        start_at="2026-07-01T00:00:00Z",
        end_at="2026-07-17T00:00:00Z",
    )

    assert result["ok"] is False
    assert result["identity_scope"] == "platform"
    assert result["warnings"][0]["warning_type"] == "permission_denied"


@pytest.mark.asyncio
async def test_detail_success_includes_platform_identity_scope(monkeypatch):
    async def fake_get_detail(**kwargs):
        assert kwargs["external_id"] == "abc123"
        return GitHubActivityEvent(
            provider="github",
            event_type="commit",
            repository="git-malu/personal-assistant",
            external_id="abc123",
            title="Fix MCP facade",
        )

    monkeypatch.setattr(gat, "github_mcp_get_detail", fake_get_detail)

    result = await gat.github_get_activity_detail(
        event_type="commit",
        repository="git-malu/personal-assistant",
        external_id="abc123",
    )

    assert result["ok"] is True
    assert result["identity_scope"] == "platform"
    assert result["event"]["external_id"] == "abc123"


@pytest.mark.asyncio
async def test_detail_warning_includes_platform_identity_scope(monkeypatch):
    async def fake_get_detail(**kwargs):
        return GitHubMCPWarning(
            ok=False,
            warning_type="permission_denied",
            message="GitHub denied access.",
        )

    monkeypatch.setattr(gat, "github_mcp_get_detail", fake_get_detail)

    result = await gat.github_get_activity_detail(
        event_type="issue",
        repository="git-malu/personal-assistant",
        external_id="15",
    )

    assert result == {
        "ok": False,
        "warning_type": "permission_denied",
        "message": "GitHub denied access.",
        "retryable": False,
        "identity_scope": "platform",
    }
