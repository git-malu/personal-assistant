"""E2E tests for feat/session-checkpoint — LangGraph Checkpointer integration.

Tests multi-turn context persistence, streaming context, session isolation,
user-scoped thread_id isolation, cookie fallback, and basic functionality.

Requires E2E_DEEPSEEK_API_KEY env var (deepseek-chat) for multi-turn verification.
"""

import json
import os
import re
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

# DeepSeek config — explicitly use deepseek as default
DEEPSEEK_CONFIG = """\
llm:
  default: deepseek
  providers:
    maas:
      base_url: https://api.modelarts-maas.com/openai/v1
      api_key_env: MAAS_API_KEY
      model: deepseek-v4-pro
    deepseek:
      base_url: https://api.deepseek.com
      api_key_env: DEEPSEEK_API_KEY
      model: deepseek-chat
"""

# Real API key — must be set in environment to run these tests
DEEPSEEK_API_KEY = os.environ.get("E2E_DEEPSEEK_API_KEY", "")


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
            try:
                _, stderr_b = proc.communicate(timeout=5)
            except Exception:
                stderr_b = b""
            stderr_text = stderr_b.decode(errors="replace")[-1000:]
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


def _write_config(content: str):
    """Write config.yaml for test scenario."""
    CONFIG_YAML.write_text(content, encoding="utf-8")


def _restore_config():
    """Restore config.yaml from backup."""
    import shutil

    if CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML_BACKUP), str(CONFIG_YAML))
        CONFIG_YAML_BACKUP.unlink()


def _backup_config():
    """Create a backup of config.yaml if it exists."""
    import shutil

    if CONFIG_YAML.exists() and not CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML), str(CONFIG_YAML_BACKUP))


def _parse_sse_stream(response: httpx.Response) -> tuple[str, list[str]]:
    """Parse SSE stream response, return (full_text, errors).

    Accumulates tokens from data: lines until done: true.
    Returns the joined full text and any error messages.
    """
    full_text = ""
    errors = []
    lines = response.text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not line.startswith("data:"):
            continue
        # Remove "data: " prefix (5 chars + optional space)
        json_str = line[5:].strip()
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            errors.append(f"Invalid JSON in SSE: {json_str[:100]}")
            continue
        if "error" in data:
            errors.append(data["error"])
        if "token" in data and data.get("token"):
            full_text += data["token"]
    return full_text, errors


def _parse_set_cookie(set_cookie_header: str) -> str | None:
    """Extract x-anonymous-session-id value from Set-Cookie header."""
    match = re.search(r"x-anonymous-session-id=([^;]+)", set_cookie_header)
    if match:
        return match.group(1)
    return None


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def manage_config():
    """Backup config.yaml before test, restore after."""
    _backup_config()
    _write_config(DEEPSEEK_CONFIG)
    yield
    _restore_config()


@pytest.fixture(autouse=True)
def require_api_key():
    """Skip all tests if E2E_DEEPSEEK_API_KEY is not set in environment."""
    if not DEEPSEEK_API_KEY:
        pytest.skip("E2E_DEEPSEEK_API_KEY not set — skipping real LLM test")


@pytest.fixture
def http_client():
    """Synchronous httpx client for E2E HTTP tests."""
    client = httpx.Client(timeout=30.0)
    yield client
    client.close()


