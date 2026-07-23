"""Integration coverage for the Feature 14 trusted invocation identity contract."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)

import app.main as main_module
from app.invocations.models import InvocationResponse
from app.main import app


def _token(subject: str) -> str:
    def encode(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject})}.gateway-signature"


def _payload() -> dict[str, str]:
    return {
        "conversation_id": str(uuid4()),
        "client_message_id": str(uuid4()),
        "message": "Hello",
    }


@dataclass
class IdentityTestContext:
    client: httpx.AsyncClient
    prepared_user_ids: list[str]


@pytest.fixture
async def identity_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[IdentityTestContext]:
    prepared_user_ids: list[str] = []

    class FakeExecution:
        async def run_sync(self) -> InvocationResponse:
            return InvocationResponse(response="Hello from mock agent")

    class FakeInvocationService:
        def __init__(self, database: object) -> None:
            del database

        async def prepare(self, *, request: object, user_id: str, handler: object):
            del request, handler
            prepared_user_ids.append(user_id)
            return FakeExecution()

    monkeypatch.setattr(main_module, "InvocationService", FakeInvocationService)
    missing = object()
    previous_database = getattr(app.state, "database", missing)
    previous_handler = getattr(app.state, "agent_handler", missing)
    app.state.database = SimpleNamespace(available=True)
    app.state.agent_handler = object()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield IdentityTestContext(
                client=client,
                prepared_user_ids=prepared_user_ids,
            )
        finally:
            if previous_database is missing:
                delattr(app.state, "database")
            else:
                app.state.database = previous_database
            if previous_handler is missing:
                delattr(app.state, "agent_handler")
            else:
                app.state.agent_handler = previous_handler


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invocations_uses_jwt_sub_and_ignores_forged_user_header(
    identity_test_context: IdentityTestContext,
):
    response = await identity_test_context.client.post(
        "/invocations",
        json=_payload(),
        headers={
            "Authorization": f"Bearer {_token('trusted-user')}",
            ACCESS_TOKEN_HEADER: "gateway-workload-token",
            SESSION_HEADER: "runtime-cookie-session",
            USER_ID_HEADER: "attacker",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"response": "Hello from mock agent"}
    assert identity_test_context.prepared_user_ids == ["trusted-user"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invocations_with_trusted_sub_still_requires_session_header(
    identity_test_context: IdentityTestContext,
):
    response = await identity_test_context.client.post(
        "/invocations",
        json=_payload(),
        headers={
            "Authorization": f"Bearer {_token('trusted-user')}",
            ACCESS_TOKEN_HEADER: "gateway-workload-token",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == f"{SESSION_HEADER} header is required"
    assert identity_test_context.prepared_user_ids == []
