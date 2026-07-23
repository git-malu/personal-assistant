"""Manual deployed Gateway probe for Feature 14 route and method support."""

import os
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.manual, pytest.mark.feature]


@pytest.fixture
def deployed_client():
    base_url = os.getenv("PA_E2E_DEPLOYED_BASE_URL", "").rstrip("/")
    token = os.getenv("PA_E2E_BEARER_TOKEN", "").strip()
    if not base_url or not token:
        pytest.skip("PA_E2E_DEPLOYED_BASE_URL and PA_E2E_BEARER_TOKEN are required")
    if httpx.URL(base_url).scheme != "https":
        pytest.fail(
            "PA_E2E_DEPLOYED_BASE_URL must use HTTPS for Secure Cookie validation"
        )
    authorization = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    with httpx.Client(
        base_url=base_url,
        headers={
            "Authorization": authorization,
            "X-HW-AgentArts-Session-Id": "caller-spoof-session",
            "X-HW-AgentGateway-User-Id": "caller-spoof-user",
        },
        timeout=30.0,
    ) as client:
        yield client


def test_feature_14_gateway_custom_methods_and_session_routing(deployed_client):
    client = deployed_client
    conversation_id: str | None = None
    try:
        listed = client.get("/api/conversations?status=active&limit=1")
        assert listed.status_code == 200
        runtime_cookie = client.cookies.get("pa_runtime_session")
        assert runtime_cookie
        assert runtime_cookie != "caller-spoof-session"

        created = client.post(
            "/api/conversations",
            json={"title": f"G1 probe {uuid4()}"},
        )
        assert created.status_code == 201
        assert client.cookies.get("pa_runtime_session") == runtime_cookie
        assert not any(
            value.startswith("pa_runtime_session=")
            for value in created.headers.get_list("set-cookie")
        )
        conversation_id = created.json()["id"]

        assert client.get(f"/api/conversations/{conversation_id}").status_code == 200
        archived = client.patch(
            f"/api/conversations/{conversation_id}",
            json={"status": "archived"},
        )
        assert archived.status_code == 200
        assert client.cookies.get("pa_runtime_session") == runtime_cookie
        assert not any(
            value.startswith("pa_runtime_session=")
            for value in archived.headers.get_list("set-cookie")
        )

        invocation = client.post(
            "/invocations",
            json={
                "conversation_id": conversation_id,
                "client_message_id": str(uuid4()),
                "message": "G1 route probe without model execution",
                "stream": True,
            },
            headers={"Accept": "text/event-stream"},
        )
        assert invocation.status_code == 409
        assert invocation.json()["code"] == "conversation_archived"

        messages = client.get(f"/api/conversations/{conversation_id}/messages?limit=1")
        assert messages.status_code == 200
        assert messages.json()["items"] == []

        restored = client.patch(
            f"/api/conversations/{conversation_id}",
            json={"status": "active"},
        )
        assert restored.status_code == 200
        deleted = client.delete(f"/api/conversations/{conversation_id}")
        assert deleted.status_code == 204
        conversation_id = None
    finally:
        if conversation_id is not None:
            client.delete(f"/api/conversations/{conversation_id}")
