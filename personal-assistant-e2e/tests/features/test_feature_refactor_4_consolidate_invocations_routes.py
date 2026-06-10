"""E2E tests for /invocations route compatibility.

Current route contract after refactor-7:
- Web Chat streaming uses POST /invocations with {"stream": true}
- GET /playground → GET /invocations/playground (Chainlit redirect)
- Chainlit mount: /playground → /invocations/playground
- GET /ping — unchanged (platform internal)
- POST /invocations — unchanged (AgentArts SDK invoke)
- .agentarts_config.yaml: url_match_type: ACCURATE_MATCH, arch: arm64

Test scenarios (all subprocess-based, using ServiceProcess from conftest.py):
  1. Health check endpoint unchanged — GET /ping → 200 {"status": "ok"}
  2. Sync invocation endpoint unchanged — POST /invocations → non-5xx response
  3. SSE streaming on /invocations — POST /invocations {"stream": true} → SSE response
  4. Old route /api/chat/stream returns 404 — GET /api/chat/stream?q=test → 404
  5. Playground redirect at new path /invocations/playground — GET /invocations/playground → redirect
"""

import httpx
import pytest

# Import shared ServiceProcess fixture from e2e conftest.
from conftest import ServiceProcess

# ── Scenario 1: Health check endpoint unchanged ──────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario1_HealthCheck:
    """Verify /ping health check endpoint still works after refactor."""

    PORT = 18800

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


# ── Scenario 2: Sync invocation endpoint unchanged ───────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario2_SyncInvocation:
    """Verify POST /invocations endpoint still works after refactor."""

    PORT = 18801

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
            json={"message": "你好"},
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


# ── Scenario 3: SSE streaming on POST /invocations ───────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3_SSEStreamingNewPath:
    """Verify SSE streaming chat works on POST /invocations."""

    PORT = 18802

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_sse_streaming_new_path_responds(self, service_url):
        """POST /invocations with stream=true returns a response."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": "你好", "stream": True},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code < 500, (
            f"SSE streaming should not cause server error, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_streaming_content_type(self, service_url):
        """POST /invocations stream=true returns text/event-stream content-type."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": "hello", "stream": True},
            headers={"Accept": "text/event-stream"},
        )
        # Only verify content-type if the response succeeded (200)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, (
                f"Expected text/event-stream content-type, got: {content_type}"
            )

    def test_sse_empty_query_returns_400(self, service_url):
        """SSE streaming with empty message returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": "", "stream": True},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_missing_query_returns_400(self, service_url):
        """SSE streaming without message returns 400."""
        resp = httpx.post(f"{service_url}/invocations", json={"stream": True})
        assert resp.status_code == 400, (
            f"Expected 400 for missing message, got {resp.status_code}: {resp.text[:200]}"
        )


# ── Scenario 4: Old route /api/chat/stream returns 404 ───────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario4_OldRouteReturns404:
    """Verify the old /api/chat/stream route returns 404 after refactor."""

    PORT = 18803

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_old_api_chat_stream_returns_404(self, service_url):
        """GET /api/chat/stream?q=test should return 404 (route removed)."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=test")
        assert resp.status_code == 404, (
            f"Expected 404 for old /api/chat/stream route, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    def test_old_api_chat_stream_not_found_detail(self, service_url):
        """The 404 response should be a FastAPI 'Not Found' JSON error."""
        resp = httpx.get(f"{service_url}/api/chat/stream?q=test")
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}"
        )
        # FastAPI returns JSON detail for 404
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type, (
            f"Expected JSON error response, got content-type: {content_type}"
        )
        data = resp.json()
        assert "detail" in data, (
            f"Expected 'detail' in 404 error response: {data}"
        )

    def test_new_route_works_old_route_404(self, service_url):
        """POST /invocations stream works while old child routes are 404."""
        # Old route is 404
        resp_old = httpx.get(f"{service_url}/api/chat/stream?q=test")
        assert resp_old.status_code == 404, (
            f"Expected 404 from /api/chat/stream, got {resp_old.status_code}"
        )

        # New route works
        resp_new = httpx.post(
            f"{service_url}/invocations",
            json={"message": "test", "stream": True},
            headers={"Accept": "text/event-stream"},
        )
        assert resp_new.status_code < 500, (
            f"POST /invocations stream should work, "
            f"got {resp_new.status_code}: {resp_new.text[:200]}"
        )

        resp_old_child = httpx.get(f"{service_url}/invocations/stream?q=test")
        assert resp_old_child.status_code == 404, (
            f"Expected 404 from removed /invocations/stream, "
            f"got {resp_old_child.status_code}"
        )

        # Health check still works too
        resp_ping = httpx.get(f"{service_url}/ping")
        assert resp_ping.status_code == 200
        assert resp_ping.json() == {"status": "ok"}


# ── Scenario 5: Playground redirect at new path /invocations/playground ──


@pytest.mark.feature
@pytest.mark.slow
class TestScenario5_PlaygroundRedirectNewPath:
    """Verify /invocations/playground redirect works after refactor."""

    PORT = 18804

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start(env={"MAAS_API_KEY": "dummy-e2e-test-key"})
        yield sp.url
        sp.stop()

    def test_playground_new_path_redirects(self, service_url):
        """GET /invocations/playground returns 307 redirect to /invocations/playground/."""
        resp = httpx.get(
            f"{service_url}/invocations/playground", follow_redirects=False
        )
        assert resp.status_code in (302, 307), (
            f"Expected 302/307 redirect from /invocations/playground, "
            f"got {resp.status_code}"
        )
        location = resp.headers.get("location", "")
        assert location == "/invocations/playground/", (
            f"Expected redirect Location '/invocations/playground/', got: {location!r}"
        )

    def test_playground_trailing_slash_returns_chainlit(self, service_url):
        """GET /invocations/playground/ returns 200 with Chainlit HTML."""
        resp = httpx.get(
            f"{service_url}/invocations/playground/", follow_redirects=True
        )
        assert resp.status_code == 200, (
            f"Expected 200 from /invocations/playground/, got {resp.status_code}"
        )
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type, (
            f"Expected HTML from /invocations/playground/, "
            f"got content-type: {content_type}"
        )
        # Chainlit delivers an SPA shell with HTML structure
        html_lower = resp.text.lower()
        assert "<html" in html_lower or "<!doctype html>" in html_lower, (
            "Expected HTML structure in /invocations/playground/ response"
        )

    def test_playground_survives_multiple_requests(self, service_url):
        """Multiple requests to /invocations/playground/ do not crash the service."""
        for i in range(3):
            resp = httpx.get(
                f"{service_url}/invocations/playground/", follow_redirects=False
            )
            assert resp.status_code < 500, (
                f"Request {i}: /invocations/playground/ returned {resp.status_code}"
            )

        # After playground calls, health check should still work
        ping_resp = httpx.get(f"{service_url}/ping")
        assert ping_resp.status_code == 200
        assert ping_resp.json() == {"status": "ok"}
