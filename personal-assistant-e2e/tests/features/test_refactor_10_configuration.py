"""E2E contract tests for the unified Service configuration entry."""

from pathlib import Path

import pytest
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"


@pytest.mark.feature
class TestUnifiedConfigurationContract:
    def test_env_example_is_the_only_root_application_config_catalog(self):
        assert (SERVICE_DIR / ".env.example").is_file()
        assert not (SERVICE_DIR / "config.yaml").exists()

    def test_env_example_documents_canonical_llm_settings(self):
        content = (SERVICE_DIR / ".env.example").read_text(encoding="utf-8")

        for name in (
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_BASE_URL",
            "LLM_CREDENTIAL_PROVIDER",
            "LLM_TIMEOUT_SECONDS",
        ):
            assert name in content

    def test_deployment_config_contains_no_removed_runtime_variables(self):
        content = (SERVICE_DIR / ".agentarts_config.yaml").read_text(encoding="utf-8")

        for removed in (
            "MODEL_API_KEY",
            "MODEL_NAME",
            "MODEL_URL",
        ):
            assert removed not in content

    def test_fastapi_has_no_cors_middleware(self):
        from app.main import app

        assert all(
            middleware.cls is not CORSMiddleware for middleware in app.user_middleware
        )

    def test_legacy_variables_do_not_change_settings(self, monkeypatch):
        from app.settings import Settings

        monkeypatch.setenv("MODEL_NAME", "legacy-model")
        monkeypatch.setenv("MODEL_URL", "https://legacy.example.com")
        monkeypatch.setenv("MODEL_API_KEY", "legacy-secret")

        settings = Settings(_env_file=None)

        assert settings.llm_model == "deepseek-v4-pro"
        assert settings.llm_base_url is None