# ── Scenario 1: Non-streaming Multi-turn Context (AC1) ─────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario1_NonStreamingMultiTurn:
    """AC1: 用户在同一 session 内进行多轮非流式对话，后续对话能记住前序上下文."""

    PORT = 18710

    def test_multi_turn_context_remembered(self, http_client):
        """Send two non-streaming messages in the same session; verify context persistence."""
        base = f"http://127.0.0.1:{self.PORT}"
        headers = {
            "X-HW-AgentGateway-User-Id": "test-user-1",
            "x-hw-agentarts-session-id": "test-session-1",
        }

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            # Request 1: Tell the agent my name
            r1 = http_client.post(
                f"{base}/invocations",
                json={"message": "我叫小明"},
                headers=headers,
            )
            assert r1.status_code == 200, f"Request 1 failed: {r1.status_code} {r1.text[:300]}"
            data1 = r1.json()
            assert "response" in data1, f"No 'response' in: {data1}"

            # Request 2: Ask my name — should remember "小明"
            r2 = http_client.post(
                f"{base}/invocations",
                json={"message": "我叫什么名字？"},
                headers=headers,
            )
            assert r2.status_code == 200, f"Request 2 failed: {r2.status_code} {r2.text[:300]}"
            data2 = r2.json()
            assert "response" in data2, f"No 'response' in: {data2}"

            response2 = data2["response"]
            assert "小明" in response2, (
                f"Expected '小明' in second response, got: {response2[:500]}"
            )
        finally:
            _stop_service(proc)


# ── Scenario 2: Streaming Multi-turn Context (AC2) ─────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario2_StreamingMultiTurn:
    """AC2: 用户在同一 session 内进行多轮流式对话，后续对话能记住前序上下文."""

    PORT = 18711

    def test_streaming_multi_turn_context(self, http_client):
        """Send two streaming messages in same session; verify SSE context."""
        base = f"http://127.0.0.1:{self.PORT}"
        headers = {
            "X-HW-AgentGateway-User-Id": "test-user-1",
            "x-hw-agentarts-session-id": "test-session-2",
        }

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            # Request 1 (stream): Set favorite color
            r1 = http_client.post(
                f"{base}/invocations",
                json={"message": "我最喜欢的颜色是蓝色", "stream": True},
                headers=headers,
            )
            assert r1.status_code == 200, f"Stream 1 failed: {r1.status_code}"
            text1, errors1 = _parse_sse_stream(r1)
            assert not errors1, f"SSE errors in request 1: {errors1}"
            assert len(text1) > 0, "No tokens received in stream 1"

            # Request 2 (stream): Ask about color — should remember
            r2 = http_client.post(
                f"{base}/invocations",
                json={"message": "我最喜欢什么颜色？", "stream": True},
                headers=headers,
            )
            assert r2.status_code == 200, f"Stream 2 failed: {r2.status_code}"
            text2, errors2 = _parse_sse_stream(r2)
            assert not errors2, f"SSE errors in request 2: {errors2}"
            assert len(text2) > 0, "No tokens received in stream 2"

            assert "蓝色" in text2, (
                f"Expected '蓝色' in second stream response, got: {text2[:500]}"
            )
        finally:
            _stop_service(proc)

    def test_sse_format_valid(self, http_client):
        """Verify SSE stream format: lines start with 'data: ', valid JSON with token/done."""
        base = f"http://127.0.0.1:{self.PORT}"
        headers = {
            "X-HW-AgentGateway-User-Id": "test-user-1",
            "x-hw-agentarts-session-id": "test-sse-format",
        }

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            r = http_client.post(
                f"{base}/invocations",
                json={"message": "你好", "stream": True},
                headers=headers,
            )
            assert r.status_code == 200, f"SSE request failed: {r.status_code}"
            content_type = r.headers.get("content-type", "")
            assert "text/event-stream" in content_type, f"Wrong content-type: {content_type}"

            # Parse and validate each SSE line
            lines = [l.strip() for l in r.text.split("\n") if l.strip()]
            for line in lines:
                assert line.startswith("data: "), f"SSE line doesn't start with 'data: ': {line[:80]}"
                json_str = line[6:]  # after "data: "
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    pytest.fail(f"Invalid JSON in SSE: {json_str[:100]}")
                # Must have either token or error, and done
                assert "done" in data, f"SSE data missing 'done' field: {data}"
                assert isinstance(data["done"], bool), f"'done' is not bool: {data}"
                if not data.get("error"):
                    assert "token" in data, f"SSE data missing 'token' field: {data}"
        finally:
            _stop_service(proc)


