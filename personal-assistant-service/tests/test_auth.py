"""Unit tests for app.auth — Gateway identity extraction.

Feature 4: Inbound Identity — fail-closed enforcement of
Gateway-injected headers (User-Id, Session-Id, Workload-Access-Token).
Uses SDK header constants from agentarts.sdk.runtime.model.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agentarts.sdk.runtime.model import (
    SESSION_HEADER,
    USER_ID_HEADER,
    ACCESS_TOKEN_HEADER,
)
from app.auth import (
    extract_gateway_session_id,
    extract_gateway_user_id,
)


def _make_request(headers: dict[str, str] | None = None) -> Request:
    """Build a Starlette Request with the given headers.

    Headers must be raw (b"key", b"value") tuples in the ASGI scope,
    so we convert from str.
    """
    raw_headers: list[tuple[bytes, bytes]] = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope: dict = {"type": "http", "headers": raw_headers}
    return Request(scope=scope)


class TestExtractGatewayUserId:
    """Tests for extract_gateway_user_id() using SDK USER_ID_HEADER."""

    def test_returns_user_id_when_header_present(self) -> None:
        """Header present → returns user_id and stores in context."""
        with patch("app.auth.AgentArtsRuntimeContext.set_user_id") as mock_set:
            request = _make_request({USER_ID_HEADER: "test-user-123"})
            result = extract_gateway_user_id(request)
            assert result == "test-user-123"
            mock_set.assert_called_once_with("test-user-123")

    def test_raises_401_when_header_missing(self) -> None:
        """No user-id header → HTTPException(401)."""
        request = _make_request({"other-header": "value"})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(request)
        assert exc_info.value.status_code == 401
        assert USER_ID_HEADER in exc_info.value.detail

    def test_raises_401_when_header_empty(self) -> None:
        """Empty user-id header → HTTPException(401)."""
        request = _make_request({USER_ID_HEADER: ""})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(request)
        assert exc_info.value.status_code == 401

    def test_raises_401_when_header_whitespace_only(self) -> None:
        """Whitespace-only user-id header → HTTPException(401)."""
        request = _make_request({USER_ID_HEADER: "   "})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(request)
        assert exc_info.value.status_code == 401


class TestExtractGatewaySessionId:
    """Tests for extract_gateway_session_id() using SDK SESSION_HEADER."""

    def test_returns_session_id_when_header_present(self) -> None:
        """Header present → returns session_id and stores in context."""
        with patch("app.auth.AgentArtsRuntimeContext.set_session_id") as mock_set:
            request = _make_request({SESSION_HEADER: "sess-abc-123"})
            result = extract_gateway_session_id(request)
            assert result == "sess-abc-123"
            mock_set.assert_called_once_with("sess-abc-123")

    def test_raises_400_when_header_missing(self) -> None:
        """No session-id header → HTTPException(400)."""
        request = _make_request({"other-header": "value"})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_session_id(request)
        assert exc_info.value.status_code == 400
        assert SESSION_HEADER in exc_info.value.detail

    def test_raises_400_when_header_empty(self) -> None:
        """Empty session-id header → HTTPException(400)."""
        request = _make_request({SESSION_HEADER: ""})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_session_id(request)
        assert exc_info.value.status_code == 400

    def test_raises_400_when_header_whitespace_only(self) -> None:
        """Whitespace-only session-id header → HTTPException(400)."""
        request = _make_request({SESSION_HEADER: "   "})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_session_id(request)
        assert exc_info.value.status_code == 400


class TestExtractWorkloadAccessToken:
    """Tests for extract_workload_access_token() using SDK ACCESS_TOKEN_HEADER."""

    def test_stores_token_when_header_present(self) -> None:
        """Header present with valid token →
        set_workload_access_token called with token value."""
        token_value = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-token"
        request = _make_request({ACCESS_TOKEN_HEADER: token_value})
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            from app.auth import extract_workload_access_token
            extract_workload_access_token(request)
            mock_set.assert_called_once_with(token_value)

    def test_sets_none_when_header_missing(self) -> None:
        """No header → set_workload_access_token called with None."""
        request = _make_request({"other-header": "value"})
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            from app.auth import extract_workload_access_token
            extract_workload_access_token(request)
            mock_set.assert_called_once_with(None)

    def test_sets_none_when_header_empty_string(self) -> None:
        """Header present but empty string →
        set_workload_access_token called with None."""
        request = _make_request({ACCESS_TOKEN_HEADER: ""})
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            from app.auth import extract_workload_access_token
            extract_workload_access_token(request)
            mock_set.assert_called_once_with(None)

    def test_strips_whitespace_and_stores_token(self) -> None:
        """Header with surrounding whitespace → stripped token stored."""
        request = _make_request({ACCESS_TOKEN_HEADER: "  valid-token  "})
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            from app.auth import extract_workload_access_token
            extract_workload_access_token(request)
            mock_set.assert_called_once_with("valid-token")

    def test_sets_none_when_header_whitespace_only(self) -> None:
        """Header with whitespace only →
        set_workload_access_token called with None."""
        request = _make_request({ACCESS_TOKEN_HEADER: "   "})
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            from app.auth import extract_workload_access_token
            extract_workload_access_token(request)
            mock_set.assert_called_once_with(None)
