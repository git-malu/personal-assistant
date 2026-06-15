"""Unit tests for app.llm_config."""

from unittest.mock import MagicMock, patch

import pytest

import app.llm_config
from app.identity import MissingAgentIdentityTokenError, runtime_context_scope


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Clear _config cache before each test to ensure isolation."""
    app.llm_config._config = None
    yield
    app.llm_config._config = None


# Valid config tests


def test_get_model_with_valid_config_and_agent_identity():
    """get_model() returns BaseChatModel using Agent Identity API key provider."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config._resolve_llm_api_key", return_value="test-maas-key"),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        mock_model = MagicMock()
        mock_init.return_value = mock_model

        result = app.llm_config.get_model()

        assert result is mock_model
        mock_init.assert_called_once_with(
            model="openai:deepseek-v4-pro",
            base_url="https://api.modelarts-maas.com/openai/v1",
            api_key="test-maas-key",
        )


def test_resolve_llm_api_key_uses_sdk_client_when_model_is_built():
    """LLM API key lookup is scoped to the selected provider when needed."""

    identity_client = MagicMock()
    identity_client.get_resource_api_key.return_value = "model-api-key"

    with (
        patch(
            "app.llm_config.IdentityClient",
            return_value=identity_client,
        ),
        runtime_context_scope(workload_access_token="workload-token"),
    ):
        assert app.llm_config._resolve_llm_api_key("MAAS_API_KEY") == "model-api-key"

    identity_client.get_resource_api_key.assert_called_once_with(
        provider_name="MAAS_API_KEY",
        workload_access_token="workload-token",
    )


def test_get_model_prefers_env_api_key_for_local_debug(monkeypatch):
    """Local debug may use provider-name env vars before Agent Identity."""
    monkeypatch.setenv("MAAS_API_KEY", "local-debug-key")
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch(
            "app.llm_config._resolve_llm_api_key",
            return_value="identity-key",
        ) as mock_resolve,
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

    mock_resolve.assert_not_called()
    mock_init.assert_called_once_with(
        model="openai:deepseek-v4-pro",
        base_url="https://api.modelarts-maas.com/openai/v1",
        api_key="local-debug-key",
    )


def test_get_model_uses_default_provider():
    """get_model() without provider arg uses llm.default from config."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_provider": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config._resolve_llm_api_key", return_value="test-maas-key"),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once()
        kwargs = mock_init.call_args[1]
        assert kwargs["model"] == "openai:deepseek-v4-pro"


def test_get_model_with_explicit_provider():
    """get_model(provider="deepseek") uses deepseek provider config."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_provider": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config._resolve_llm_api_key", return_value="test-deepseek-key"),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model(provider="deepseek")

        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="test-deepseek-key",
        )


def test_get_model_missing_agent_identity_key_raises():
    """get_model() raises ValueError when Agent Identity cannot return a key."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch(
            "app.llm_config._resolve_llm_api_key",
            side_effect=MissingAgentIdentityTokenError("boom"),
        ),
        pytest.raises(ValueError, match="Agent Identity"),
    ):
        app.llm_config.get_model()


def test_get_model_unknown_provider_raises():
    """get_model(provider="unknown") raises ValueError with available providers."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config._resolve_llm_api_key", return_value="test-key"),
        pytest.raises(ValueError, match="unknown"),
    ):
        app.llm_config.get_model(provider="unknown")


# Missing config tests


def test_missing_config_raises_without_env_fallback():
    """When config.yaml is absent, fail closed instead of reading env API keys."""
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch("app.llm_config.init_chat_model") as mock_init,
        pytest.raises(ValueError, match="llm providers"),
    ):
        app.llm_config.get_model()

    mock_init.assert_not_called()


def test_config_with_no_llm_section_raises():
    """When config.yaml exists but has no llm section, fail closed."""
    mock_yaml = {"other_section": {}}
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config.init_chat_model") as mock_init,
        pytest.raises(ValueError, match="llm providers"),
    ):
        app.llm_config.get_model()

    mock_init.assert_not_called()


def test_config_with_llm_but_no_providers_raises():
    """When config.yaml has llm section but no providers, fail closed."""
    mock_yaml = {"llm": {"default": "maas"}}
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config.init_chat_model") as mock_init,
        pytest.raises(ValueError, match="llm providers"),
    ):
        app.llm_config.get_model()

    mock_init.assert_not_called()


# Caching tests


def test_config_cached():
    """Two calls to get_model() should only call yaml.safe_load once."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml) as mock_load,
        patch("app.llm_config._resolve_llm_api_key", return_value="test-key"),
        patch("app.llm_config.init_chat_model"),
    ):
        app.llm_config.get_model()
        app.llm_config.get_model()

        # yaml.safe_load should only be called once due to caching
        assert mock_load.call_count == 1


# Multi-provider failure tests


def test_default_provider_missing_key_does_not_fallback_to_alternative_provider():
    """When the selected default provider key is missing, fail closed."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_provider": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch(
            "app.llm_config._resolve_llm_api_key",
            side_effect=MissingAgentIdentityTokenError("maas unavailable"),
        ),
        patch("app.llm_config.init_chat_model") as mock_init,
        pytest.raises(ValueError, match="Agent Identity"),
    ):
        app.llm_config.get_model()

    mock_init.assert_not_called()


def test_explicit_provider_missing_key_does_not_fallback():
    """Explicit provider key missing; do not fall back to another provider."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_provider": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch(
            "app.llm_config._resolve_llm_api_key",
            side_effect=MissingAgentIdentityTokenError("maas unavailable"),
        ),
        patch("app.llm_config.init_chat_model") as mock_init,
        pytest.raises(ValueError, match="Agent Identity"),
    ):
        app.llm_config.get_model(provider="maas")

    mock_init.assert_not_called()


def test_selected_provider_failure_raises_agent_identity_error():
    """Selected provider failure raises the unified Agent Identity error."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_provider": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch(
            "app.llm_config._resolve_llm_api_key",
            side_effect=MissingAgentIdentityTokenError("boom"),
        ) as mock_get_key,
        pytest.raises(ValueError, match="Agent Identity"),
    ):
        app.llm_config.get_model()
    mock_get_key.assert_called_once_with("MAAS_API_KEY")


def test_default_provider_works_no_fallback():
    """When default provider's Agent Identity key works, use it normally."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_provider": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_provider": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch("app.llm_config._resolve_llm_api_key", return_value="test-maas-key"),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        mock_model = MagicMock()
        mock_init.return_value = mock_model

        result = app.llm_config.get_model()

        assert result is mock_model
        mock_init.assert_called_once_with(
            model="openai:deepseek-v4-pro",
            base_url="https://api.modelarts-maas.com/openai/v1",
            api_key="test-maas-key",
        )
