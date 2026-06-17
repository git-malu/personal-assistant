"""Unit tests for app.llm_config."""

from unittest.mock import MagicMock, patch

import pytest

import app.llm_config


@pytest.fixture(autouse=True)
def reset_config_cache(monkeypatch):
    """Clear _config cache and non-secret overrides before each test."""
    app.llm_config._config = None
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_URL", raising=False)
    yield
    app.llm_config._config = None


def _mock_config(default: str = "deepseek") -> dict:
    return {
        "llm": {
            "default": default,
            "providers": {
                "deepseek": {
                    "credential_provider_name": "DEEPSEEK_API_KEY",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                },
            },
        },
    }


def test_get_model_fetches_api_key_from_agent_identity():
    """get_model() uses SDK-managed API key provider instead of env vars."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        patch(
            "app.llm_config._get_api_key_from_identity",
            return_value="identity-deepseek-key",
        ) as mock_get_key,
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        mock_model = MagicMock()
        mock_init.return_value = mock_model

        result = app.llm_config.get_model()

        assert result is mock_model
        mock_get_key.assert_called_once_with("DEEPSEEK_API_KEY")
        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="identity-deepseek-key",
        )


def test_get_model_with_explicit_provider():
    """get_model(provider='deepseek') uses that provider's Identity credential."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        patch(
            "app.llm_config._get_api_key_from_identity",
            return_value="identity-deepseek-key",
        ) as mock_get_key,
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model(provider="deepseek")

        mock_get_key.assert_called_once_with("DEEPSEEK_API_KEY")
        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="identity-deepseek-key",
        )


def test_validate_model_config_does_not_fetch_api_key():
    """Startup validation checks metadata only; no secret is fetched."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        patch("app.llm_config._get_api_key_from_identity") as mock_get_key,
    ):
        app.llm_config.validate_model_config()

        mock_get_key.assert_not_called()


def test_model_name_and_url_can_be_overridden_by_env(monkeypatch):
    """MODEL_NAME and MODEL_URL are non-secret runtime metadata overrides."""
    monkeypatch.setenv("MODEL_NAME", "deepseek-reasoner")
    monkeypatch.setenv("MODEL_URL", "https://custom.deepseek.example/v1")

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        patch(
            "app.llm_config._get_api_key_from_identity",
            return_value="identity-deepseek-key",
        ),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once_with(
            model="openai:deepseek-reasoner",
            base_url="https://custom.deepseek.example/v1",
            api_key="identity-deepseek-key",
        )


def test_model_overrides_are_optional(monkeypatch):
    """When unset, config.yaml values remain the defaults."""
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_URL", raising=False)

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        patch(
            "app.llm_config._get_api_key_from_identity",
            return_value="identity-deepseek-key",
        ),
        patch("app.llm_config.init_chat_model") as mock_init,
    ):
        app.llm_config.get_model()

        mock_init.assert_called_once_with(
            model="openai:deepseek-chat",
            base_url="https://api.deepseek.com",
            api_key="identity-deepseek-key",
        )


def test_missing_config_raises():
    """config.yaml is required; legacy MODEL_API_KEY fallback is removed."""
    with (
        patch("pathlib.Path.exists", return_value=False),
        pytest.raises(ValueError, match="config.yaml is required"),
    ):
        app.llm_config.get_model()


def test_unknown_provider_raises():
    """Unknown provider names include the available provider list."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        pytest.raises(ValueError, match="unknown"),
    ):
        app.llm_config.get_model(provider="unknown")


def test_missing_credential_provider_name_raises():
    """Provider config must include credential_provider_name."""
    cfg = _mock_config()
    del cfg["llm"]["providers"]["deepseek"]["credential_provider_name"]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=cfg),
        pytest.raises(ValueError, match="credential_provider_name"),
    ):
        app.llm_config.validate_model_config()


def test_identity_provider_returns_empty_key_raises():
    """An empty SDK-returned API key fails before init_chat_model."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("app.llm_config.yaml.safe_load", return_value=_mock_config()),
        patch("app.llm_config.require_api_key") as mock_decorator,
        pytest.raises(ValueError, match="empty API key"),
    ):
        mock_decorator.return_value = lambda fn: lambda *args, **kwargs: fn(api_key="")
        app.llm_config.get_model()


def test_config_cached():
    """Two metadata validations should only read config.yaml once."""
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "app.llm_config.yaml.safe_load",
            return_value=_mock_config(),
        ) as mock_load,
    ):
        app.llm_config.validate_model_config()
        app.llm_config.validate_model_config()

        assert mock_load.call_count == 1
