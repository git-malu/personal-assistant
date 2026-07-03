"""Tests for AgentArts Workload Access Token helpers."""

from unittest.mock import MagicMock, patch

from app.agentarts_wat import (
    create_jwt_mode_workload_access_token,
    get_workload_name,
)


def test_get_workload_name_reads_default_agent_base_name(tmp_path):
    config = tmp_path / ".agentarts_config.yaml"
    config.write_text(
        """
default_agent: personal-assistant
agents:
  personal-assistant:
    base:
      name: personal-assistant
""",
        encoding="utf-8",
    )

    assert get_workload_name(config) == "personal-assistant"


def test_create_jwt_mode_workload_access_token_uses_user_token():
    client = MagicMock()
    client.create_workload_access_token.return_value = "jwt-mode-wat"

    token = create_jwt_mode_workload_access_token(
        " user-token ",
        client=client,
        workload_name="personal-assistant",
    )

    assert token == "jwt-mode-wat"
    client.create_workload_access_token.assert_called_once_with(
        "personal-assistant",
        user_token="user-token",
    )


def test_create_jwt_mode_workload_access_token_builds_identity_client():
    client = MagicMock()
    client.create_workload_access_token.return_value = "jwt-mode-wat"

    with (
        patch("app.agentarts_wat.get_region", return_value="cn-southwest-2"),
        patch("app.agentarts_wat.IdentityClient", return_value=client) as identity,
        patch("app.agentarts_wat.get_workload_name", return_value="personal-assistant"),
    ):
        token = create_jwt_mode_workload_access_token("user-token")

    assert token == "jwt-mode-wat"
    identity.assert_called_once_with(region="cn-southwest-2")
