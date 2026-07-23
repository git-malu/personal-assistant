"""Curated Agent-facing tools for the GitHub MCP activity source."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool as lc_tool

from app.mcp.github_activity_source import (
    GitHubActivityType,
    GitHubMCPWarning,
    github_mcp_get_detail,
    github_mcp_search_activity,
)

_PLATFORM_IDENTITY_SCOPE = "platform"


def _warning_result(value: GitHubMCPWarning) -> dict[str, Any]:
    return {
        **value.to_dict(),
        "identity_scope": _PLATFORM_IDENTITY_SCOPE,
    }


async def github_search_activity(
    start_at: str,
    end_at: str,
    repositories: list[str] | None = None,
    event_types: list[GitHubActivityType] | None = None,
    limit: int = 30,
    timezone: str = "Asia/Shanghai",
    cursor: str | None = None,
) -> dict[str, Any]:
    """Search GitHub engineering activity visible to the platform account."""
    result = await github_mcp_search_activity(
        start_at=start_at,
        end_at=end_at,
        timezone=timezone,
        repositories=repositories,
        actor=None,
        event_types=event_types,
        limit=limit,
        cursor=cursor,
    )
    serialized = result.to_dict()
    events = serialized["events"]
    return {
        "ok": bool(result.events) or not result.warnings,
        "events": events,
        "count": len(events),
        "warnings": serialized["warnings"],
        "next_cursor": result.next_cursor,
        "identity_scope": result.identity_scope,
        "start_at": start_at,
        "end_at": end_at,
        "timezone": timezone,
    }


async def github_get_activity_detail(
    event_type: GitHubActivityType,
    repository: str,
    external_id: str,
    parent_external_id: str | None = None,
) -> dict[str, Any]:
    """Fetch one GitHub activity detail visible to the platform account."""
    result = await github_mcp_get_detail(
        event_type=event_type,
        repository=repository,
        external_id=external_id,
        parent_external_id=parent_external_id,
    )
    if isinstance(result, GitHubMCPWarning):
        return _warning_result(result)
    return {
        "ok": True,
        "event": result.to_dict(),
        "identity_scope": _PLATFORM_IDENTITY_SCOPE,
    }


GITHUB_ACTIVITY_TOOLS = [
    lc_tool(
        "github_search_activity",
        description=(
            "Search read-only GitHub engineering activity visible to the platform "
            "account through AgentArts MCP Gateway. Supports commits, pull "
            "requests, issues, reviews, comments, pagination, and repository "
            "filters. Use this for explicit GitHub MCP, platform activity, or "
            "time-range engineering activity requests. It does not require "
            "end-user GitHub OAuth. Activity may be authored by any account "
            "visible to the platform identity."
        ),
    )(github_search_activity),
    lc_tool(
        "github_get_activity_detail",
        description=(
            "Fetch detail for one read-only GitHub activity event visible to the "
            "platform account. For review or comment events, pass the parent PR "
            "or issue number as parent_external_id. Use this only after an MCP "
            "activity search result. It does not require end-user GitHub OAuth."
        ),
    )(github_get_activity_detail),
]
