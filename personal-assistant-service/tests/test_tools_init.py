"""Unit tests for app.tools — build_tools() factory function.

Feature 10a: Outbound Email — verifies the factory correctly discovers
and collects tools from sub-modules.
"""

import inspect
import sys
from unittest.mock import patch

import pytest

from app.settings import Settings
from app.tools import build_tools


def _tool_name(tool) -> str:
    return tool.name if hasattr(tool, "name") else tool.__name__


def _tool_param_names(tool) -> list[str]:
    schema = getattr(tool, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None)
        if fields is None:
            fields = getattr(schema, "__fields__", {})
        return list(fields.keys())
    return list(inspect.signature(tool).parameters)


class TestBuildTools:
    """Tests for build_tools() factory function."""

    def test_build_tools_returns_list(self) -> None:
        """UT-TI-01: build_tools() returns a list."""
        result = build_tools()
        assert isinstance(result, list)

    def test_build_tools_includes_email_tools(self) -> None:
        """UT-TI-02: build_tools() includes all 5 email tools."""
        result = build_tools()

        result_names = [_tool_name(t) for t in result]
        expected = [
            "list_emails",
            "get_email",
            "search_emails",
            "send_email",
            "reply_to_email",
        ]
        for name in expected:
            assert name in result_names, (
                f"Expected {name} in build_tools() result, got {result_names}"
            )

    def test_build_tools_includes_github_tools(self) -> None:
        """UT-TI-05: build_tools() includes all GitHub tools."""
        result = build_tools()

        result_names = [_tool_name(t) for t in result]
        expected = [
            "github_list_repositories",
            "github_list_repo_contents",
            "github_get_file_content",
            "github_search_code",
            "github_star_repository",
        ]
        for name in expected:
            assert name in result_names, (
                f"Expected {name} in build_tools() result, got {result_names}"
            )

    @pytest.mark.parametrize(
        ("source_enabled", "facade_enabled", "registered"),
        [
            (False, False, False),
            (False, True, False),
            (True, False, False),
            (True, True, True),
        ],
    )
    def test_build_tools_github_activity_requires_both_switches(
        self,
        source_enabled: bool,
        facade_enabled: bool,
        registered: bool,
    ) -> None:
        settings = Settings(
            _env_file=None,
            github_mcp_enabled=source_enabled,
            github_activity_tools_enabled=facade_enabled,
        )

        with patch("app.tools.get_settings", return_value=settings):
            result = build_tools()

        result_names = {_tool_name(t) for t in result}
        agent_tool_names = {
            "github_search_activity",
            "github_get_activity_detail",
        }
        internal_source_names = {
            "github_mcp_resolve_identity",
            "github_mcp_list_repositories",
            "github_mcp_search_activity",
            "github_mcp_get_detail",
        }
        if registered:
            assert agent_tool_names.issubset(result_names)
        else:
            assert agent_tool_names.isdisjoint(result_names)
        assert internal_source_names.isdisjoint(result_names)

    def test_build_tools_includes_gitee_tools(self) -> None:
        """UT-TI-06: build_tools() includes Gitee tools."""
        result = build_tools()

        result_names = [_tool_name(t) for t in result]
        assert "gitee_list_repositories" in result_names

    def test_build_tools_includes_iam_tools(self) -> None:
        """UT-TI-07: build_tools() includes Huawei Cloud IAM tools."""
        result = build_tools()

        result_names = [_tool_name(t) for t in result]
        assert "huaweicloud_list_iam_users" in result_names

    def test_build_tools_graceful_import_error(self) -> None:
        """UT-TI-03: build_tools() does NOT raise when email_tools import fails."""
        # Ensure the module is in sys.modules before we set it to None
        _ = sys.modules.get("app.tools.email_tools")

        with patch.dict(sys.modules, {"app.tools.email_tools": None}):
            result = build_tools()

        # Should return a list (possibly empty) without raising
        assert isinstance(result, list)

    def test_build_tools_deduplicates(self) -> None:
        """UT-TI-04: each tool function appears only once in the result list."""
        result = build_tools()

        names = [_tool_name(t) for t in result]
        assert len(names) == len(set(names)), f"Duplicate tool names detected: {names}"

    def test_build_tools_oauth2_public_schemas_exclude_credentials(self) -> None:
        """UT-TI-08: registered OAuth2 tools do not expose injected credentials."""
        oauth2_tool_names = {
            "github_list_repositories",
            "github_list_repo_contents",
            "github_get_file_content",
            "github_search_code",
            "github_star_repository",
            "gitee_list_repositories",
            "list_emails",
            "get_email",
            "search_emails",
            "send_email",
            "reply_to_email",
            "list_calendar_events",
            "get_calendar_event",
            "search_calendar_events",
        }
        credential_params = {"access_token", "api_key"}

        tools = build_tools()
        registered = {_tool_name(t): t for t in tools}

        missing = oauth2_tool_names - set(registered)
        assert not missing, f"Missing expected OAuth2 tools: {sorted(missing)}"

        for name in oauth2_tool_names:
            params = set(_tool_param_names(registered[name]))
            assert params.isdisjoint(credential_params), (
                f"{name} exposes credential params: "
                f"{sorted(params & credential_params)}"
            )

    def test_build_tools_github_activity_schemas_exclude_credentials(self) -> None:
        """Feature 17 Agent tools do not expose credential parameters."""
        credential_params = {"access_token", "api_key", "authorization", "sts"}
        settings = Settings(
            _env_file=None,
            github_mcp_enabled=True,
            github_activity_tools_enabled=True,
        )

        with patch("app.tools.get_settings", return_value=settings):
            tools = build_tools()

        registered = {_tool_name(t): t for t in tools}
        for name in {
            "github_search_activity",
            "github_get_activity_detail",
        }:
            params = set(_tool_param_names(registered[name]))
            assert params.isdisjoint(credential_params), (
                f"{name} exposes credential params: "
                f"{sorted(params & credential_params)}"
            )