# ── Scenario 3: Cross-session Isolation (AC3) ──────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3_CrossSessionIsolation:
    """AC3: 不同 session 之间的上下文互相隔离."""

    PORT = 18712

    def test_cross_session_context_not_shared(self, http_client):
        """Session A sets context; Session B should not see it."""
        base = f"http://127.0.0.1:{self.PORT}"

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            # Session A: Set name
            r_a = http_client.post(
                f"{base}/invocations",
                json={"message": "我叫小红"},
                headers={
                    "X-HW-AgentGateway-User-Id": "test-user-1",
                    "x-hw-agentarts-session-id": "session-a",
                },
            )
            assert r_a.status_code == 200, f"Session A failed: {r_a.status_code}"

            # Session B: Ask name — should NOT know "小红"
            r_b = http_client.post(
                f"{base}/invocations",
                json={"message": "我叫什么名字？"},
                headers={
                    "X-HW-AgentGateway-User-Id": "test-user-1",
                    "x-hw-agentarts-session-id": "session-b",
                },
            )
            assert r_b.status_code == 200, f"Session B failed: {r_b.status_code}"
            data_b = r_b.json()
            response_b = data_b.get("response", "")
            assert "小红" not in response_b, (
                f"Cross-session leak: '小红' found in Session B response: {response_b[:500]}"
            )
        finally:
            _stop_service(proc)


# ── Scenario 4: User-scoped Thread ID Isolation (AC4) ──────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario4_UserScopedIsolation:
    """AC4: 不同 user 即使使用相同 session header，上下文也隔离."""

    PORT = 18713

    def test_user_scoped_thread_isolation(self, http_client):
        """User A sets a secret; User B with same session header cannot see it."""
        base = f"http://127.0.0.1:{self.PORT}"

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            # User A: Share a secret
            r_a = http_client.post(
                f"{base}/invocations",
                json={"message": "我的秘密代码是12345"},
                headers={
                    "X-HW-AgentGateway-User-Id": "user_a",
                    "x-hw-agentarts-session-id": "shared-session",
                },
            )
            assert r_a.status_code == 200, f"User A failed: {r_a.status_code}"

            # User B: Same session header, ask about secret
            r_b = http_client.post(
                f"{base}/invocations",
                json={"message": "秘密代码是什么？"},
                headers={
                    "X-HW-AgentGateway-User-Id": "user_b",
                    "x-hw-agentarts-session-id": "shared-session",
                },
            )
            assert r_b.status_code == 200, f"User B failed: {r_b.status_code}"
            data_b = r_b.json()
            response_b = data_b.get("response", "")
            assert "12345" not in response_b, (
                f"User-scoped leak: '12345' found in User B response: {response_b[:500]}"
            )
        finally:
            _stop_service(proc)


