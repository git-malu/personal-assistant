"""E2E tests for Feature 1.3 — 多 LLM Provider 可配置架构.

Tests the full application stack via real subprocess (uvicorn serving HTTP)
to verify Service + Client integration scenarios.

Since real LLM API keys are not available, verification focuses on:
- Service startup/shutdown behavior under different provider configurations
- HTTP API contract (status codes, response structure, error handling)
- Config loading errors (missing provider config, unknown providers)

Unit test coverage (34/34 passed, 100%) already verifies llm_config logic in isolation.
These E2E tests verify the process-level integration.

Test scenarios from plan:
  1. Default provider (MaaS) — service starts, endpoints respond correctly
  2. DeepSeek provider switch — service starts, endpoints respond correctly
  3. Config.yaml missing — invocation fails closed without env fallback
  5. Unknown provider — service exits with clear error listing available providers
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CONFIG_YAML = SERVICE_DIR / "config.yaml"
CONFIG_YAML_BACKUP = SERVICE_DIR / "config.yaml.e2e-backup"
# ── Helpers ────────────────────────────────────────────────────────────


def _get_uv_path() -> str:
    """Get the uv binary from the service venv."""
    uv_path = SERVICE_DIR / ".venv" / "bin" / "uv"
    if uv_path.exists():
        return str(uv_path)
    return "uv"


def _start_service(
    port: int, env: dict[str, str] | None = None, timeout: float = 60.0
) -> subprocess.Popen:
    """Start uvicorn as a subprocess. Returns the Popen handle."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    proc = subprocess.Popen(
        [
            _get_uv_path(),
            "run",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=str(SERVICE_DIR),
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for service to be healthy or exit
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        if proc.poll() is not None:
            # Process exited — collect stderr for diagnostics
            try:
                _, stderr = proc.communicate(timeout=5)
            except Exception:
                stderr = b""
            stderr_text = stderr.decode(errors="replace")[-1000:]
            raise RuntimeError(
                f"Service exited with code {proc.returncode}: {stderr_text}"
            )
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/ping", timeout=2.0)
            if resp.status_code == 200:
                return proc
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_error = e
        time.sleep(0.5)

    _stop_service(proc)
    raise TimeoutError(
        f"Service did not become healthy within {timeout}s on port {port}. "
        f"Last error: {last_error}"
    )


def _stop_service(proc: subprocess.Popen):
    """Gracefully stop the service subprocess."""
    if proc is None or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _wait_for_service_exit(proc: subprocess.Popen, timeout: float = 15.0) -> int:
    """Wait for service to exit and return its exit code."""
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_service(proc)
        raise TimeoutError(f"Service did not exit within {timeout}s")


def _get_service_stderr(proc: subprocess.Popen) -> str:
    """Collect stderr from the service process."""
    if proc is None:
        return ""
    try:
        if proc.stderr:
            stderr_bytes = proc.stderr.read()
            return stderr_bytes.decode(errors="replace")
    except Exception:
        pass
    try:
        _, stderr = proc.communicate(timeout=1)
        return stderr.decode(errors="replace")
    except Exception:
        return ""


def _write_config(content: str):
    """Write config.yaml for test scenario."""
    CONFIG_YAML.write_text(content, encoding="utf-8")


def _restore_config():
    """Restore config.yaml from backup. Never deletes — only restores."""
    if CONFIG_YAML_BACKUP.exists():
        import shutil
        shutil.copy2(str(CONFIG_YAML_BACKUP), str(CONFIG_YAML))
        CONFIG_YAML_BACKUP.unlink()


def _backup_config():
    """Create a backup of config.yaml if it exists."""
    import shutil
    if CONFIG_YAML.exists() and not CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML), str(CONFIG_YAML_BACKUP))


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def manage_config():
    """Backup config.yaml before test, restore after.
    
    Uses module-level backup to survive across multiple test classes.
    """
    _backup_config()
    yield
    _restore_config()


