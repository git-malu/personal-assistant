"""E2E contracts for unified Service structured logging."""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"


@pytest.mark.feature
class TestStructuredLoggingContract:
    def test_dev_and_prod_logging_configs_exist(self):
        assert (SERVICE_DIR / "config/logging.dev.yaml").is_file()
        assert (SERVICE_DIR / "config/logging.prod.yaml").is_file()

    def test_all_service_loggers_have_one_shared_configuration_owner(self):
        for name in ("logging.dev.yaml", "logging.prod.yaml"):
            config = yaml.safe_load(
                (SERVICE_DIR / f"config/{name}").read_text(encoding="utf-8")
            )

            assert config["disable_existing_loggers"] is False
            assert set(config["loggers"]) == {
                "app",
                "agentarts",
                "uvicorn",
                "uvicorn.error",
                "uvicorn.access",
            }
            assert config["loggers"]["agentarts"] == {
                "handlers": [],
                "level": "DEBUG",
                "propagate": True,
            }
            assert config["loggers"]["uvicorn.access"]["handlers"] == []

    def test_production_logging_uses_console_formatter(self):
        config = yaml.safe_load(
            (SERVICE_DIR / "config/logging.prod.yaml").read_text(encoding="utf-8")
        )

        assert set(config["formatters"]) == {"console"}
        assert config["formatters"]["console"]["()"] == (
            "app.logging_config.ConsoleFormatter"
        )
        assert config["handlers"]["console"]["formatter"] == "console"

    def test_container_uses_production_logging_config(self):
        dockerfile = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")

        assert "COPY personal-assistant-service/config/ ./config/" in dockerfile
        assert '"--log-config", "config/logging.prod.yaml"' in dockerfile

    def test_fastapi_registers_request_logging_middleware(self):
        from app.logging_config import RequestLoggingMiddleware
        from app.main import app

        assert any(
            middleware.cls is RequestLoggingMiddleware
            for middleware in app.user_middleware
        )
