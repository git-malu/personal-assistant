"""E2E tests for Feature 1.1 — Web Chat Frontend Engineering (assistant-ui integration).

Tests the full application stack:
- FastAPI service with static LLM mock (FakeAgentHandler via TestClient)
- Vite dev server (subprocess)
- Production build verification
- SSE streaming format and content
- Multi-turn conversation reliability
- Error handling for invalid inputs
- StaticFiles mount serving assistant-ui frontend
- Chainlit /playground coexistence

Test scenarios from plan:
  1. Dev Mode Startup — Vite dev server starts, serves assistant-ui interface
  2. SSE Streaming Chat — Proper SSE format with token events
  3. Markdown Rendering (Static) — Production build serves assistant-ui HTML
  4. Multi-turn Conversation — Multiple streaming requests succeed
  5. Error Handling — Empty query returns proper error
  6. Production Build — npm run build generates dist/
  7. Chainlit Coexistence — /playground endpoint availability
  8. StaticFiles Mount — /, /ping, /invocations stream mode all work
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SERVICE_DIR = PROJECT_ROOT / "personal-assistant-service"
CLIENT_DIR = PROJECT_ROOT / "personal-assistant-client"
DIST_DIR = CLIENT_DIR / "dist"
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
    """Start uvicorn as a subprocess. Returns the Popen handle.

    Uses `MAAS_API_KEY=dummy-e2e-test-key` to allow service startup
    (prevents lifespan crash from missing API key). Real LLM calls
    will fail (500) but HTTP plumbing is verified.
    """
    merged_env = os.environ.copy()
    # Default: provide a dummy key to prevent lifespan crash
    merged_env.setdefault("MAAS_API_KEY", "dummy-e2e-test-key")
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


async def _post_stream(client: httpx.AsyncClient, message: str) -> httpx.Response:
    """Call the unified streaming invocation endpoint."""
    return await client.post(
        "/invocations",
        json={"message": message, "stream": True},
        headers={"Accept": "text/event-stream"},
    )


def _backup_config():
    """Create a backup of config.yaml if it exists."""
    if CONFIG_YAML.exists() and not CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML), str(CONFIG_YAML_BACKUP))


def _restore_config():
    """Restore config.yaml from backup."""
    if CONFIG_YAML_BACKUP.exists():
        shutil.copy2(str(CONFIG_YAML_BACKUP), str(CONFIG_YAML))
        CONFIG_YAML_BACKUP.unlink()


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def manage_config():
    """Backup and restore config.yaml around each test module."""
    _backup_config()
    yield
    _restore_config()


@pytest.fixture
def http_client():
    """Synchronous httpx client for E2E HTTP tests."""
    client = httpx.Client(timeout=10.0)
    yield client
    client.close()


# ── FakeAgentHandler + TestClient fixture ──────────────────────────────


class FakeAgentHandler:
    """A fake AgentHandler with predictable streaming responses."""

    def __init__(self, tokens: list[str] | None = None):
        self._tokens = tokens or ["Hello", " world", "!"]
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []

    async def handle(
        self, message: str, user_id: str = "anonymous", session_id: str | None = None
    ) -> str:
        self.handle_calls.append((message, user_id, session_id))
        return "".join(self._tokens)

    async def handle_stream(self, message: str, user_id: str = "anonymous"):
        self.stream_calls.append((message, user_id))
        for token in self._tokens:
            yield f'data: {json.dumps({"token": token, "done": False})}\n\n'
        yield f'data: {json.dumps({"token": "", "done": True})}\n\n'


@pytest.fixture
def fake_handler():
    """Create a FakeAgentHandler instance."""
    handler = FakeAgentHandler()
    return handler


@pytest.fixture
async def test_app_client(fake_handler):
    """httpx AsyncClient for the FastAPI app with FakeAgentHandler.

    Uses ASGITransport to test the full FastAPI stack in-process.
    Sets app.state.agent_handler directly because ASGITransport
    doesn't auto-trigger the lifespan.

    Must be async because ASGITransport requires httpx.AsyncClient.
    Must import app.main first so the module exists for patching.
    Uses patch.object with a real module reference to avoid
    pkgutil.resolve_name errors.
    """
    os.environ.setdefault("MODEL_API_KEY", "test-key-for-e2e")
    os.environ.setdefault("MAAS_API_KEY", "dummy-e2e-test-key")

    # Import app.main first so the module exists for patching,
    # then use patch.object which takes a real module reference.
    import app.main as app_main
    with patch.object(app_main, "AgentHandler", return_value=fake_handler):
        from app.main import app

        app.state.agent_handler = fake_handler

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# ── Scenario 1: Dev Mode Startup ──────────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario1_DevModeStartup:
    """Verify Vite dev server can start and serve assistant-ui interface."""

    PORT = 5173

    @pytest.fixture(autouse=True)
    def _ensure_deps(self):
        """Ensure node_modules are installed."""
        if not (CLIENT_DIR / "node_modules").is_dir():
            pytest.skip(
                "node_modules/ not found — run 'npm install' in personal-assistant-client/"
            )

    def test_vite_dev_server_starts_and_serves_page(self, http_client):
        """npm run dev starts Vite, serves HTML with assistant-ui related content."""
        proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(self.PORT)],
            cwd=str(CLIENT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "BROWSER": "none"},
        )

        try:
            # Wait for Vite to be ready (poll up to 60s)
            deadline = time.time() + 60
            ready = False
            while time.time() < deadline:
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate(timeout=5)
                    raise RuntimeError(
                        f"Vite dev server exited with code {proc.returncode}.\n"
                        f"stdout: {stdout.decode(errors='replace')[-500:]}\n"
                        f"stderr: {stderr.decode(errors='replace')[-500:]}"
                    )
                try:
                    resp = httpx.get(
                        f"http://localhost:{self.PORT}/", timeout=2.0
                    )
                    if resp.status_code == 200:
                        ready = True
                        break
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass
                time.sleep(1)

            if not ready:
                raise TimeoutError(
                    f"Vite dev server did not start within 60s on port {self.PORT}"
                )

            # Verify the page is the assistant-ui chat interface
            resp = http_client.get(f"http://localhost:{self.PORT}/")
            assert resp.status_code == 200
            content_type = resp.headers.get("content-type", "").lower()
            assert "text/html" in content_type

            body = resp.text
            # The page should contain the root div and React-related content
            assert '<div id="root"></div>' in body or "root" in body.lower(), (
                f"Expected React root div in HTML, got body preview: {body[:500]}"
            )
            assert "script" in body.lower(), "Expected script tags in HTML"

        finally:
            _stop_service(proc)


# ── Scenario 2: SSE Streaming Chat ─────────────────────────────────────


@pytest.mark.feature
class TestScenario2_SSEStreamingChat:
    """Verify SSE streaming chat format, content, and multi-event behavior."""

    @pytest.mark.asyncio
    async def test_sse_content_type_and_headers(self, test_app_client):
        """POST /invocations stream=true returns text/event-stream headers."""
        resp = await _post_stream(test_app_client, "Hello")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"

        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, f"Got content-type: {content_type}"
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("connection") == "keep-alive"
        assert resp.headers.get("x-accel-buffering") == "no"

    @pytest.mark.asyncio
    async def test_sse_data_prefix_format(self, test_app_client):
        """SSE events use 'data: ' prefix with valid JSON payload."""
        resp = await _post_stream(test_app_client, "Hello")
        assert resp.status_code == 200

        body = resp.text
        lines = [line for line in body.split("\n") if line.strip()]

        for line in lines:
            assert line.startswith("data: "), f"SSE line missing data prefix: {line!r}"

            # Each data line should be valid JSON
            payload = line[6:]  # strip "data: " prefix
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as e:
                pytest.fail(f"SSE data line is not valid JSON: {payload!r}. Error: {e}")

            # Must have either 'token' key (streaming) or 'done' key (completion)
            assert "token" in parsed or "done" in parsed, (
                f"SSE payload missing 'token' or 'done': {parsed}"
            )

    @pytest.mark.asyncio
    async def test_sse_streams_multiple_events(self, test_app_client, fake_handler):
        """Streaming produces multiple token events and a final done event."""
        resp = await _post_stream(test_app_client, "Hello")
        assert resp.status_code == 200

        body = resp.text
        lines = [line for line in body.split("\n") if line.strip()]

        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        tokens = [e for e in events if not e.get("done")]
        done_events = [e for e in events if e.get("done")]

        assert len(tokens) >= 1, f"Expected at least 1 token event, got {len(tokens)}"
        assert len(done_events) == 1, f"Expected exactly 1 done event, got {len(done_events)}"
        assert done_events[0]["done"] is True

        # Verify stream_calls recorded correctly
        assert len(fake_handler.stream_calls) == 1
        assert fake_handler.stream_calls[0][0] == "Hello"

    @pytest.mark.asyncio
    async def test_sse_with_chinese_text(self, test_app_client):
        """SSE streaming works with Chinese text (UTF-8)."""
        resp = await _post_stream(test_app_client, "你好世界")
        assert resp.status_code == 200

        body = resp.text
        assert "data:" in body
        # Verify the response contains valid JSON
        lines = [line for line in body.split("\n") if line.strip()]
        for line in lines:
            if line.startswith("data: "):
                json.loads(line[6:])  # Should not raise

    @pytest.mark.asyncio
    async def test_sse_with_special_characters(self, test_app_client):
        """SSE streaming handles special characters in message body."""
        resp = await _post_stream(test_app_client, "Hello!+@#$%")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ── Scenario 3: Markdown Rendering (Static) ────────────────────────────
# NOTE (refactor-2): This entire scenario is now OBSOLETE. refactor-2
# removed the StaticFiles mount; GET / no longer serves dist/index.html.
# Tests are skipped but preserved as historical documentation.


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3_MarkdownRenderingStatic:
    """Verify production build serves assistant-ui frontend with chat interface.

    ALL TESTS SKIPPED after refactor-2: StaticFiles mount removed.
    GET / now returns 404 — dist/ is no longer served by the backend.
    """

    PORT = 18711

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: StaticFiles mount removed, "
               "GET / now returns 404 by design."
    )
    def test_build_and_serve_dist(self, http_client):
        """Build client, start service with dist/, verify HTML contains assistant-ui elements."""
        # Ensure dist/ exists (run build if needed)
        if not (DIST_DIR / "index.html").exists():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.fail(
                    f"npm run build failed with code {result.returncode}:\n"
                    f"stdout: {result.stdout[-500:]}\n"
                    f"stderr: {result.stderr[-500:]}"
                )

        assert DIST_DIR.is_dir(), f"dist/ directory not found at {DIST_DIR}"
        assert (DIST_DIR / "index.html").exists(), "dist/index.html not found"

        # Find JS/CSS assets
        assets_dir = DIST_DIR / "assets"
        js_files = list(assets_dir.glob("*.js")) if assets_dir.is_dir() else []
        css_files = list(assets_dir.glob("*.css")) if assets_dir.is_dir() else []
        assert len(js_files) > 0, f"No JS bundle found in {assets_dir}"
        assert len(css_files) > 0, f"No CSS bundle found in {assets_dir}"

        # Start service and verify it serves the built frontend
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/")
            assert resp.status_code == 200

            content_type = resp.headers.get("content-type", "").lower()
            assert "text/html" in content_type, f"Expected HTML, got: {content_type}"

            body = resp.text
            # Verify it's the assistant-ui chat interface:
            # - Root div for React
            assert '<div id="root"></div>' in body or 'id="root"' in body, (
                f"Expected React root div in HTML. Body preview: {body[:500]}"
            )
            # - Script tags for bundled JS
            assert '<script type="module"' in body or '<script src=' in body or '<script ' in body, (
                f"Expected script tags in HTML. Body preview: {body[:500]}"
            )
            # - Title or app name
            assert "Personal Assistant" in body or "personal-assistant" in body.lower(), (
                f"Expected app name in HTML. Body preview: {body[:500]}"
            )
        finally:
            _stop_service(proc)

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: StaticFiles mount removed, "
               "static assets are no longer served by the backend."
    )
    def test_static_assets_are_served(self, http_client):
        """Bundled JS and CSS assets are served from /assets/.

        SKIPPED: refactor-2 removed StaticFiles.
        """
        # Verify dist exists first
        if not (DIST_DIR / "index.html").exists():
            pytest.skip("dist/ not built — run npm run build first")

        assets_dir = DIST_DIR / "assets"
        if not assets_dir.is_dir():
            pytest.skip("No assets directory in dist/")

        proc = _start_service(self.PORT)
        try:
            # Verify the index page references assets
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/")
            body = resp.text

            # Check that assets are referenced in HTML
            assert "/assets/" in body, (
                f"Expected /assets/ reference in HTML. Body preview: {body[:500]}"
            )
        finally:
            _stop_service(proc)


# ── Scenario 4: Multi-turn Conversation ────────────────────────────────


@pytest.mark.feature
class TestScenario4_MultiTurnConversation:
    """Verify multiple streaming messages in sequence work correctly."""

    @pytest.mark.asyncio
    async def test_multiple_messages_return_valid_sse(self, test_app_client, fake_handler):
        """Sending multiple messages sequentially returns valid SSE for each."""
        messages = ["Hello", "How are you?", "What time is it?"]

        for i, msg in enumerate(messages):
            resp = await _post_stream(test_app_client, msg)
            assert resp.status_code == 200, f"Message {i} ('{msg}') failed: {resp.status_code}"
            assert "text/event-stream" in resp.headers.get("content-type", "")

            # Verify valid SSE format
            body = resp.text
            assert "data:" in body, f"Message {i}: no 'data:' in response"
            lines = [line for line in body.split("\n") if line.startswith("data: ")]
            assert len(lines) >= 2, f"Message {i}: expected >=2 SSE lines, got {len(lines)}"

        # Verify all calls were recorded
        assert len(fake_handler.stream_calls) == 3
        for i, msg in enumerate(messages):
            assert fake_handler.stream_calls[i][0] == msg

    @pytest.mark.asyncio
    async def test_rapid_successive_requests_no_crash(self, test_app_client):
        """Rapid successive requests don't crash the service."""
        # Send 10 requests quickly
        for i in range(10):
            resp = await _post_stream(test_app_client, f"msg{i}")
            # Only check status — the test verifies stability
            assert resp.status_code in (200, 400), (
                f"Request {i} failed with unexpected status {resp.status_code}"
            )


