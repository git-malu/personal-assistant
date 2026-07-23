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
  2. Sync invocation content negotiation happens before the Agent boundary
  3. SSE streaming on /invocations — POST /invocations {"stream": true} → SSE response
  4. Old route /api/chat/stream returns 404 — GET /api/chat/stream?q=test → 404
  5. Playground redirect at new path /invocations/playground.
"""

import httpx
import pytest

# Import shared ServiceProcess fixture from e2e conftest.
from conftest import ServiceProcess

pytestmark = [pytest.mark.smoke]

# ── Scenario 1: Health check endpoint unchanged ──────────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario1HealthCheck:
    """Verify /ping health check endpoint still works after refactor."""

    PORT = 18800

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start()
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
class TestScenario2SyncInvocation:
    """Verify POST /invocations endpoint still works after refactor."""

    PORT = 18801

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start()
        yield sp.url
        sp.stop()

    def test_invocations_sync_rejects_sse_accept_before_agent(self, service_url):
        """Sync POST /invocations rejects an incompatible Accept header.

        This keeps smoke deterministic: it proves the live route is present and
        validates sync response negotiation without crossing into the real Agent
        or LLM boundary.
        """
        resp = httpx.post(
            f"{service_url}/invocations",
            json={
                "conversation_id": "0190e9fe-82b4-7000-8000-000000000001",
                "client_message_id": "0190e9fe-82b4-7000-8000-000000000002",
                "message": "你好",
            },
            headers={
                "Accept": "text/event-stream",
                "X-HW-AgentGateway-User-Id": "test-user",
                "x-hw-agentarts-session-id": "e2e-test-session",
            },
        )
        assert resp.status_code == 406, (
            f"Expected 406 before Agent boundary, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )
        assert resp.json()["detail"] == "Accept header must allow application/json"

    def test_invocations_empty_message_returns_400(self, service_url):
        """POST /invocations with empty message returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": ""},
            headers={
                "X-HW-AgentGateway-User-Id": "test-user",
                "x-hw-agentarts-session-id": "e2e-test-session",
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_invocations_missing_message_returns_400(self, service_url):
        """POST /invocations without message field returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={},
            headers={
                "X-HW-AgentGateway-User-Id": "test-user",
                "x-hw-agentarts-session-id": "e2e-test-session",
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for missing message, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )


# ── Scenario 3: SSE streaming on POST /invocations ───────────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario3SSEStreamingNewPath:
    """Verify SSE streaming chat works on POST /invocations."""

    PORT = 18802

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start()
        yield sp.url
        sp.stop()

    def test_sse_streaming_new_path_responds(self, service_url):
        """Streaming requests enforce the Feature 14 Conversation contract."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": "你好", "stream": True},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "conversation_id is required"

    def test_sse_streaming_content_type(self, service_url):
        """Pre-stream validation errors remain explicit JSON responses."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={
                "conversation_id": "0190e9fe-82b4-7000-8000-000000000001",
                "message": "hello",
                "stream": True,
            },
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "client_message_id is required"
        assert "application/json" in resp.headers.get("content-type", "")

    def test_sse_empty_query_returns_400(self, service_url):
        """SSE streaming with empty message returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"message": "", "stream": True},
            headers={
                "X-HW-AgentGateway-User-Id": "test-user",
                "x-hw-agentarts-session-id": "e2e-test-session",
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_sse_missing_query_returns_400(self, service_url):
        """SSE streaming without message returns 400."""
        resp = httpx.post(
            f"{service_url}/invocations",
            json={"stream": True},
            headers={
                "X-HW-AgentGateway-User-Id": "test-user",
                "x-hw-agentarts-session-id": "e2e-test-session",
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for missing message, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )


# ── Scenario 4: Old route /api/chat/stream returns 404 ───────────────────


@pytest.mark.feature
@pytest.mark.slow
class TestScenario4OldRouteReturns404:
    """Verify the old /api/chat/stream route returns 404 after refactor."""

    PORT = 18803

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start()
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
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        # FastAPI returns JSON detail for 404
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type, (
            f"Expected JSON error response, got content-type: {content_type}"
        )
        data = resp.json()
        assert "detail" in data, f"Expected 'detail' in 404 error response: {data}"

    def test_new_route_works_old_route_404(self, service_url):
        """The new route validates requests while old child routes are 404."""
        # Old route is 404
        resp_old = httpx.get(f"{service_url}/api/chat/stream?q=test")
        assert resp_old.status_code == 404, (
            f"Expected 404 from /api/chat/stream, got {resp_old.status_code}"
        )

        # New route owns validation at the expected path.
        resp_new = httpx.post(
            f"{service_url}/invocations",
            json={"message": "test", "stream": True},
            headers={"Accept": "text/event-stream"},
        )
        assert resp_new.status_code == 400
        assert resp_new.json()["detail"] == "conversation_id is required"

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
class TestScenario5PlaygroundRedirectNewPath:
    """Verify /invocations/playground redirect works after refactor."""

    PORT = 18804

    @pytest.fixture
    def service_url(self):
        """Start the service and return its base URL."""
        sp = ServiceProcess(port=self.PORT)
        sp.start()
        yield sp.url
        sp.stop()

    def test_playground_new_path_redirects(self, service_url):
        """GET /invocations/playground redirects to the trailing-slash path."""
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
