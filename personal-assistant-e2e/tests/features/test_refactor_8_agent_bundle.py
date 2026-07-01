"""E2E contracts for the renewable process-scoped Agent Bundle."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"


@pytest.mark.feature
class TestAgentBundleContract:
    def test_agent_bundle_ttl_is_discoverable_and_defaulted(self):
        env_catalog = (SERVICE_DIR / ".env.example").read_text(encoding="utf-8")
        settings_source = (SERVICE_DIR / "app/settings.py").read_text(encoding="utf-8")

        assert "LLM_AGENT_BUNDLE_TTL_SECONDS" in env_catalog
        assert "llm_agent_bundle_ttl_seconds" in settings_source

    def test_request_paths_use_shared_async_agent_entry(self):
        handler_source = (SERVICE_DIR / "app/agent_handler.py").read_text(
            encoding="utf-8"
        )
        playground_source = (SERVICE_DIR / "app/playground.py").read_text(
            encoding="utf-8"
        )

        assert "async def handle(" in handler_source
        assert "async def handle_stream(" in handler_source
        assert handler_source.count("agent = await self.get_agent()") >= 2
        assert "await handler.get_agent()" in playground_source
        assert "def create_agent(" not in handler_source

    def test_llm_api_key_is_not_written_to_process_environment(self):
        llm_source = (SERVICE_DIR / "app/llm_config.py").read_text(encoding="utf-8")
        handler_source = (SERVICE_DIR / "app/agent_handler.py").read_text(
            encoding="utf-8"
        )

        assert "os.environ" not in llm_source
        assert "os.environ" not in handler_source
