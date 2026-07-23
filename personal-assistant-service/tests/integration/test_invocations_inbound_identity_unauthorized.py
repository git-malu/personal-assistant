"""Integration coverage for fail-closed trusted JWT invocation identity."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from agentarts.sdk.runtime.model import SESSION_HEADER, USER_ID_HEADER

from app.main import app


def _payload() -> dict[str, str]:
    return {
        "conversation_id": str(uuid4()),
        "client_message_id": str(uuid4()),
        "message": "Hello",
    }


@pytest.fixture
async def auth_test_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invocations_without_authorization_returns_401_even_with_user_header(
    auth_test_client: httpx.AsyncClient,
):
    response = await auth_test_client.post(
        "/invocations",
        json=_payload(),
        headers={
            SESSION_HEADER: "runtime-cookie-session",
            USER_ID_HEADER: "forged-user",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == ("A Gateway-validated Bearer token is required")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param("Basic credentials", id="wrong-scheme"),
        pytest.param("Bearer", id="missing-token"),
        pytest.param("Bearer not-a-jwt", id="invalid-segments"),
        pytest.param("Bearer e30.e30.gateway-signature", id="missing-sub"),
        pytest.param(
            "Bearer e30.eyJzdWIiOjEyM30.gateway-signature",
            id="non-string-sub",
        ),
    ],
)
async def test_invocations_with_malformed_authorization_returns_401(
    auth_test_client: httpx.AsyncClient,
    authorization: str,
):
    response = await auth_test_client.post(
        "/invocations",
        json=_payload(),
        headers={
            "Authorization": authorization,
            SESSION_HEADER: "runtime-cookie-session",
            USER_ID_HEADER: "forged-user",
        },
    )

    assert response.status_code == 401
    assert "Gateway-validated Bearer token" in response.json()["detail"]
