"""Unit tests for app.auth — Gateway identity extraction.

Feature 4: Inbound Identity — fail-closed enforcement of
X-HW-AgentGateway-User-Id header.
"""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import extract_gateway_user_id


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
    """Tests for extract_gateway_user_id()."""

    def test_returns_user_id_when_header_present(self) -> None:
        """Header X-HW-AgentGateway-User-Id: test-user-123 → returns 'test-user-123'."""
        request = _make_request({"X-HW-AgentGateway-User-Id": "test-user-123"})
        result = extract_gateway_user_id(request)
        assert result == "test-user-123"

    def test_raises_401_when_header_missing(self) -> None:
        """No X-HW-AgentGateway-User-Id header → HTTPException(401)."""
        request = _make_request({"other-header": "value"})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(request)
        assert exc_info.value.status_code == 401
        assert "Missing X-HW-AgentGateway-User-Id header" in exc_info.value.detail

    def test_raises_401_when_header_empty(self) -> None:
        """X-HW-AgentGateway-User-Id: '' → HTTPException(401)."""
        request = _make_request({"X-HW-AgentGateway-User-Id": ""})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(request)
        assert exc_info.value.status_code == 401

    def test_raises_401_when_header_whitespace_only(self) -> None:
        """X-HW-AgentGateway-User-Id: '   ' → HTTPException(401)."""
        request = _make_request({"X-HW-AgentGateway-User-Id": "   "})
        with pytest.raises(HTTPException) as exc_info:
            extract_gateway_user_id(request)
        assert exc_info.value.status_code == 401
