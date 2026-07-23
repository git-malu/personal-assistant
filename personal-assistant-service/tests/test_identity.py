"""Tests for outbound identity Settings adapters."""

from unittest.mock import patch

from app import identity
from app.settings import Settings


def test_get_gitee_provider_name_defaults():
    settings = Settings(_env_file=None)
    with patch("app.identity.get_settings", return_value=settings):
        assert identity.get_gitee_provider_name() == "gitee-provider"


def test_get_gitee_provider_name_reads_settings():
    settings = Settings(
        _env_file=None,
        gitee_provider_name="custom-gitee-provider",
    )
    with patch("app.identity.get_settings", return_value=settings):
        assert identity.get_gitee_provider_name() == "custom-gitee-provider"


def test_get_iam_users_readonly_config_defaults():
    settings = Settings(_env_file=None)
    with patch("app.identity.get_settings", return_value=settings):
        assert identity.get_iam_users_readonly_config() == {
            "provider_name": "iam-users-readonly",
            "agency_session_name": "personal-assistant-iam-users-readonly",
            "region": "cn-southwest-2",
            "endpoint": "https://iam.cn-southwest-2.myhuaweicloud.com",
        }


def test_get_github_mcp_config_defaults():
    settings = Settings(_env_file=None, github_mcp_enabled=False)
    with patch("app.identity.get_settings", return_value=settings):
        assert identity.get_github_mcp_config() == {
            "enabled": False,
            "gateway_url": (
                "https://gateway-github-mcp-defaultgw-ha3wenzqga.cn-southwest-2."
                "huaweicloud-agentarts.com/mcp"
            ),
            "auth_mode": "iam",
            "sts_provider_name": "github-mcp-gateway",
            "sts_agency_session_name": "personal-assistant-github-mcp",
            "timeout_seconds": 30.0,
        }


def test_get_iam_users_readonly_config_reads_settings():
    settings = Settings(
        _env_file=None,
        iam_users_provider_name="custom-iam-provider",
        iam_users_agency_session_name="custom-session",
        iam_users_region="cn-north-4",
        iam_users_endpoint="https://custom-iam.example.com",
    )
    with patch("app.identity.get_settings", return_value=settings):
        assert identity.get_iam_users_readonly_config() == {
            "provider_name": "custom-iam-provider",
            "agency_session_name": "custom-session",
            "region": "cn-north-4",
            "endpoint": "https://custom-iam.example.com",
        }
