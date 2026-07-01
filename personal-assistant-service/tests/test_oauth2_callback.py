"""Tests for Calendar OAuth2 backend-owned callback completion."""

from contextlib import suppress
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.main import app
from app.oauth2_callback_store import OAuth2CallbackStore
from app.oauth2_state import (
    create_oauth2_state,
    verify_oauth2_state,
)
from app.settings import Settings


@pytest.fixture(autouse=True)
def clear_app_callback_store():
    with suppress(AttributeError, KeyError):
        delattr(app.state, "oauth2_callback_store")

    yield

    with suppress(AttributeError, KeyError):
        delattr(app.state, "oauth2_callback_store")


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def calendar_settings():
    return Settings(
        m365_calendar_provider_name="m365-calendar-provider",
    )


def _state(settings: Settings, user_id: str = "user-1") -> str:
    return create_oauth2_state(
        settings=settings,
        user_id=user_id,
        session_id="session-1",
        provider=settings.m365_calendar_provider_name,
    )


class _IdentityPermissionError(Exception):
    status_code = 403

    def __str__(self) -> str:
        return (
            "ClientRequestException - {status_code:403,"
            "error_code:AgentIdentityTokenVault.1007,"
            "error_msg:not authorized to perform: "
            "agentIdentity::completeResourceTokenAuth}"
        )


class FakeOAuth2CallbackStore:
    def __init__(self, begin_status: str = "started"):
        self.begin_status = begin_status
        self.begin_calls = []
        self.completed_calls = []
        self.clear_calls = []

    async def begin_completion(self, claims):
        self.begin_calls.append(claims)
        return self.begin_status

    async def mark_completed(self, claims):
        self.completed_calls.append(claims)

    async def clear_active(self, claims):
        self.clear_calls.append(claims)


def test_backend_callback_openapi_documents_html_and_json():
    operation = app.openapi()["paths"]["/auth/oauth2/callback/m365-calendar"]["get"]
    content = operation["responses"]["200"]["content"]

    assert set(content) == {"text/html", "application/json"}
    assert content["text/html"]["schema"] == {"type": "string"}
    assert content["application/json"]["schema"]["properties"]["status"] == {
        "description": "Backend-owned OAuth2 completion status.",
        "enum": ["complete", "failed", "pending"],
        "title": "Status",
        "type": "string",
    }


@pytest.mark.asyncio
async def test_backend_callback_completes_identity_with_authorization_user_token(
    client,
    calendar_settings,
):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore()
    state = _state(calendar_settings, user_id="state-user")

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
            headers={"Authorization": "Bearer callback-user-token"},
        )

    assert response.status_code == 200
    assert "授权完成" in response.text
    assert "m365-calendar-auth" in response.text
    identity_client.complete_resource_token_auth.assert_called_once()
    kwargs = identity_client.complete_resource_token_auth.call_args.kwargs
    assert kwargs["session_uri"] == "urn:uuid:test"
    assert kwargs["user_identifier"].user_token == "callback-user-token"
    assert kwargs["user_identifier"].user_id is None
    assert len(store.begin_calls) == 1
    assert len(store.completed_calls) == 1


@pytest.mark.asyncio
async def test_backend_callback_returns_json_for_local_fallback(
    client,
    calendar_settings,
):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore()
    state = _state(calendar_settings, user_id="state-user")

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer callback-user-token",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "type": "m365-calendar-auth",
        "requestId": state,
        "provider": "m365-calendar-provider",
        "status": "complete",
        "message": "日历授权已完成，可以关闭此窗口并重试刚才的问题。",
        "state": state,
    }


@pytest.mark.asyncio
async def test_callback_store_local_fallback_tracks_active_and_completed(
    calendar_settings,
):
    state = _state(calendar_settings, user_id="state-user")
    claims = verify_oauth2_state(
        state,
        settings=calendar_settings,
        expected_provider=calendar_settings.m365_calendar_provider_name,
    )
    store = OAuth2CallbackStore(settings=calendar_settings)

    assert await store.begin_completion(claims) == "started"
    assert await store.begin_completion(claims) == "active"

    await store.mark_completed(claims)

    assert await store.begin_completion(claims) == "completed"


@pytest.mark.asyncio
async def test_backend_callback_rejects_invalid_state(client, calendar_settings):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore()

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": "not-a-valid-state",
            },
        )

    assert response.status_code == 200
    assert "授权失败" in response.text
    assert "授权状态无效或已过期" in response.text
    identity_client.complete_resource_token_auth.assert_not_called()
    assert store.begin_calls == []


@pytest.mark.asyncio
async def test_backend_callback_completed_replay_does_not_call_identity(
    client,
    calendar_settings,
):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore(begin_status="completed")
    state = _state(calendar_settings, user_id="state-user")

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        first = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
        )
        second = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "授权完成" in second.text
    identity_client.complete_resource_token_auth.assert_not_called()
    assert len(store.begin_calls) == 2


@pytest.mark.asyncio
async def test_backend_callback_active_duplicate_does_not_call_identity(
    client,
    calendar_settings,
):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore(begin_status="active")
    state = _state(calendar_settings, user_id="state-user")

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
        )

    assert response.status_code == 200
    assert "授权处理中" in response.text
    identity_client.complete_resource_token_auth.assert_not_called()


@pytest.mark.asyncio
async def test_backend_callback_reports_oauth_error(client, calendar_settings):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore()

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "error": "access_denied",
                "error_description": "用户取消授权",
                "state": "signed-state",
            },
        )

    assert response.status_code == 200
    assert "授权失败" in response.text
    assert "用户取消授权" in response.text
    identity_client.complete_resource_token_auth.assert_not_called()
    assert store.begin_calls == []


@pytest.mark.asyncio
async def test_backend_callback_reports_identity_permission_error(
    client,
    calendar_settings,
):
    identity_client = MagicMock()
    identity_client.complete_resource_token_auth.side_effect = (
        _IdentityPermissionError()
    )
    store = FakeOAuth2CallbackStore()
    state = _state(calendar_settings, user_id="state-user")

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
            headers={"Authorization": "Bearer callback-user-token"},
        )

    assert response.status_code == 200
    assert "授权失败" in response.text
    assert "日历授权服务权限尚未配置完成" in response.text
    assert len(store.clear_calls) == 1


@pytest.mark.asyncio
async def test_backend_callback_requires_authorization_user_token(
    client,
    calendar_settings,
):
    identity_client = MagicMock()
    store = FakeOAuth2CallbackStore()
    state = _state(calendar_settings, user_id="state-user")

    with (
        patch("app.main.get_settings", return_value=calendar_settings),
        patch("app.main.IdentityClient", return_value=identity_client),
    ):
        app.state.oauth2_callback_store = store
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={
                "session_uri": "urn:uuid:test",
                "state": state,
            },
        )

    assert response.status_code == 200
    assert "授权失败" in response.text
    assert "请保持原聊天窗口处于登录状态" in response.text
    identity_client.complete_resource_token_auth.assert_not_called()
    assert len(store.clear_calls) == 1


@pytest.mark.asyncio
async def test_backend_callback_rejects_invalid_bff_secret(client):
    settings = Settings(
        m365_calendar_provider_name="m365-calendar-provider",
        oauth2_callback_bff_secret="expected-secret",
    )

    with patch("app.main.get_settings", return_value=settings):
        response = await client.get(
            "/auth/oauth2/callback/m365-calendar",
            params={"session_uri": "urn:uuid:test", "state": "signed-state"},
            headers={"x-pa-oauth2-callback-secret": "wrong-secret"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "invalid OAuth2 callback secret"
