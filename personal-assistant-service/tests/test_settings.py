"""Tests for the single Runtime Settings entry point."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch):
    monkeypatch.delenv("AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME", raising=False)
    monkeypatch.delenv("OAUTH2_CALENDAR_CALLBACK_URL", raising=False)
    monkeypatch.delenv("OAUTH2_CALLBACK_BFF_SECRET", raising=False)
    monkeypatch.delenv("GITHUB_MCP_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_MCP_GATEWAY_URL", raising=False)
    monkeypatch.delenv("GITHUB_MCP_AUTH_MODE", raising=False)
    monkeypatch.delenv("GITHUB_MCP_STS_PROVIDER_NAME", raising=False)
    monkeypatch.delenv("GITHUB_MCP_STS_AGENCY_SESSION_NAME", raising=False)
    monkeypatch.delenv("GITHUB_MCP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("GITHUB_ACTIVITY_TOOLS_ENABLED", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.log_level == "INFO"
    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-v4-pro"
    assert settings.llm_agent_bundle_ttl_seconds == 300.0
    assert settings.postgres_dsn is None
    assert settings.sqlite_db_path is None
    assert settings.agent_identity_local_jwt_workload_name == "pa-local-jwt-workload"
    assert str(settings.oauth2_calendar_callback_url).rstrip("/") == (
        "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar"
    )
    assert str(settings.graph_base_url).rstrip("/") == (
        "https://graph.microsoft.com/v1.0/me"
    )
    assert settings.github_mcp_enabled is True
    assert str(settings.github_mcp_gateway_url).rstrip("/") == (
        "https://gateway-github-mcp-defaultgw-ha3wenzqga.cn-southwest-2."
        "huaweicloud-agentarts.com/mcp"
    )
    assert settings.github_mcp_auth_mode == "iam"
    assert settings.github_mcp_sts_provider_name == "github-mcp-gateway"
    assert (
        settings.github_mcp_sts_agency_session_name == "personal-assistant-github-mcp"
    )
    assert settings.github_mcp_timeout_seconds == 30.0
    assert settings.github_activity_tools_enabled is True


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.llm_model == "deepseek-reasoner"


def test_dotenv_is_supported_without_mutating_os_environ(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=dotenv-model\n", encoding="utf-8")
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.llm_model == "dotenv-model"
    assert "LLM_MODEL" not in __import__("os").environ


def test_environment_takes_priority_over_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=dotenv-model\n", encoding="utf-8")
    monkeypatch.setenv("LLM_MODEL", "runtime-model")

    settings = Settings(_env_file=env_file)

    assert settings.llm_model == "runtime-model"


def test_persistence_backends_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings(
            _env_file=None,
            postgres_dsn="postgresql://localhost/test",
            sqlite_db_path=Path("/tmp/checkpoints.db"),
        )


def test_invalid_log_level_fails_fast():
    with pytest.raises(ValidationError, match="log_level"):
        Settings(_env_file=None, log_level="TRACE")


def test_agent_bundle_ttl_can_be_overridden(monkeypatch):
    monkeypatch.setenv("LLM_AGENT_BUNDLE_TTL_SECONDS", "120")

    settings = Settings(_env_file=None)

    assert settings.llm_agent_bundle_ttl_seconds == 120.0


def test_graph_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv(
        "GRAPH_BASE_URL",
        "https://graph.microsoft.com/v1.0/users/current",
    )

    settings = Settings(_env_file=None)

    assert str(settings.graph_base_url).rstrip("/") == (
        "https://graph.microsoft.com/v1.0/users/current"
    )


def test_github_mcp_settings_can_be_overridden(monkeypatch):
    monkeypatch.setenv("GITHUB_MCP_ENABLED", "true")
    monkeypatch.setenv("GITHUB_MCP_GATEWAY_URL", "https://example.com/mcp")
    monkeypatch.setenv("GITHUB_MCP_STS_PROVIDER_NAME", "github-mcp-provider")
    monkeypatch.setenv(
        "GITHUB_MCP_STS_AGENCY_SESSION_NAME",
        "github-mcp-session",
    )
    monkeypatch.setenv("GITHUB_MCP_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("GITHUB_ACTIVITY_TOOLS_ENABLED", "false")

    settings = Settings(_env_file=None)

    assert settings.github_mcp_enabled is True
    assert str(settings.github_mcp_gateway_url).rstrip("/") == "https://example.com/mcp"
    assert settings.github_mcp_sts_provider_name == "github-mcp-provider"
    assert settings.github_mcp_sts_agency_session_name == "github-mcp-session"
    assert settings.github_mcp_timeout_seconds == 12.0
    assert settings.github_activity_tools_enabled is False


def test_calendar_callback_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv(
        "OAUTH2_CALENDAR_CALLBACK_URL",
        "http://localhost:5173/auth/callback/m365-calendar",
    )

    settings = Settings(_env_file=None)

    assert str(settings.oauth2_calendar_callback_url).rstrip("/") == (
        "http://localhost:5173/auth/callback/m365-calendar"
    )


def test_local_jwt_workload_name_can_be_overridden(monkeypatch):
    monkeypatch.setenv(
        "AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME",
        "custom-local-jwt-workload",
    )

    settings = Settings(_env_file=None)

    assert settings.agent_identity_local_jwt_workload_name == (
        "custom-local-jwt-workload"
    )


@pytest.mark.parametrize("ttl", [0, -1])
def test_agent_bundle_ttl_must_be_positive(ttl):
    with pytest.raises(ValidationError, match="llm_agent_bundle_ttl_seconds"):
        Settings(_env_file=None, llm_agent_bundle_ttl_seconds=ttl)


def test_empty_optional_values_are_unset():
    settings = Settings(
        _env_file=None,
        llm_base_url="",
        postgres_dsn="",
        sqlite_db_path="",
        iam_users_endpoint="",
        oauth2_calendar_callback_url="",
        oauth2_callback_bff_secret="",
    )

    assert settings.llm_base_url is None
    assert settings.postgres_dsn is None
    assert settings.sqlite_db_path is None
    assert settings.iam_users_endpoint is None
    assert settings.oauth2_calendar_callback_url is None
    assert settings.oauth2_callback_bff_secret is None


def test_settings_are_frozen():
    settings = Settings(_env_file=None)

    with pytest.raises(ValidationError):
        settings.llm_model = "changed"