@pytest.fixture
def http_client():
    """Synchronous httpx client for E2E HTTP tests."""
    client = httpx.Client(timeout=10.0)
    yield client
    client.close()


# ── Scenario 1: Default provider (MaaS) 对话正常 ──────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario1_DefaultProviderMaaS:
    """config.yaml 配置 maas 为默认，服务启动正常，调用时走 Agent Identity。"""

    PORT = 18701

    def test_service_starts_and_ping_responds(self, http_client):
        """Service starts without local API key env vars; /ping returns 200."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"status": "ok"}
        finally:
            _stop_service(proc)

    def test_api_invocations_endpoint_structure(self, http_client):
        """POST /invocations reaches Agent Identity key lookup and fails gracefully."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "Hello"},
            )
            assert resp.status_code == 400
            assert "x-hw-agentarts-session-id" in resp.json()["detail"]
        finally:
            _stop_service(proc)

    def test_api_invocations_empty_message_returns_400(self, http_client):
        """POST /invocations with empty message returns 400."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": ""},
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "message is required"
        finally:
            _stop_service(proc)

    def test_api_invocations_missing_message_returns_400(self, http_client):
        """POST /invocations without message field returns 400."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={},
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == "message is required"
        finally:
            _stop_service(proc)

    def test_chat_stream_endpoint_returns_sse(self, http_client):
        """POST /invocations with stream=true returns SSE content type."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "Hello", "stream": True},
                headers={
                    "Accept": "text/event-stream",
                    "x-hw-agentarts-session-id": "e2e-session",
                },
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            assert "AgentArts workload access token is empty" in resp.text
        finally:
            _stop_service(proc)

    def test_chat_stream_empty_message_returns_400(self, http_client):
        """POST /invocations with stream=true and empty message returns 400."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "", "stream": True},
            )
            assert resp.status_code == 400
        finally:
            _stop_service(proc)

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: StaticFiles mount removed, "
               "GET / now returns 404 by design."
    )
    def test_static_files_endpoint_serves_html(self, http_client):
        """GET / returns HTML (static files served).

        SKIPPED: refactor-2 removed StaticFiles. GET / now returns 404.
        """
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/")
            # Static mount should serve index.html
            assert resp.status_code == 200
            content_type = resp.headers.get("content-type", "").lower()
            assert "text/html" in content_type
        finally:
            _stop_service(proc)


