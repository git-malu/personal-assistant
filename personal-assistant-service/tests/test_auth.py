"""Unit tests for app.auth — Gateway identity extraction.

Feature 4: Inbound Identity — fail-closed enforcement of
Gateway-injected headers (User-Id, Session-Id, Workload-Access-Token).
Uses SDK header constants from agentarts.sdk.runtime.model.
"""

from unittest.mock import patch

import pytest
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from fastapi import HTTPException
from huaweicloudsdkcore.exceptions.exceptions import SdkException
from starlette.requests import Request

from app.auth import (
    ensure_jwt_workload_access_token,
    extract_authorization_user_token,
    extract_gateway_session_id,
    extract_gateway_user_id,
    prepare_jwt_workload_access_token,
    require_jwt_workload_access_token,
)
from app.settings import Settings


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


class TestExtractAuthorizationUserToken:
    """Tests for extracting the user JWT from Authorization."""

    def test_returns_bearer_token(self) -> None:
        request = _make_request({"Authorization": "Bearer jwt-token"})
        assert extract_authorization_user_token(request) == "jwt-token"

    def test_returns_raw_token_when_scheme_absent(self) -> None:
        request = _make_request({"Authorization": "jwt-token"})
        assert extract_authorization_user_token(request) == "jwt-token"

    def test_raises_401_when_header_missing(self) -> None:
        request = _make_request({"other-header": "value"})
        with pytest.raises(HTTPException) as exc_info:
            extract_authorization_user_token(request)
        assert exc_info.value.status_code == 401
        assert "Authorization" in exc_info.value.detail

    def test_raises_401_when_bearer_token_empty(self) -> None:
        request = _make_request({"Authorization": "Bearer "})
        with pytest.raises(HTTPException) as exc_info:
            extract_authorization_user_token(request)
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


class TestEnsureJwtWorkloadAccessToken:
    def test_gateway_wat_wins_without_local_exchange(self) -> None:
        request = _make_request(
            {
                ACCESS_TOKEN_HEADER: " gateway-wat ",
                "Authorization": "Bearer user-token",
            }
        )
        with (
            patch("app.auth.IdentityClient") as identity_client_cls,
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
        ):
            result = ensure_jwt_workload_access_token(request, wat_required=True)

        assert result == "gateway-wat"
        mock_set.assert_called_once_with("gateway-wat")
        identity_client_cls.assert_not_called()

    def test_local_authorization_token_exchanged_for_jwt_mode_wat(self) -> None:
        request = _make_request({"Authorization": "Bearer user-token"})
        settings = Settings(
            _env_file=None,
            agent_identity_local_jwt_workload_name="pa-local-jwt-workload",
        )

        with (
            patch("app.auth.IdentityClient") as identity_client_cls,
            patch("app.auth.get_settings", return_value=settings),
            patch("app.auth.get_region", return_value="cn-southwest-2"),
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
        ):
            client = identity_client_cls.return_value
            client.create_workload_access_token.return_value = "local-jwt-wat"
            result = ensure_jwt_workload_access_token(request, wat_required=True)

        assert result == "local-jwt-wat"
        identity_client_cls.assert_called_once_with(region="cn-southwest-2")
        client.create_workload_access_token.assert_called_once_with(
            "pa-local-jwt-workload",
            user_token="user-token",
        )
        mock_set.assert_called_once_with("local-jwt-wat")

    def test_missing_authorization_token_fails_when_wat_required(self) -> None:
        request = _make_request({"other-header": "value"})
        with (
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
            pytest.raises(HTTPException) as exc_info,
        ):
            ensure_jwt_workload_access_token(request, wat_required=True)

        assert exc_info.value.status_code == 401
        assert "Authorization user token" in exc_info.value.detail
        mock_set.assert_called_once_with(None)

    def test_missing_authorization_token_is_best_effort_when_wat_not_required(
        self,
    ) -> None:
        request = _make_request({"other-header": "value"})
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            assert prepare_jwt_workload_access_token(request) is None

        mock_set.assert_called_once_with(None)

    def test_local_wat_exchange_failure_raises_when_wat_required(self) -> None:
        request = _make_request({"Authorization": "Bearer user-token"})
        settings = Settings(
            _env_file=None,
            agent_identity_local_jwt_workload_name="pa-local-jwt-workload",
        )

        with (
            patch("app.auth.IdentityClient") as identity_client_cls,
            patch("app.auth.get_settings", return_value=settings),
            patch("app.auth.get_region", return_value="cn-southwest-2"),
            patch("app.auth.logger") as logger,
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
            pytest.raises(SdkException),
        ):
            client = identity_client_cls.return_value
            client.create_workload_access_token.side_effect = SdkException(
                "workload identity not found"
            )
            ensure_jwt_workload_access_token(request, wat_required=True)

        mock_set.assert_called_once_with(None)
        logger.error.assert_called_once()
        assert "ensure_local_jwt_workload_identity.py" in str(logger.error.call_args)

    def test_local_wat_exchange_failure_is_best_effort_when_wat_not_required(
        self,
    ) -> None:
        request = _make_request({"Authorization": "Bearer user-token"})
        settings = Settings(
            _env_file=None,
            agent_identity_local_jwt_workload_name="pa-local-jwt-workload",
        )

        with (
            patch("app.auth.IdentityClient") as identity_client_cls,
            patch("app.auth.get_settings", return_value=settings),
            patch("app.auth.get_region", return_value="cn-southwest-2"),
            patch("app.auth.logger") as logger,
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
        ):
            client = identity_client_cls.return_value
            client.create_workload_access_token.side_effect = SdkException(
                "invalid JWT client ID"
            )
            result = ensure_jwt_workload_access_token(request, wat_required=False)

        assert result is None
        mock_set.assert_called_once_with(None)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()
        assert "ensure_local_jwt_workload_identity.py" in str(logger.warning.call_args)

    def test_identity_client_construction_failure_is_best_effort_when_wat_not_required(
        self,
    ) -> None:
        request = _make_request({"Authorization": "Bearer user-token"})
        settings = Settings(
            _env_file=None,
            agent_identity_local_jwt_workload_name="pa-local-jwt-workload",
        )

        with (
            patch("app.auth.IdentityClient", side_effect=ValueError("missing creds")),
            patch("app.auth.get_settings", return_value=settings),
            patch("app.auth.get_region", return_value="cn-southwest-2"),
            patch("app.auth.logger") as logger,
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
        ):
            result = prepare_jwt_workload_access_token(request)

        assert result is None
        mock_set.assert_called_once_with(None)
        logger.warning.assert_called_once()
        logger.error.assert_not_called()
        assert "missing creds" in str(logger.warning.call_args)

    def test_identity_client_construction_failure_raises_when_wat_required(
        self,
    ) -> None:
        request = _make_request({"Authorization": "Bearer user-token"})
        settings = Settings(
            _env_file=None,
            agent_identity_local_jwt_workload_name="pa-local-jwt-workload",
        )

        with (
            patch("app.auth.IdentityClient", side_effect=ValueError("missing creds")),
            patch("app.auth.get_settings", return_value=settings),
            patch("app.auth.get_region", return_value="cn-southwest-2"),
            patch("app.auth.logger") as logger,
            patch(
                "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
            ) as mock_set,
            pytest.raises(ValueError, match="missing creds"),
        ):
            require_jwt_workload_access_token(request)

        mock_set.assert_called_once_with(None)
        logger.error.assert_called_once()