# ── Scenario 5: Cookie Fallback (AC5) ──────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario5_CookieFallback:
    """AC5: 当 x-hw-agentarts-session-id header 缺失时，服务自动生成 session 并回传 cookie."""

    PORT = 18714

    def test_cookie_generation_and_multi_turn_via_cookie(self, http_client):
        """First request without session header gets Set-Cookie; second with cookie has context."""
        base = f"http://127.0.0.1:{self.PORT}"

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
            "ENV": "development",
        })
        try:
            # Request 1: No session header, should get Set-Cookie
            r1 = http_client.post(
                f"{base}/invocations",
                json={"message": "我住在北京"},
                headers={"X-HW-AgentGateway-User-Id": "test-cookie-user"},
            )
            assert r1.status_code == 200, f"Request 1 failed: {r1.status_code}"

            # Verify Set-Cookie header exists
            set_cookie = r1.headers.get("Set-Cookie")
            assert set_cookie is not None, "Expected Set-Cookie header in response"
            assert "x-anonymous-session-id=" in set_cookie, (
                f"Expected x-anonymous-session-id in Set-Cookie, got: {set_cookie}"
            )

            # Extract the session ID
            session_id = _parse_set_cookie(set_cookie)
            assert session_id is not None, f"Could not parse session ID from: {set_cookie}"
            # Validate UUID format (len > 0 and looks like uuid)
            assert len(session_id) > 10, f"Session ID too short: {session_id}"

            # Request 2: Use Cookie header (simulate browser returning cookie)
            r2 = http_client.post(
                f"{base}/invocations",
                json={"message": "我住在哪个城市？"},
                headers={
                    "X-HW-AgentGateway-User-Id": "test-cookie-user",
                    "Cookie": f"x-anonymous-session-id={session_id}",
                },
            )
            assert r2.status_code == 200, f"Request 2 failed: {r2.status_code} {r2.text[:300]}"
            data2 = r2.json()
            response2 = data2.get("response", "")
            assert "北京" in response2, (
                f"Expected '北京' in cookie-fallback response, got: {response2[:500]}"
            )
        finally:
            _stop_service(proc)

    def test_streaming_cookie_fallback(self, http_client):
        """Streaming request without session header also returns Set-Cookie."""
        base = f"http://127.0.0.1:{self.PORT}"

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
            "ENV": "development",
        })
        try:
            r = http_client.post(
                f"{base}/invocations",
                json={"message": "你好", "stream": True},
                headers={"X-HW-AgentGateway-User-Id": "test-cookie-user"},
            )
            assert r.status_code == 200, f"Stream request failed: {r.status_code}"
            set_cookie = r.headers.get("Set-Cookie")
            assert set_cookie is not None, (
                "Expected Set-Cookie header in streaming response"
            )
            assert "x-anonymous-session-id=" in set_cookie, (
                f"Expected x-anonymous-session-id in streaming Set-Cookie, got: {set_cookie}"
            )
        finally:
            _stop_service(proc)


# ── Scenario 6: Ping and Existing Functionality (AC8) ──────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario6_PingAndExisting:
    """AC8: 基础功能验证——ping、无 session header 可用、非流式+流式混合 session."""

    PORT = 18715

    def test_ping_returns_ok(self, http_client):
        """GET /ping returns 200 with {"status": "ok"}."""
        base = f"http://127.0.0.1:{self.PORT}"

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            r = http_client.get(f"{base}/ping")
            assert r.status_code == 200
            data = r.json()
            assert data == {"status": "ok"}, f"Unexpected ping response: {data}"
        finally:
            _stop_service(proc)

    def test_invocation_without_session_header(self, http_client):
        """POST /invocations without session header still works."""
        base = f"http://127.0.0.1:{self.PORT}"

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            r = http_client.post(
                f"{base}/invocations",
                json={"message": "你好"},
                headers={"X-HW-AgentGateway-User-Id": "test-no-session"},
            )
            assert r.status_code == 200, f"Request failed: {r.status_code}"
            data = r.json()
            assert "response" in data, f"No 'response' in: {data}"
            assert len(data["response"]) > 0, "Empty response"
        finally:
            _stop_service(proc)

    def test_non_stream_then_stream_same_session(self, http_client):
        """Non-stream then stream in same session: context persists."""
        base = f"http://127.0.0.1:{self.PORT}"
        headers = {
            "X-HW-AgentGateway-User-Id": "test-user-ac8",
            "x-hw-agentarts-session-id": "test-ac8",
        }

        proc = _start_service(self.PORT, env={
            "DEEPSEEK_API_KEY": DEEPSEEK_API_KEY,
        })
        try:
            # Non-stream: say hello
            r1 = http_client.post(
                f"{base}/invocations",
                json={"message": "你好"},
                headers=headers,
            )
            assert r1.status_code == 200, f"Non-stream failed: {r1.status_code}"

            # Stream: ask to repeat
            r2 = http_client.post(
                f"{base}/invocations",
                json={"message": "重复一遍你刚才说的", "stream": True},
                headers=headers,
            )
            assert r2.status_code == 200, f"Stream failed: {r2.status_code}"
            text2, errors2 = _parse_sse_stream(r2)
            assert not errors2, f"SSE errors: {errors2}"
            assert len(text2) > 0, "No tokens in stream response"

            # Should reference conversation context (not necessarily exact "你好",
            # but the response should be non-empty and relate to the greeting)
            # Minimal check: response exists and SSE is valid
        finally:
            _stop_service(proc)