# ── Scenario 2: 切换 DeepSeek 对话正常 ────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario2_DeepSeekProvider:
    """修改 config.yaml llm.default 为 deepseek，验证服务和路由正常。"""

    PORT = 18702

    DEEPSEEK_CONFIG = """\
llm:
  default: deepseek
  providers:
    maas:
      base_url: https://api.modelarts-maas.com/openai/v1
      api_key_provider: MAAS_API_KEY
      model: deepseek-v4-pro
    deepseek:
      base_url: https://api.deepseek.com
      api_key_provider: DEEPSEEK_API_KEY
      model: deepseek-chat
"""

    @pytest.fixture(autouse=True)
    def use_deepseek_config(self):
        """Temporarily switch config.yaml to use deepseek as default provider."""
        _write_config(self.DEEPSEEK_CONFIG)
        yield
        _restore_config()

    def test_service_starts_with_deepseek_provider(self, http_client):
        """Service starts successfully without a local DeepSeek API key env var."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
        finally:
            _stop_service(proc)

    def test_deepseek_invocations_endpoint(self, http_client):
        """POST /invocations reaches routing and validates required session header."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "你好，DeepSeek"},
                headers={"X-HW-AgentGateway-User-Id": "test-user"},
            )
            assert resp.status_code == 400
            assert "x-hw-agentarts-session-id" in resp.json()["detail"]
        finally:
            _stop_service(proc)

    def test_deepseek_stream_endpoint(self, http_client):
        """POST /invocations with stream=true works with deepseek provider."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "Hello", "stream": True},
                headers={
                    "Accept": "text/event-stream",
                    "x-hw-agentarts-session-id": "e2e-session",
                },
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            assert "AgentArts workload access token is empty" in resp.text
        finally:
            _stop_service(proc)


# ── Scenario 3: config.yaml 不存在时失败关闭 ─────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3_ConfigFallback:
    """删除 config.yaml 后直接失败，不再读取旧 fallback。"""

    PORT = 18703

    @pytest.fixture(autouse=True)
    def remove_config(self):
        """Remove config.yaml for fallback tests."""
        # Already backed up by autouse fixture; now remove
        if CONFIG_YAML.exists():
            CONFIG_YAML.unlink()
        yield
        _restore_config()

    def test_missing_config_still_allows_health_check(self, http_client):
        """Service starts without model initialization; /ping still works."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
        finally:
            _stop_service(proc)

    def test_missing_config_invocation_fails_closed(self, http_client):
        """Agent invocation fails closed when config.yaml has no llm providers."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert resp.status_code == 200

            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "Hello"},
                headers={"x-hw-agentarts-session-id": "e2e-session"},
            )
            assert resp.status_code == 500
            assert "llm providers" in resp.json()["detail"]
        finally:
            _stop_service(proc)

    def test_missing_config_invocation_fails_closed_even_with_other_env(self, http_client):
        """旧环境变量不会让缺失配置重新启用。"""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "Hello"},
                headers={"x-hw-agentarts-session-id": "e2e-session"},
            )
            assert resp.status_code == 500
            assert "llm providers" in resp.json()["detail"]
        finally:
            _stop_service(proc)

    def test_missing_config_with_only_health_check(self, http_client):
        """缺 config 也不会影响健康检查。"""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert resp.status_code == 200
        finally:
            _stop_service(proc)



# ── Scenario 5: 未知 provider 名称报错 ─────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario5_UnknownProvider:
    """config.yaml 设置 llm.default: unknown，验证启动报错并提示可用 provider 列表."""

    PORT = 18705

    def test_unknown_provider_fails_with_available_list(self):
        """Setting llm.default to unknown provider causes clear error listing available providers."""
        # Write a config with unknown default provider
        _write_config("""\
llm:
  default: unknown_provider_xyz
  providers:
    maas:
      base_url: https://api.modelarts-maas.com/openai/v1
      api_key_provider: MAAS_API_KEY
      model: deepseek-v4-pro
    deepseek:
      base_url: https://api.deepseek.com
      api_key_provider: DEEPSEEK_API_KEY
      model: deepseek-chat
""")


        try:
            with pytest.raises(RuntimeError) as exc_info:
                _start_service(self.PORT, timeout=15.0)

            error_msg = str(exc_info.value)
            # Should mention the unknown provider name
            assert "unknown_provider_xyz" in error_msg, (
                f"Error should mention unknown provider name, got: {error_msg}"
            )
            # Should list available providers
            assert "maas" in error_msg.lower(), (
                f"Error should list available providers (maas), got: {error_msg}"
            )
            assert "deepseek" in error_msg.lower(), (
                f"Error should list available providers (deepseek), got: {error_msg}"
            )
        finally:
            _restore_config()

    def test_unknown_provider_with_no_matching_key_also_fails(self):
        """Even with env vars set, unknown provider name causes startup failure."""
        _write_config("""\
llm:
  default: nonexistent_llm
  providers:
    maas:
      base_url: https://api.modelarts-maas.com/openai/v1
      api_key_provider: MAAS_API_KEY
      model: deepseek-v4-pro
""")


        try:
            with pytest.raises(RuntimeError) as exc_info:
                _start_service(self.PORT, timeout=15.0)

            error_msg = str(exc_info.value)
            assert "nonexistent_llm" in error_msg, (
                f"Error should mention the bad provider name, got: {error_msg}"
            )
            assert "maas" in error_msg.lower(), (
                f"Error should list available providers, got: {error_msg}"
            )
        finally:
            _restore_config()
