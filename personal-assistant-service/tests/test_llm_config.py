"""Unit tests for app.llm_config."""

import os
from unittest.mock import MagicMock, patch

import pytest

import app.llm_config


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Clear _config cache before each test to ensure isolation."""
    app.llm_config._config = None
    yield
    app.llm_config._config = None


# ── Tests with valid config.yaml ──────────────────────────────────────────


def test_get_model_with_valid_config_and_env():
    """get_model() returns BaseChatModel when config.yaml exists and env is set."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"MAAS_API_KEY": "test-maas-key"}),
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


def test_get_model_uses_default_provider():
    """get_model() without provider arg uses llm.default from config."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"MAAS_API_KEY": "test-maas-key"}),
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
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek-key"}),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model(provider="deepseek")

        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="test-deepseek-key",
        )


def test_get_model_missing_api_key_raises():
    """get_model() raises ValueError when the required api_key env var is missing."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ValueError, match="MAAS_API_KEY"),
    ):
        app.llm_config.get_model()


def test_get_model_unknown_provider_raises():
    """get_model(provider="unknown") raises ValueError with available providers."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"MAAS_API_KEY": "test-key"}),
        pytest.raises(ValueError, match="unknown"),
    ):
        app.llm_config.get_model(provider="unknown")


# ── Fallback tests (config.yaml absent) ──────────────────────────────────


def test_fallback_when_config_absent():
    """When config.yaml is absent, fallback to MODEL_URL/MODEL_API_KEY/MODEL_NAME."""
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch.dict(
            os.environ,
            {
                "MODEL_API_KEY": "test-fallback-key",
                "MODEL_NAME": "custom-model",
                "MODEL_URL": "https://custom.api.com/v1",
            },
        ),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once_with(
            model="openai:custom-model",
            base_url="https://custom.api.com/v1",
            api_key="test-fallback-key",
        )


def test_fallback_uses_defaults():
    """When MODEL_NAME and MODEL_URL are not set, uses built-in defaults."""
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch.dict(os.environ, {"MODEL_API_KEY": "test-key"}),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once_with(
            model="openai:deepseek-v4-pro",
            base_url="https://api.modelarts-maas.com/openai/v1",
            api_key="test-key",
        )


def test_fallback_missing_api_key_raises():
    """When config.yaml absent and MODEL_API_KEY not set, raises ValueError."""
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ValueError, match="MODEL_API_KEY"),
    ):
        app.llm_config.get_model()


# ── Caching ───────────────────────────────────────────────────────────────


def test_config_cached():
    """Two calls to get_model() should only call yaml.safe_load once."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml) as mock_load,
        patch.dict(os.environ, {"MAAS_API_KEY": "test-key"}),
        patch("app.llm_config.init_chat_model"),
    ):
        app.llm_config.get_model()
        app.llm_config.get_model()

        # yaml.safe_load should only be called once due to caching
        assert mock_load.call_count == 1


# ── Edge cases ───────────────────────────────────────────────────────────


def test_config_with_no_llm_section_falls_back():
    """When config.yaml exists but has no llm section, use fallback."""
    mock_yaml = {"other_section": {}}
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"MODEL_API_KEY": "test-key"}),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args[1]
        # Model name uses default since MODEL_NAME is not set
        assert "openai:deepseek-v4-pro" in str(call_kwargs["model"])


def test_config_with_llm_but_no_providers_falls_back():
    """When config.yaml has llm section but no providers, use fallback."""
    mock_yaml = {"llm": {"default": "maas"}}
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"MODEL_API_KEY": "test-key"}),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once()


# ── Fallback to alternative provider (multi-provider) ────────────────────


def test_fallback_to_alternative_provider_when_default_key_missing():
    """When default key is missing but alt has one, falls back and warns."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek-key"}, clear=True),
        patch("app.llm_config.init_chat_model") as mock_init,
        patch.object(app.llm_config.logger, "warning") as mock_warning,
    ):
        mock_model = MagicMock()
        mock_init.return_value = mock_model

        result = app.llm_config.get_model()

        assert result is mock_model
        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="test-deepseek-key",
        )
        # Verify warnings were logged (scanning + fallback)
        assert mock_warning.call_count >= 2
        # The fallback warning should mention "default" (None uses default provider)
        fallback_calls = [
            c for c in mock_warning.call_args_list
            if "Auto-falling back" in c.args[0]
        ]
        assert len(fallback_calls) == 1
        assert "To use the default provider" in fallback_calls[0].args[0]


def test_explicit_provider_with_missing_key_falls_back():
    """Explicit provider key missing, alt key set → fallback says 'requested'."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek-key"}, clear=True),
        patch("app.llm_config.init_chat_model") as mock_init,
        patch.object(app.llm_config.logger, "warning") as mock_warning,
    ):
        mock_model = MagicMock()
        mock_init.return_value = mock_model

        result = app.llm_config.get_model(provider="maas")

        assert result is mock_model
        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="test-deepseek-key",
        )
        # The fallback warning should mention "requested" (not "default")
        fallback_calls = [
            c for c in mock_warning.call_args_list
            if "Auto-falling back" in c.args[0]
        ]
        assert len(fallback_calls) == 1
        assert "To use the requested provider" in fallback_calls[0].args[0]


def test_all_providers_fail_raises_unified_error():
    """2+ providers configured, none have keys → raises unified Chinese error."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {}, clear=True),
        pytest.raises(ValueError, match="没有可用的 LLM provider"),
    ):
        app.llm_config.get_model()


def test_default_provider_works_no_fallback():
    """When default provider's key IS set, normal behavior: no fallback, no warnings."""
    mock_yaml = {
        "llm": {
            "default": "maas",
            "providers": {
                "maas": {
                    "api_key_env": "MAAS_API_KEY",
                    "model": "deepseek-v4-pro",
                    "base_url": "https://api.modelarts-maas.com/openai/v1",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=mock_yaml),
        patch.dict(os.environ, {"MAAS_API_KEY": "test-maas-key"}, clear=True),
        patch("app.llm_config.init_chat_model") as mock_init,
        patch.object(app.llm_config.logger, "warning") as mock_warning,
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
        # No fallback-related warnings should be logged when default works
        mock_warning.assert_not_called()
