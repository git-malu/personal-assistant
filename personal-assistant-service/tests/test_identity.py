"""Tests for AgentArts Identity adapter helpers."""

from __future__ import annotations

import pytest
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from starlette.datastructures import Headers

from app.identity import (
    get_github_oauth2_callback_url,
    get_runtime_session_id,
    get_runtime_user_id,
    request_runtime_context,
    runtime_context_scope,
)


@pytest.fixture(autouse=True)
def clear_agentarts_runtime_context():
    AgentArtsRuntimeContext.clear()
    yield
    AgentArtsRuntimeContext.clear()


def test_runtime_context_scope_sets_context_values():
    with runtime_context_scope(
        user_id="user-1",
        session_id="sess-1",
        workload_access_token="workload-token",
    ):
        assert get_runtime_user_id() == "user-1"
        assert get_runtime_session_id() == "sess-1"
        assert AgentArtsRuntimeContext.get_workload_access_token() == "workload-token"

    assert get_runtime_user_id() is None
    assert get_runtime_session_id() is None
    assert AgentArtsRuntimeContext.get_workload_access_token() is None


def test_workload_token_does_not_fall_back_to_user_token(monkeypatch):
    monkeypatch.delenv("AGENTARTS_WORKLOAD_ACCESS_TOKEN", raising=False)
    AgentArtsRuntimeContext.set_user_token("user-token")

    assert AgentArtsRuntimeContext.get_workload_access_token() is None


def test_request_runtime_context_loads_agentarts_headers_case_insensitively():
    headers = Headers(
        {
            "x-hw-agentgateway-user-id": "user-1",
            "X-HW-AGENTARTS-SESSION-ID": "sess-1",
            "x-hw-agentgateway-workload-access-token": "workload-token",
            "x-hw-agentarts-oauth2-custom-state": "state-1",
            "x-request-id": "req-1",
        }
    )

    with request_runtime_context(headers):
        assert get_runtime_user_id() == "user-1"
        assert get_runtime_session_id() == "sess-1"
        assert AgentArtsRuntimeContext.get_workload_access_token() == "workload-token"
        assert AgentArtsRuntimeContext.get_oauth2_custom_state() == "state-1"
        assert AgentArtsRuntimeContext.get_request_id() == "req-1"

    assert get_runtime_user_id() is None
    assert get_runtime_session_id() is None
    assert AgentArtsRuntimeContext.get_workload_access_token() is None


def test_get_github_oauth2_callback_url_reads_config(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTARTS_GITHUB_OAUTH2_CALLBACK_URL", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
identity:
  github:
    oauth2_callback_url: https://callback.example/from-config
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.identity._CONFIG_PATH", config_path)
    monkeypatch.setattr("app.identity._service_config", None)

    assert get_github_oauth2_callback_url() == "https://callback.example/from-config"


def test_get_github_oauth2_callback_url_prefers_env(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
identity:
  github:
    oauth2_callback_url: https://callback.example/from-config
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.identity._CONFIG_PATH", config_path)
    monkeypatch.setattr("app.identity._service_config", None)
    monkeypatch.setenv(
        "AGENTARTS_GITHUB_OAUTH2_CALLBACK_URL",
        "https://callback.example/from-env",
    )

    assert get_github_oauth2_callback_url() == "https://callback.example/from-env"
