"""Helpers for outbound AgentArts Identity integrations."""

from __future__ import annotations

from contextvars import ContextVar

from agentarts.sdk.runtime.context import AgentArtsRuntimeContext

from app.settings import get_settings

_GITHUB_AUTHORIZATION_URL: ContextVar[str | None] = ContextVar(
    "github_authorization_url",
    default=None,
)


def capture_github_authorization_url(url: str) -> None:
    """Store the latest GitHub authorization URL in this request context."""
    _GITHUB_AUTHORIZATION_URL.set(url)


def get_gitee_provider_name() -> str:
    """Return the configured Gitee OAuth provider name."""
    return get_settings().gitee_provider_name


def get_github_provider_name() -> str:
    """Return the configured GitHub OAuth provider name."""
    return get_settings().github_provider_name


def get_github_scopes_list() -> list[str]:
    """Return the configured GitHub OAuth2 scopes."""
    return get_settings().github_scope_list


def get_github_mcp_config() -> dict[str, str | float | bool]:
    """Return GitHub MCP Gateway data source settings."""
    settings = get_settings()
    return {
        "enabled": settings.github_mcp_enabled,
        "gateway_url": str(settings.github_mcp_gateway_url),
        "auth_mode": settings.github_mcp_auth_mode,
        "sts_provider_name": settings.github_mcp_sts_provider_name,
        "sts_agency_session_name": settings.github_mcp_sts_agency_session_name,
        "timeout_seconds": settings.github_mcp_timeout_seconds,
    }


def get_iam_users_readonly_config() -> dict[str, str]:
    """Return outbound IAM Users credential provider settings."""
    settings = get_settings()
    return {
        "provider_name": settings.iam_users_provider_name,
        "agency_session_name": settings.iam_users_agency_session_name,
        "region": settings.iam_users_region,
        "endpoint": settings.effective_iam_users_endpoint,
    }


def get_runtime_user_id() -> str | None:
    return AgentArtsRuntimeContext.get_user_id()


def get_runtime_session_id() -> str | None:
    return AgentArtsRuntimeContext.get_session_id()
