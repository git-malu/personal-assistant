"""E2E tests for Feature 4 — Inbound Identity: unauthorized / fail-closed behavior.

Tests the fail-closed security model:
- Missing X-HW-AgentGateway-User-Id header → 401
- Empty X-HW-AgentGateway-User-Id header → 401
- extract_gateway_user_id function direct testing
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Test Fixture ─────────────────────────────────────────────────────────


@pytest.fixture
def auth_test_app():
    """Create FastAPI TestClient with mocked LLM and mocked AgentHandler.

    Mocks both init_chat_model (for lifespan) and AgentHandler (for requests),
    so the auth layer is tested without real LLM calls.
    """
    # Dummy API key to prevent config loading errors
    os.environ.setdefault("MAAS_API_KEY", "dummy-e2e-test-key")

    with patch("app.llm_config.init_chat_model", return_value=MagicMock()):
        from app.main import app

        # Create a mock handler that returns a fixed response
        mock_handler = MagicMock()
        mock_handler.handle.return_value = "Hello from mock agent"

        # Replace the app.state.agent_handler after app creation
        # (lifespan may overwrite it, so we set it after the client is ready)
        app.state.agent_handler = mock_handler

        # Also patch the AgentHandler class so that get_agent_handler()
        # returns our mock instead of a real instance
        with patch.object(app, "state", create=True):
            app.state.agent_handler = mock_handler
            client = TestClient(app, raise_server_exceptions=False)
            yield client


# ── Scenario 1: Missing header → 401 ─────────────────────────────────────


@pytest.mark.feature
def test_invocations_without_user_id_header_returns_401(auth_test_app):
    """POST /invocations without X-HW-AgentGateway-User-Id header returns 401."""
    resp = auth_test_app.post(
        "/invocations",
        json={"message": "Hello"},
        headers={"x-hw-agentarts-session-id": "test-session"},
    )
    assert resp.status_code == 401, (
        f"Expected 401 for missing X-HW-AgentGateway-User-Id header, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )
    data = resp.json()
    assert "detail" in data, f"Expected 'detail' in 401 response: {data}"
    assert (
        "Missing X-HW-AgentGateway-User-Id header" in data["detail"]
    ), (
        "Expected 'Missing X-HW-AgentGateway-User-Id header' "
        f"in detail, got: {data['detail']}"
    )


# ── Scenario 2: Empty header → 401 ───────────────────────────────────────


@pytest.mark.feature
def test_invocations_with_empty_user_id_header_returns_401(auth_test_app):
    """POST /invocations with empty X-HW-AgentGateway-User-Id returns 401."""
    resp = auth_test_app.post(
        "/invocations",
        json={"message": "Hello"},
        headers={
            "X-HW-AgentGateway-User-Id": "",
            "x-hw-agentarts-session-id": "test-session",
        },
    )
    assert resp.status_code == 401, (
        f"Expected 401 for empty user_id header, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.feature
def test_invocations_with_whitespace_user_id_header_returns_401(auth_test_app):
    """POST /invocations with whitespace-only X-HW-AgentGateway-User-Id returns 401."""
    resp = auth_test_app.post(
        "/invocations",
        json={"message": "Hello"},
        headers={
            "X-HW-AgentGateway-User-Id": "   ",
            "x-hw-agentarts-session-id": "test-session",
        },
    )
    assert resp.status_code == 401, (
        f"Expected 401 for whitespace user_id header, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )


# ── Scenario 3: Valid header continues past auth ─────────────────────────


@pytest.mark.feature
def test_invocations_with_valid_header_does_not_fail_auth(auth_test_app):
    """POST /invocations with valid X-HW-AgentGateway-User-Id passes auth check.

    Note: this tests that the auth check passes (no 401). The handler may return
    an error due to mock setup, but the auth layer specifically should not reject.
    """
    resp = auth_test_app.post(
        "/invocations",
        json={"message": "Hello"},
        headers={
            "X-HW-AgentGateway-User-Id": "dev-user",
            "x-hw-agentarts-session-id": "test-session",
        },
    )
    # Should NOT be 401 (auth rejected)
    assert resp.status_code != 401, (
        f"Valid header should not trigger 401, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )
    # Should NOT be 403
    assert resp.status_code != 403, (
        f"Valid header should not trigger 403, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )


# ── Scenario 4: extract_gateway_user_id direct testing ───────────────────


@pytest.mark.feature
class TestExtractGatewayUserId:
    """Direct unit tests for extract_gateway_user_id function."""

    @staticmethod
    def _make_mock_request(headers: dict[str, str]):
        """Create a mock FastAPI Request with given headers."""
        from unittest.mock import MagicMock

        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_request.headers.get.side_effect = (
            lambda key, default="": headers.get(key, default)
        )
        return mock_request

    def test_extract_returns_user_id_when_header_present(self):
        """extract_gateway_user_id returns the user_id when header is present."""
        from app.auth import extract_gateway_user_id

        mock_req = self._make_mock_request({"X-HW-AgentGateway-User-Id": "user-123"})
        result = extract_gateway_user_id(mock_req)
        assert result == "user-123", f"Expected 'user-123', got {result!r}"

    def test_extract_strips_whitespace_from_header(self):
        """extract_gateway_user_id strips whitespace from header value."""
        from app.auth import extract_gateway_user_id

        mock_req = self._make_mock_request(
            {"X-HW-AgentGateway-User-Id": "  user-456  "}
        )
        result = extract_gateway_user_id(mock_req)
        assert result == "user-456", f"Expected 'user-456', got {result!r}"

    def test_extract_raises_401_when_header_missing(self):
        """extract_gateway_user_id raises HTTPException(401) when header missing."""
        from app.auth import extract_gateway_user_id
        from fastapi import HTTPException

        mock_req = self._make_mock_request({})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(mock_req)
        assert exc_info.value.status_code == 401, (
            f"Expected status 401, got {exc_info.value.status_code}"
        )
        assert "Missing X-HW-AgentGateway-User-Id header" in exc_info.value.detail

    def test_extract_raises_401_when_header_empty(self):
        """extract_gateway_user_id raises HTTPException(401) when header is empty."""
        from app.auth import extract_gateway_user_id
        from fastapi import HTTPException

        mock_req = self._make_mock_request({"X-HW-AgentGateway-User-Id": ""})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(mock_req)
        assert exc_info.value.status_code == 401

    def test_extract_raises_401_when_header_whitespace_only(self):
        """extract_gateway_user_id raises 401 when header is whitespace."""
        from app.auth import extract_gateway_user_id
        from fastapi import HTTPException

        mock_req = self._make_mock_request({"X-HW-AgentGateway-User-Id": "   "})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(mock_req)
        assert exc_info.value.status_code == 401
