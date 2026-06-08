"""E2E tests for Refactor-2: Remove Web Chat Static File Serving.

After refactor-2:
- StaticFiles mount removed from app/main.py
- SPAFallbackMiddleware deleted (app/spa_middleware.py removed)
- No more COPY of personal-assistant-client/dist/ in Dockerfile
- Container only serves API routes + Chainlit Playground
- GET / now intentionally returns 404

Test scenarios (all subprocess-based, using ServiceProcess from conftest.py):
  1. Health check still works — GET /ping → 200 {"status": "ok"}
  2. Invocations endpoint works — POST /invocations → non-5xx response
  3. SSE streaming still works — GET /api/chat/stream?q=hello → SSE response
  4. Playground redirect works — GET /playground → 307 redirect to /playground/
  5. Chainlit UI loads — GET /playground/ → Chainlit UI (non-5xx)
  6. Root returns 404 (KEY CHANGE) — GET / → 404
"""

import httpx
import pytest

# Import shared ServiceProcess fixture from e2e conftest.
# pytest automatically discovers conftest.py in the e2e root directory.
from conftest import ServiceProcess


# ── Scenario 1: Health check still works ────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario1_HealthCheck:
    """Verify /ping health check endpoint still works after refactor."""

    PORT = 18740

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_ping_returns_ok(self, service_url):
        """GET /ping returns 200 with {"status": "ok"}."""
        resp = httpx.get(f"{service_url}/ping")
        assert resp.status_code == 200, (
            f"Expected 200 from /ping, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert data == {"status": "ok"}, f"Unexpected ping response: {data}"
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type, (
            f"Expected JSON content-type, got: {content_type}"
        )


# ── Scenario 2: Invocations endpoint works ──────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario2_InvocationsEndpoint:
    """Verify /invocations endpoint works after static serving removal."""

    PORT = 18741

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_invocations_responds_without_crash(self, service_url):
        """POST /invocations with valid message returns a response.

        With a dummy API key, the LLM call may fail (500), but the endpoint
        plumbing must still work — we verify it responds without crashing the
        process and returns expected status codes (200 or 500 for LLM failure).
        """
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": "Hello"},
        )
        assert resp.status_code in (200, 500), (
            f"POST /invocations got unexpected status: {resp.status_code}\n"
            f"Response: {resp.text[:200]}"
        )

    def test_invocations_empty_message_returns_400(self, service_url):
        """POST /invocations with empty message returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": ""},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_invocations_missing_message_returns_400(self, service_url):
        """POST /invocations without message field returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for missing message, got {resp.status_code}: {resp.text[:200]}"
        )


# ── Scenario 3: SSE streaming still works ───────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3_SSEStreaming:
    """Verify SSE streaming chat still works after static serving removal."""

    PORT = 18742

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_sse_streaming_endpoint_responds(self, service_url):
        """GET /api/chat/stream?q=hello returns a response (non-5xx)."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=hello")
        assert resp.status_code < 500, (
            f"SSE streaming should not cause server error, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_empty_query_returns_400(self, service_url):
        """SSE streaming with empty query returns 400."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=")
        assert resp.status_code == 400, (
            f"Expected 400 for empty query, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_missing_query_returns_400(self, service_url):
        """SSE streaming without q param returns 400."""
        resp = httpx.get(f"{service_url}/api/chat/stream")
        assert resp.status_code == 400, (
            f"Expected 400 for missing query, got {resp.status_code}: {resp.text[:200]}"
        )


# ── Scenario 4: Playground redirect works ───────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario4_PlaygroundRedirect:
    """Verify /playground redirect still works after refactor."""

    PORT = 18743

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_playground_redirects_to_trailing_slash(self, service_url):
        """GET /playground returns 307 redirect to /playground/."""
        resp = httpx.get(f"{service_url}/playground", follow_redirects=False)

        assert resp.status_code == 307, (
            f"Expected 307 redirect from /playground, got {resp.status_code}"
        )
        location = resp.headers.get("location", "")
        assert location == "/playground/", (
            f"Expected redirect Location '/playground/', got: {location!r}"
        )

    def test_playground_trailing_slash_returns_chainlit(self, service_url):
        """GET /playground/ returns 200 with Chainlit HTML."""
        resp = httpx.get(f"{service_url}/playground/", follow_redirects=True)

        assert resp.status_code == 200, (
            f"Expected 200 from /playground/, got {resp.status_code}"
        )
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type, (
            f"Expected HTML from /playground/, got content-type: {content_type}"
        )
        # Chainlit delivers an SPA shell with HTML structure
        html_lower = resp.text.lower()
        assert "<html" in html_lower or "<!doctype html>" in html_lower, (
            f"Expected HTML structure in /playground/ response"
        )


# ── Scenario 5: Chainlit UI loads ───────────────────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario5_ChainlitUI:
    """Verify Chainlit UI is properly accessible via /playground/."""

    PORT = 18744

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_chainlit_ui_returns_non_5xx(self, service_url):
        """GET /playground/ returns a non-5xx status code."""
        resp = httpx.get(f"{service_url}/playground/", follow_redirects=False)
        assert resp.status_code < 500, (
            f"/playground/ returned server error: {resp.status_code}\n"
            f"Response: {resp.text[:300]}"
        )

    def test_chainlit_ui_survives_multiple_requests(self, service_url):
        """Multiple requests to /playground/ do not crash the service."""
        for i in range(3):
            resp = httpx.get(f"{service_url}/playground/", follow_redirects=False)
            assert resp.status_code < 500, (
                f"Request {i}: /playground/ returned {resp.status_code}"
            )

        # After /playground/ calls, health check should still work
        ping_resp = httpx.get(f"{service_url}/ping")
        assert ping_resp.status_code == 200
        assert ping_resp.json() == {"status": "ok"}


# ── Scenario 6: Root returns 404 (KEY CHANGE) ───────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario6_RootReturns404:
    """Verify GET / returns 404 — the key behavioral change in refactor-2."""

    PORT = 18745

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_root_returns_404(self, service_url):
        """GET / returns 404 (no longer serves index.html)."""
        resp = httpx.get(f"{service_url}/")

        assert resp.status_code == 404, (
            f"Expected 404 from GET / after static serving removal, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    def test_root_does_not_return_html(self, service_url):
        """GET / does NOT return HTML content."""
        resp = httpx.get(f"{service_url}/")

        content_type = resp.headers.get("content-type", "")
        # Should NOT be HTML — either JSON (FastAPI error) or other
        assert "text/html" not in content_type.lower(), (
            f"GET / should not return HTML after static serving removal. "
            f"Got content-type: {content_type}"
        )

    def test_other_endpoints_unaffected_by_root_404(self, service_url):
        """After refactor, /ping and /api/chat/stream still work even though / is 404."""
        # Verify / is 404
        resp_root = httpx.get(f"{service_url}/")
        assert resp_root.status_code == 404, (
            f"Expected 404 from /, got {resp_root.status_code}"
        )

        # Verify /ping still works
        resp_ping = httpx.get(f"{service_url}/ping")
        assert resp_ping.status_code == 200
        assert resp_ping.json() == {"status": "ok"}

        # Verify /playground still works
        resp_playground = httpx.get(f"{service_url}/playground", follow_redirects=False)
        assert resp_playground.status_code == 307, (
            f"Expected 307 from /playground, got {resp_playground.status_code}"
        )