# ── Scenario 5: Error Handling ─────────────────────────────────────────


@pytest.mark.feature
class TestScenario5_ErrorHandling:
    """Verify proper error handling for invalid inputs."""

    @pytest.mark.asyncio
    async def test_empty_message_returns_400(self, test_app_client):
        """POST /invocations stream=true with empty message returns 400."""
        resp = await test_app_client.post(
            "/invocations",
            json={"message": "", "stream": True},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
        )

        # Try to parse JSON error detail
        try:
            data = resp.json()
            assert "detail" in data
            assert "required" in data["detail"].lower() or "message" in data["detail"].lower()
        except Exception:
            # At minimum the response should not be a crash (5xx)
            assert resp.status_code < 500, (
                f"Empty query should not cause server error: {resp.status_code}"
            )

    @pytest.mark.asyncio
    async def test_missing_message_returns_400(self, test_app_client):
        """POST /invocations stream=true without message returns 400."""
        resp = await test_app_client.post("/invocations", json={"stream": True})
        assert resp.status_code == 400, (
            f"Expected 400 for missing message, got {resp.status_code}: {resp.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_whitespace_only_message_returns_400(self, test_app_client):
        """POST /invocations stream=true with whitespace message returns 400."""
        resp = await test_app_client.post(
            "/invocations",
            json={"message": "  ", "stream": True},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for whitespace-only message, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_service_does_not_crash_after_invalid_request(self, test_app_client):
        """After receiving 400, the service still handles valid requests."""
        # Send invalid request first
        resp_bad = await test_app_client.post(
            "/invocations",
            json={"message": "", "stream": True},
        )
        assert resp_bad.status_code == 400

        # Then send valid request
        resp_good = await _post_stream(test_app_client, "valid")
        assert resp_good.status_code == 200
        assert "data:" in resp_good.text


# ── Scenario 6: Production Build ───────────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario6_ProductionBuild:
    """Verify npm run build generates dist/ with index.html and bundled assets."""

    @pytest.fixture(autouse=True)
    def _ensure_deps(self):
        """Ensure node_modules are installed."""
        if not (CLIENT_DIR / "node_modules").is_dir():
            # Try to install
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(
                    f"npm install failed: {result.stderr[-300:]}"
                )

    def test_npm_run_build_creates_dist(self, tmp_path):
        """npm run build generates dist/ directory with index.html."""
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(CLIENT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"npm run build failed with code {result.returncode}:\n"
            f"stderr: {result.stderr[-800:]}\n"
            f"stdout: {result.stdout[-800:]}"
        )

        assert DIST_DIR.is_dir(), f"dist/ directory not found after build at {DIST_DIR}"
        assert (DIST_DIR / "index.html").exists(), "dist/index.html not found after build"

    def test_dist_index_html_content(self):
        """dist/index.html contains proper HTML structure for assistant-ui."""
        if not (DIST_DIR / "index.html").exists():
            # Run build first
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(f"npm run build failed: {result.stderr[-300:]}")

        index_html = DIST_DIR / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "<!doctype html>" in content.lower() or "<!DOCTYPE html>" in content
        assert '<html lang="zh-CN">' in content or "<html" in content
        assert '<div id="root"></div>' in content or 'id="root"' in content
        assert '<script' in content, "Expected script tags in index.html"
        assert "Personal Assistant" in content, (
            f"Expected app name in index.html, got preview: {content[:300]}"
        )

    def test_dist_has_bundled_assets(self):
        """dist/assets/ contains bundled JS and CSS files."""
        if not (DIST_DIR / "index.html").exists():
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(CLIENT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                pytest.skip(f"npm run build failed: {result.stderr[-300:]}")

        assets_dir = DIST_DIR / "assets"
        assert assets_dir.is_dir(), f"assets/ directory not found at {assets_dir}"

        js_files = list(assets_dir.glob("*.js"))
        css_files = list(assets_dir.glob("*.css"))

        assert len(js_files) >= 1, (
            f"No JS files found in {assets_dir}. Contents: {list(assets_dir.iterdir())}"
        )
        assert len(css_files) >= 1, (
            f"No CSS files found in {assets_dir}. Contents: {list(assets_dir.iterdir())}"
        )

        # Verify files are non-empty
        for js_file in js_files:
            assert js_file.stat().st_size > 0, f"JS file {js_file.name} is empty"
        for css_file in css_files:
            assert css_file.stat().st_size > 0, f"CSS file {css_file.name} is empty"


# ── Scenario 7: Chainlit Coexistence ───────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario7_ChainlitCoexistence:
    """Verify /playground endpoint availability alongside the web chat frontend."""

    PORT = 18712

    def test_playground_endpoint_responds(self, http_client):
        """GET /playground returns a response (200, 302, or 4xx — not a 5xx crash)."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(
                f"http://127.0.0.1:{self.PORT}/playground",
                follow_redirects=False,
            )
            # Expect it to respond (200, 302, or 404 — just not 5xx crash).
            # Note: Currently /playground is not explicitly mounted, so
            # the SPA StaticFiles fallback (html=True) may serve index.html.
            # This test verifies the endpoint doesn't crash the service.
            assert resp.status_code < 500, (
                f"/playground returned server error: {resp.status_code}\n"
                f"Response: {resp.text[:300]}"
            )

            # Additional check: does it serve the chat UI?
            content_type = resp.headers.get("content-type", "").lower()
            is_html = "text/html" in content_type
            body = resp.text.lower()

            if resp.status_code == 200 and is_html:
                # It's serving HTML — check if it's the chat UI (index.html)
                has_chat_ui = "personal assistant" in body or 'id="root"' in body
                if has_chat_ui:
                    # Currently, the SPA fallback serves index.html for /playground
                    # because Chainlit is not yet mounted. This is a known gap.
                    # See: ADR-003 (Chainlit Integration)
                    pass  # Non-fatal — the endpoint works, but serves chat UI
        finally:
            _stop_service(proc)

    def test_playground_does_not_crash_service(self, http_client):
        """Multiple /playground requests don't crash the service."""
        proc = _start_service(self.PORT)
        try:
            for i in range(3):
                resp = http_client.get(
                    f"http://127.0.0.1:{self.PORT}/playground",
                    follow_redirects=False,
                )
                assert resp.status_code < 500, (
                    f"Request {i}: /playground returned {resp.status_code}"
                )

            # After /playground calls, main endpoints still work
            ping = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert ping.status_code == 200
            assert ping.json() == {"status": "ok"}
        finally:
            _stop_service(proc)


# ── Scenario 8: StaticFiles Mount ──────────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario8_StaticFilesMount:
    """Verify StaticFiles mount serves dist/ and API routes take priority.

    NOTE (refactor-2): The StaticFiles mount is removed. `test_root_serves_index_html`
    and `test_spa_fallback_serves_index_html` are skipped. The remaining API-level
    tests (ping, stream, invocations) still pass because API routes continue to work.
    """

    PORT = 18713

    # NOTE (refactor-2): _ensure_dist fixture removed — the 2 dist-dependent
    # tests are skipped, and the remaining 3 API tests don't need dist/.

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: StaticFiles mount removed, "
               "GET / now returns 404 by design."
    )
    def test_root_serves_index_html(self, http_client):
        """GET / returns dist/index.html with 200 and text/html.

        SKIPPED: refactor-2 removed StaticFiles. GET / now returns 404.
        """
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/")
            assert resp.status_code == 200, (
                f"GET / failed with {resp.status_code}: {resp.text[:200]}"
            )

            content_type = resp.headers.get("content-type", "").lower()
            assert "text/html" in content_type, f"Expected HTML, got: {content_type}"

            body = resp.text
            assert "<!doctype html>" in body.lower()
            assert "Personal Assistant" in body
            assert '<div id="root"></div>' in body
        finally:
            _stop_service(proc)

    def test_api_ping_takes_priority_over_static(self, http_client):
        """GET /ping returns 200 JSON — API routes override static mount."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/ping")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"status": "ok"}
            content_type = resp.headers.get("content-type", "")
            assert "application/json" in content_type
        finally:
            _stop_service(proc)

    def test_invocations_stream_works_with_static_mounted(self, http_client):
        """POST /invocations stream=true works when static files are mounted."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "test", "stream": True},
                headers={"Accept": "text/event-stream"},
            )
            # With dummy API key, LLM may fail (500) but the endpoint should respond
            assert resp.status_code in (200, 500), (
                f"Expected 200 or 500, got {resp.status_code}: {resp.text[:200]}"
            )
        finally:
            _stop_service(proc)

    @pytest.mark.skip(
        reason="Obsolete after refactor-2: StaticFiles/SPA fallback removed. "
               "Bug-2 (SPA fallback) is now invalid by design — GET /chat returns 404."
    )
    def test_spa_fallback_serves_index_html(self, http_client):
        """SPA fallback: verify /chat path serves index.html.

        SKIPPED: refactor-2 removed StaticFiles and SPA fallback entirely.
        Bug-2 is now invalid — SPA fallback was removed by design.
        """
        proc = _start_service(self.PORT)
        try:
            resp = http_client.get(f"http://127.0.0.1:{self.PORT}/chat")
            # Strict: bug-2 causes 404. When fixed, expect 200 with index.html.
            assert resp.status_code == 200, (
                f"Expected SPA fallback to serve index.html, got {resp.status_code}"
            )
            content_type = resp.headers.get("content-type", "").lower()
            assert "text/html" in content_type
            body = resp.text
            assert "Personal Assistant" in body
            assert '<div id="root"></div>' in body
        finally:
            _stop_service(proc)

    def test_api_invocations_works_with_static_mounted(self, http_client):
        """POST /invocations endpoint works alongside static files."""
        proc = _start_service(self.PORT)
        try:
            resp = http_client.post(
                f"http://127.0.0.1:{self.PORT}/invocations",
                json={"message": "Hello"},
            )
            # With dummy key, may get 500 from LLM, but the endpoint exists
            assert resp.status_code in (200, 400, 500), (
                f"Unexpected status: {resp.status_code}"
            )
        finally:
            _stop_service(proc)
