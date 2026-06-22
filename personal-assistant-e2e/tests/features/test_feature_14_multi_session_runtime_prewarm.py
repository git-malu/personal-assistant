"""E2E contract tests for Feature 14 multi-Conversation execution."""

import json
from unittest.mock import patch

import httpx
import pytest


class ConversationAwareHandler:
    def __init__(self):
        self.calls: list[tuple[str, str, str | None]] = []

    async def handle(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ) -> str:
        self.calls.append((message, user_id, session_id))
        return f"{session_id}:{message}"

    async def handle_stream(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ):
        self.calls.append((message, user_id, session_id))
        yield f"data: {json.dumps({'token': session_id, 'done': False})}\n\n"
        yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"


@pytest.fixture
async def conversation_client():
    import app.main as app_main

    handler = ConversationAwareHandler()
    app_main.app.state.agent_handler = handler
    transport = httpx.ASGITransport(app=app_main.app)
    with patch.object(
        app_main,
        "assert_conversation_owner",
        return_value=None,
    ):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client, handler


@pytest.mark.feature
@pytest.mark.asyncio
async def test_conversation_id_not_runtime_session_drives_thread(
    conversation_client,
):
    client, handler = conversation_client
    conversation_id = "11111111-1111-4111-8111-111111111111"
    response = await client.post(
        "/invocations",
        json={
            "conversation_id": conversation_id,
            "client_message_id": "22222222-2222-4222-8222-222222222222",
            "message": "hello",
            "stream": True,
        },
        headers={
            "X-HW-AgentGateway-User-Id": "user-1",
            "x-hw-agentarts-session-id": "replaceable-runtime-session",
        },
    )

    assert response.status_code == 200
    assert handler.calls == [("hello", "user-1", conversation_id)]


@pytest.mark.feature
@pytest.mark.asyncio
async def test_two_conversations_remain_isolated_on_one_runtime(
    conversation_client,
):
    client, handler = conversation_client
    headers = {
        "X-HW-AgentGateway-User-Id": "user-1",
        "x-hw-agentarts-session-id": "shared-runtime-session",
    }
    for conversation_id in (
        "11111111-1111-4111-8111-111111111111",
        "33333333-3333-4333-8333-333333333333",
    ):
        response = await client.post(
            "/invocations",
            json={
                "conversation_id": conversation_id,
                "message": "hello",
                "stream": False,
            },
            headers=headers,
        )
        assert response.status_code == 200

    assert [call[2] for call in handler.calls] == [
        "11111111-1111-4111-8111-111111111111",
        "33333333-3333-4333-8333-333333333333",
    ]
