"""E2E tests for Feature 10a — Outbound Email: Microsoft 365 邮件处理.

Tests email conversation flows through the POST /invocations endpoint
with a mocked AgentHandler that returns canned email-specific responses.
Covers all 10 test scenarios defined in the test plan:

Scenario 1 — View Inbox (2 tests)
Scenario 2 — Search Emails (1 test)
Scenario 3 — Reply + Guard Confirmation Multi-turn (3 tests)
Scenario 4 — Cross-Session Identity (2 tests)
Scenario 5 — Integration-level / Real Service (2 tests)
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ═══════════════════════════════════════════════════════════════════════════
# Fake Email AgentHandler
# ═══════════════════════════════════════════════════════════════════════════


class FakeEmailHandler:
    """Simulates the backend email Agent with canned Chinese responses.

    Tracks per-session state for multi-turn Guard confirmation flows
    (reply + send). Returns Markdown-formatted email content so the
    existing Web Chat MarkdownText renderer displays it correctly.
    """

    def __init__(self):
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []
        self._session_state: dict[str, str] = {}

    # ── Non-streaming response templates ──────────────────────────────

    INBOX_RESPONSE = (
        "你有 3 封未读邮件：\n\n"
        "| 发件人 | 主题 | 时间 |\n"
        "|------|------|------|\n"
        "| 张三 | 项目进度更新 | 2026-06-14 |\n"
        "| 李四 | 会议邀请：Q2 复盘 | 2026-06-13 |\n"
        "| 王五 | 报销审批通知 | 2026-06-12 |"
    )

    SEARCH_RESPONSE = (
        "搜索到 2 封关于「项目进度」的邮件：\n\n"
        "| 发件人 | 主题 | 时间 |\n"
        "|------|------|------|\n"
        "| 张三 | 项目进度更新 | 2026-06-14 |\n"
        "| 赵六 | 项目进度阻塞风险 | 2026-06-10 |\n\n"
        "需要查看哪封邮件的详细内容？"
    )

    REPLY_PREVIEW = (
        "📧 **回复预览**\n\n"
        "**收件人**: 张三 <zhangsan@example.com>\n"
        "**主题**: Re: 项目进度更新\n"
        "**正文**:\n"
        "> 收到，感谢更新。我会根据最新进度调整计划。\n\n"
        "---\n"
        "是否确认发送此回复？（回复「发送」确认，回复「取消」放弃）"
    )

    REPLY_SENT = "邮件已回复 ✅"

    REPLY_CANCELLED = "已取消，不发送。"

    SEND_PREVIEW = (
        "📧 **新邮件预览**\n\n"
        "**收件人**: zhangsan@example.com\n"
        "**主题**: 你好\n"
        "**正文**:\n"
        "> 你好\n\n"
        "---\n"
        "需要发送吗？请回复「确认」发送，或「取消」放弃。"
    )

    GENERIC = "我是你的 Personal Assistant，可以帮你处理邮件、日程等事务。"

    # ── Streaming token lists ─────────────────────────────────────────

    STREAM_TOKENS_INBOX = [
        "你有 ", "3 封", "未读", "邮件", "：\n",
        "| 发件人 | 主题 | 时间 |\n",
        "| 张三 | 项目进度更新 | 2026-06-14 |",
    ]

    STREAM_TOKENS_SEARCH = [
        "搜索到 ", "2 封", "关于", "「项目进度」", "的邮件",
    ]

    STREAM_TOKENS_REPLY_PREVIEW = [
        "📧 ", "**回复预览**\n\n",
        "**收件人**: ", "张三 ", "<zhangsan@example.com>\n",
        "**主题**: ", "Re: 项目进度更新\n",
    ]

    STREAM_TOKENS_SEND_PREVIEW = [
        "📧 ", "**新邮件预览**\n\n",
        "**收件人**: ", "zhangsan@example.com\n",
        "**主题**: ", "你好\n",
    ]

    STREAM_TOKENS_REPLY_SENT = ["邮件已回复", " ✅"]

    STREAM_TOKENS_REPLY_CANCELLED = ["已取消，", "不发送。"]

    STREAM_TOKENS_GENERIC = ["Hello", " from", " stream"]

    # ── Handler: non-streaming ────────────────────────────────────────

    async def handle(
        self, message: str, user_id: str = "anonymous",
        session_id: str | None = None,
    ) -> str:
        self.handle_calls.append((message, user_id, session_id))
        sid = session_id or "default"
        state = self._session_state.get(sid)

        # ── Guard: awaiting reply confirmation ──
        if state == "awaiting_reply":
            self._session_state[sid] = _resolve_guard(
                message, sid, self._session_state,
                confirm_value="reply_sent", cancel_value="reply_cancelled",
            )
            return _guard_response(self._session_state[sid],
                                   sent=self.REPLY_SENT,
                                   cancelled=self.REPLY_CANCELLED,
                                   preview=self.REPLY_PREVIEW)

        # ── Guard: awaiting send confirmation ──
        if state == "awaiting_send":
            self._session_state[sid] = _resolve_guard(
                message, sid, self._session_state,
                confirm_value="send_confirmed", cancel_value="send_cancelled",
            )
            return _guard_response(self._session_state[sid],
                                   sent="邮件已发送 ✅",
                                   cancelled="已取消，不发送。",
                                   preview=self.SEND_PREVIEW)

        # ── Message routing ──
        if "收件箱" in message:
            return self.INBOX_RESPONSE

        if "搜索" in message or "查" in message:
            return self.SEARCH_RESPONSE

        if "回" in message and ("张三" in message or "邮件" in message):
            self._session_state[sid] = "awaiting_reply"
            return self.REPLY_PREVIEW

        if "发邮件" in message or "发一封" in message:
            self._session_state[sid] = "awaiting_send"
            return self.SEND_PREVIEW

        return self.GENERIC

    # ── Handler: SSE streaming ────────────────────────────────────────

    async def handle_stream(
        self, message: str, user_id: str = "anonymous",
        session_id: str | None = None,
    ):
        self.stream_calls.append((message, user_id, session_id))
        sid = session_id or "default"
        state = self._session_state.get(sid)

        # ── Guard: awaiting reply confirmation (streaming) ──
        if state == "awaiting_reply":
            new_state = _resolve_guard(
                message, sid, self._session_state,
                confirm_value="reply_sent", cancel_value="reply_cancelled",
            )
            self._session_state[sid] = new_state
            if new_state == "reply_sent":
                tokens = self.STREAM_TOKENS_REPLY_SENT
            elif new_state == "reply_cancelled":
                tokens = self.STREAM_TOKENS_REPLY_CANCELLED
            else:
                tokens = self.STREAM_TOKENS_REPLY_PREVIEW
        # ── Guard: awaiting send confirmation (streaming) ──
        elif state == "awaiting_send":
            new_state = _resolve_guard(
                message, sid, self._session_state,
                confirm_value="send_confirmed", cancel_value="send_cancelled",
            )
            self._session_state[sid] = new_state
            if new_state == "send_confirmed":
                tokens = ["邮件已发送", " ✅"]
            elif new_state == "send_cancelled":
                tokens = ["已取消，", "不发送。"]
            else:
                tokens = self.STREAM_TOKENS_GENERIC
        elif "收件箱" in message:
            tokens = self.STREAM_TOKENS_INBOX
        elif "搜索" in message or "查" in message:
            tokens = self.STREAM_TOKENS_SEARCH
        elif "回" in message and ("张三" in message or "邮件" in message):
            self._session_state[sid] = "awaiting_reply"
            tokens = self.STREAM_TOKENS_REPLY_PREVIEW
        elif "发邮件" in message or "发一封" in message:
            self._session_state[sid] = "awaiting_send"
            tokens = self.STREAM_TOKENS_SEND_PREVIEW
        else:
            tokens = self.STREAM_TOKENS_GENERIC

        for token in tokens:
            yield f'data: {json.dumps({"token": token, "done": False})}\n\n'
        yield f'data: {json.dumps({"token": "", "done": True})}\n\n'


# ── Guard helpers ─────────────────────────────────────────────────────────


_CONFIRM_TERMS = {"发送", "确认", "好的", "确认发送", "好的，发送", "是"}
_CANCEL_TERMS = {"取消", "不发送", "先不发了", "不要发", "否"}


def _resolve_guard(
    message: str,
    session_id: str,
    state_dict: dict,
    confirm_value: str,
    cancel_value: str,
) -> str:
    """Decode user intent in a Guard confirmation turn."""
    msg_lower = message.strip().lower()
    if msg_lower in _CONFIRM_TERMS:
        return confirm_value
    if msg_lower in _CANCEL_TERMS:
        return cancel_value
    # Ambiguous — stay in current state
    return state_dict.get(session_id, "")


def _guard_response(state: str, sent: str, cancelled: str,
                    preview: str) -> str:
    """Map guard state to response text."""
    if "sent" in state or "confirmed" in state:
        return sent
    if "cancelled" in state:
        return cancelled
    return preview


# ═══════════════════════════════════════════════════════════════════════════
# Fixture
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def email_test_client():
    """Create FastAPI TestClient with mocked LLM and FakeEmailHandler.

    Patches init_chat_model (for lifespan startup) and the AgentHandler class
    (so get_agent_handler() returns our fake handler). This allows testing
    the full FastAPI stack — routing, auth, SSE formatting, header handling —
    without real LLM calls or AgentArts Identity Service.
    """
    os.environ.setdefault("MAAS_API_KEY", "dummy-e2e-test-key")

    fake_handler = FakeEmailHandler()

    with patch("app.llm_config.init_chat_model", return_value=MagicMock()), \
         patch("app.agent_handler.AgentHandler", return_value=fake_handler):
        from app.main import app

        # Ensure the handler is set (lifespan will call get_agent_handler
        # which now returns our fake handler)
        app.state.agent_handler = fake_handler

        client = TestClient(app, raise_server_exceptions=False)
        yield client, fake_handler


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 1: View Inbox
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_list_inbox_non_streaming(email_test_client):
    """E2E-01: POST /invocations with "帮我看看收件箱" (stream=false).

    Returns 200 with email list in response body. Verifies handler
    received correct message, user_id, and session_id.
    """
    client, fake_handler = email_test_client

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": False},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "e2e-session-1",
        },
    )
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )

    data = resp.json()
    assert "response" in data, f"No 'response' key in: {data}"
    assert len(data["response"]) > 0, "Response should not be empty"
    assert "张三" in data["response"], (
        f"Expected sender '张三' in response, got: {data['response'][:200]}"
    )
    assert "邮件" in data["response"], (
        f"Expected email-related content, got: {data['response'][:200]}"
    )

    # Verify handler was called with correct params
    assert len(fake_handler.handle_calls) == 1, (
        f"Expected 1 handle call, got {len(fake_handler.handle_calls)}"
    )
    msg, user_id, session_id = fake_handler.handle_calls[0]
    assert msg == "帮我看看收件箱"
    assert user_id == "test-user", (
        f"Expected user_id='test-user', got {user_id!r}"
    )
    assert session_id == "e2e-session-1", (
        f"Expected session_id='e2e-session-1', got {session_id!r}"
    )


@pytest.mark.feature
def test_list_inbox_sse_streaming(email_test_client):
    """E2E-02: POST /invocations stream=true — SSE format + email content.

    Verifies content-type is text/event-stream, SSE headers, data: prefix
    on every line, valid JSON with 'done' field, and accumulated tokens
    contain email keywords.
    """
    client, fake_handler = email_test_client

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "e2e-session-1",
            "Accept": "text/event-stream",
        },
    )
    assert resp.status_code == 200, (
        f"Expected 200 for streaming, got {resp.status_code}: {resp.text[:300]}"
    )

    # Content-type
    content_type = resp.headers.get("content-type", "")
    assert "text/event-stream" in content_type, (
        f"Expected text/event-stream, got: {content_type}"
    )

    # SSE infrastructure headers
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("connection") == "keep-alive"

    # Verify stream_calls recorded
    assert len(fake_handler.stream_calls) == 1, (
        f"Expected 1 stream call, got {len(fake_handler.stream_calls)}"
    )
    msg, user_id, session_id = fake_handler.stream_calls[0]
    assert msg == "帮我看看收件箱"
    assert user_id == "test-user"

    # Parse SSE and validate format
    body = resp.text
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    assert len(lines) > 0, "SSE response should have data lines"

    accumulated = ""
    for line in lines:
        assert line.startswith("data: "), (
            f"SSE line should start with 'data: ': {line[:80]}"
        )
        payload = line[6:]  # strip "data: " prefix
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON in SSE: {payload[:100]}")
        assert "done" in data, f"SSE data missing 'done' field: {data}"
        if data.get("token") and not data.get("done"):
            accumulated += data["token"]

    # Last event must signal completion
    last_event = json.loads(lines[-1][6:])
    assert last_event["done"] is True, (
        f"Last SSE event should have done=True: {last_event}"
    )

    # Accumulated text must contain email keywords
    assert len(accumulated) > 0, "No tokens accumulated from SSE stream"
    assert any(
        kw in accumulated for kw in ("邮件", "未读", "发件人", "张三")
    ), f"Expected email keywords in stream: {accumulated[:200]}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2: Search Emails
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_search_emails(email_test_client):
    """E2E-03: POST /invocations with search query returns search results."""
    client, fake_handler = email_test_client

    resp = client.post(
        "/invocations",
        json={"message": "帮我查一下最近关于项目进度的邮件", "stream": False},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "e2e-session-search",
        },
    )
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )

    data = resp.json()
    assert "response" in data
    assert "项目进度" in data["response"], (
        f"Expected '项目进度' in search result, got: {data['response'][:200]}"
    )

    # Handler recorded the search request
    assert len(fake_handler.handle_calls) == 1
    msg, _, _ = fake_handler.handle_calls[0]
    assert "项目进度" in msg


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 3: Reply + Guard Confirmation (Multi-turn)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_reply_to_email_guard_confirm_flow(email_test_client):
    """E2E-04: Reply Guard — preview then confirm → sent.

    Round 1: "帮我回张三的邮件，说收到" → preview with recipient info.
    Round 2: "发送" → confirms, returns "邮件已回复".
    """
    client, fake_handler = email_test_client
    session_id = "e2e-guard-confirm"
    headers = {
        "X-HW-AgentGateway-User-Id": "test-user",
        "x-hw-agentarts-session-id": session_id,
    }

    # ── Round 1: Request reply → preview ──
    resp1 = client.post(
        "/invocations",
        json={"message": "帮我回张三的邮件，说收到"},
        headers=headers,
    )
    assert resp1.status_code == 200, (
        f"Round 1 failed: {resp1.status_code}: {resp1.text[:300]}"
    )
    data1 = resp1.json()
    response1 = data1["response"]
    assert "预览" in response1, (
        f"Round 1 should show reply preview, got: {response1[:200]}"
    )
    assert "张三" in response1, "Preview should include recipient name"
    assert "已回复" not in response1, "Preview must NOT contain '已回复'"
    assert "已发送" not in response1, "Preview must NOT contain '已发送'"
    assert "回复成功" not in response1, "Preview must NOT contain '回复成功'"

    # ── Round 2: Confirm → sent ──
    resp2 = client.post(
        "/invocations",
        json={"message": "发送"},
        headers=headers,
    )
    assert resp2.status_code == 200, (
        f"Round 2 failed: {resp2.status_code}: {resp2.text[:300]}"
    )
    data2 = resp2.json()
    response2 = data2["response"]
    assert ("已回复" in response2) or ("回复成功" in response2), (
        f"Round 2 should confirm reply sent, got: {response2[:200]}"
    )

    # Both turns tracked
    assert len(fake_handler.handle_calls) == 2


@pytest.mark.feature
def test_reply_to_email_cancel_flow(email_test_client):
    """E2E-05: Reply Guard — preview then cancel → not sent.

    Round 1: preview shown.
    Round 2: "取消" → returns cancellation, no "已回复".
    """
    client, fake_handler = email_test_client
    session_id = "e2e-guard-cancel"
    headers = {
        "X-HW-AgentGateway-User-Id": "test-user",
        "x-hw-agentarts-session-id": session_id,
    }

    # Round 1: Preview
    resp1 = client.post(
        "/invocations",
        json={"message": "帮我回张三的邮件，说收到"},
        headers=headers,
    )
    assert resp1.status_code == 200
    assert "预览" in resp1.json()["response"]

    # Round 2: Cancel
    resp2 = client.post(
        "/invocations",
        json={"message": "取消"},
        headers=headers,
    )
    assert resp2.status_code == 200
    response2 = resp2.json()["response"]
    assert ("已取消" in response2) or ("不发送" in response2), (
        f"Round 2 should confirm cancellation, got: {response2[:200]}"
    )
    assert "已回复" not in response2, (
        "Cancellation must NOT contain '已回复'"
    )


@pytest.mark.feature
def test_direct_send_shows_preview(email_test_client):
    """E2E-06: Direct send request shows preview, NOT "已发送".

    POST "帮zhangsan@example.com发邮件说你好" →
    shows recipient, confirmation prompt; must NOT auto-send.
    """
    client, fake_handler = email_test_client
    session_id = "e2e-send-preview"
    headers = {
        "X-HW-AgentGateway-User-Id": "test-user",
        "x-hw-agentarts-session-id": session_id,
    }

    resp = client.post(
        "/invocations",
        json={"message": "帮zhangsan@example.com发邮件说你好"},
        headers=headers,
    )
    assert resp.status_code == 200
    response = resp.json()["response"]

    # Must mention recipient or show send context
    assert ("zhangsan@example.com" in response) or ("收件人" in response), (
        f"Preview should mention recipient, got: {response[:200]}"
    )
    # Must ask for confirmation
    assert any(
        phrase in response for phrase in ("确认", "发送吗", "需要发送")
    ), f"Preview should ask for confirmation, got: {response[:200]}"
    # Must NOT auto-send
    assert "已发送" not in response, (
        "Preview must NOT contain '已发送' before confirmation"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 4: Cross-Session Identity
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_cross_session_no_reauth(email_test_client):
    """E2E-07: Two sessions, same user — both return email content.

    Verifies no "请先授权" / "需要登录 Microsoft 365" re-auth prompt
    appears. Each session is independent at the HTTP + handler layer.
    """
    client, fake_handler = email_test_client

    # Session A
    resp_a = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱"},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "session-a",
        },
    )
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert "邮件" in data_a["response"], (
        f"Session A should return email content: {data_a['response'][:200]}"
    )
    assert "请先授权" not in data_a["response"]
    assert "需要登录 Microsoft 365" not in data_a["response"]

    # Session B (same user, new session)
    resp_b = client.post(
        "/invocations",
        json={"message": "再帮我看看收件箱"},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "session-b",
        },
    )
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert "邮件" in data_b["response"], (
        f"Session B should return email content: {data_b['response'][:200]}"
    )
    assert "请先授权" not in data_b["response"]
    assert "需要登录 Microsoft 365" not in data_b["response"]

    # Both sessions tracked with correct session IDs
    assert len(fake_handler.handle_calls) == 2
    assert fake_handler.handle_calls[0][2] == "session-a"
    assert fake_handler.handle_calls[1][2] == "session-b"


@pytest.mark.feature
def test_cross_session_independent_state(email_test_client):
    """E2E-08: Session A cancels reply; Session B queries inbox normally.

    Guard state must be scoped per session — cancellation in Session A
    does not affect Session B's ability to read email.
    """
    client, fake_handler = email_test_client

    headers_a = {
        "X-HW-AgentGateway-User-Id": "test-user",
        "x-hw-agentarts-session-id": "session-a",
    }
    headers_b = {
        "X-HW-AgentGateway-User-Id": "test-user",
        "x-hw-agentarts-session-id": "session-b",
    }

    # Session A: reply preview → cancel
    r1 = client.post(
        "/invocations",
        json={"message": "帮我回张三的邮件，说收到"},
        headers=headers_a,
    )
    assert r1.status_code == 200
    assert "预览" in r1.json()["response"]

    r2 = client.post(
        "/invocations",
        json={"message": "取消"},
        headers=headers_a,
    )
    assert r2.status_code == 200
    assert ("已取消" in r2.json()["response"]) or \
           ("不发送" in r2.json()["response"])

    # Session B: query inbox — must still work
    r3 = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱"},
        headers=headers_b,
    )
    assert r3.status_code == 200
    data3 = r3.json()
    assert "邮件" in data3["response"], (
        f"Session B should work after Session A cancel: {data3['response'][:200]}"
    )
    assert "已取消" not in data3["response"], (
        "Session B must not see Session A's cancelled state"
    )

    # All three calls tracked
    assert len(fake_handler.handle_calls) == 3


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 3b: Tool-level confirm parameter behavior
# ═══════════════════════════════════════════════════════════════════════════


# ── Helpers for tool-level tests ────────────────────────────────────────────


def _make_passthrough_decorator(*args, **kwargs):
    """Mock require_access_token — returns function unchanged (no token injection)."""

    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(*fargs, **fkwargs):
            return await func(*fargs, **fkwargs)

        return wrapper

    return decorator


def _import_email_tools():
    """Import send_email and reply_to_email with agentarts.sdk mocked.

    agentarts-sdk is NOT installed in the E2E venv, so we mock it at the
    sys.modules level before the module is imported.
    """
    import sys
    from unittest.mock import MagicMock

    mock_agentarts_sdk = MagicMock()
    mock_agentarts_sdk.require_access_token = _make_passthrough_decorator
    mock_agentarts_sdk.IdentityClient = MagicMock()

    with patch.dict(sys.modules, {
        "agentarts": MagicMock(),
        "agentarts.sdk": mock_agentarts_sdk,
        "agentarts.sdk.identity": MagicMock(),
        "agentarts.sdk.identity.types": MagicMock(),
    }):
        from app.tools.email_tools import reply_to_email, send_email  # noqa: E402

        return send_email, reply_to_email


def _mock_graph_client():
    """Return a mock httpx.AsyncClient that returns 202 for POST calls."""
    from unittest.mock import AsyncMock, MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.text = ""

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


@pytest.mark.feature
def test_send_email_confirm_false_returns_preview():
    """E2E-11: send_email with confirm=False (default) returns preview.

    Verifies the tool-level Guard: calling send_email without confirm
    returns requires_confirmation=True and a preview, does NOT call Graph API.
    """
    send_email, _ = _import_email_tools()

    import asyncio

    result = asyncio.run(
        send_email(
            to=["test@example.com"],
            subject="Hello",
            body="This is a test email",
            confirm=False,
            access_token="fake-token",
        )
    )

    assert result["sent"] is False, (
        f"Expected sent=False, got: {result}"
    )
    assert result.get("requires_confirmation") is True, (
        f"Expected requires_confirmation=True, got: {result}"
    )
    assert "preview" in result, (
        f"Expected preview dict, got: {result}"
    )
    assert result["preview"]["to"] == ["test@example.com"]
    assert result["preview"]["subject"] == "Hello"
    assert "body_preview" in result["preview"]
    assert "请确认" in result.get("error", ""), (
        f"Expected Chinese confirmation prompt in error, got: {result}"
    )


@pytest.mark.feature
def test_reply_to_email_confirm_false_returns_preview():
    """E2E-12: reply_to_email with confirm=False returns preview.

    Verifies the tool-level Guard: calling reply_to_email without confirm
    returns requires_confirmation=True and a preview with email_id + body_preview.
    """
    _, reply_to_email = _import_email_tools()

    import asyncio

    result = asyncio.run(
        reply_to_email(
            email_id="AAMkAGFiYmNk",
            body="收到，感谢更新。",
            confirm=False,
            access_token="fake-token",
        )
    )

    assert result["sent"] is False, (
        f"Expected sent=False, got: {result}"
    )
    assert result.get("requires_confirmation") is True, (
        f"Expected requires_confirmation=True, got: {result}"
    )
    assert "preview" in result, (
        f"Expected preview dict, got: {result}"
    )
    assert result["preview"]["email_id"] == "AAMkAGFiYmNk"
    assert "body_preview" in result["preview"]
    assert "请确认" in result.get("error", ""), (
        f"Expected Chinese confirmation prompt in error, got: {result}"
    )


@pytest.mark.feature
def test_send_email_confirm_true_sends():
    """E2E-11b: send_email with confirm=True actually sends (calls Graph API).

    Verifies that when confirm=True, the function proceeds to call the Graph API
    and returns sent=True on 202 response.
    """
    from unittest.mock import patch

    send_email, _ = _import_email_tools()
    mock_client = _mock_graph_client()

    import asyncio

    with patch(
        "app.tools.email_tools._get_client", return_value=mock_client
    ), patch("app.tools.email_tools._ensure_provider", AsyncMock()):
        result = asyncio.run(
            send_email(
                to=["test@example.com"],
                subject="Hello",
                body="This is a test email",
                confirm=True,
                access_token="fake-token",
            )
        )

    assert result["sent"] is True, (
        f"Expected sent=True with confirm=True, got: {result}"
    )
    assert result["error"] is None, (
        f"Expected no error, got: {result}"
    )
    # Verify Graph API was called (POST to /sendMail)
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "/sendMail" in str(call_args), (
        f"Expected POST to /sendMail, got: {call_args}"
    )


@pytest.mark.feature
def test_send_email_input_validation():
    """E2E-13: send_email validates 'to' is non-empty.

    Calling send_email with an empty to list should return an error dict
    immediately, without calling Graph API.
    """
    send_email, _ = _import_email_tools()

    import asyncio

    result = asyncio.run(
        send_email(
            to=[],
            subject="Test",
            body="Body",
            access_token="fake-token",
        )
    )

    assert result["sent"] is False, (
        f"Expected sent=False for empty to, got: {result}"
    )
    assert "error" in result, (
        f"Expected error key, got: {result}"
    )
    assert "recipient" in result["error"].lower(), (
        f"Expected error about recipients, got: {result['error']}"
    )


@pytest.mark.feature
def test_reply_to_email_input_validation():
    """E2E-14: reply_to_email validates email_id and body are non-empty.

    Empty/whitespace-only email_id or body should return error dicts
    immediately, without calling Graph API.
    """
    _, reply_to_email = _import_email_tools()

    import asyncio

    # Empty email_id
    result = asyncio.run(
        reply_to_email(
            email_id="",
            body="Some reply",
            access_token="fake-token",
        )
    )
    assert result["sent"] is False, (
        f"Expected sent=False for empty email_id, got: {result}"
    )
    assert "email_id" in result.get("error", "").lower(), (
        f"Expected error about email_id, got: {result}"
    )

    # Empty body
    result = asyncio.run(
        reply_to_email(
            email_id="msg123",
            body="",
            access_token="fake-token",
        )
    )
    assert result["sent"] is False, (
        f"Expected sent=False for empty body, got: {result}"
    )
    assert "body" in result.get("error", "").lower(), (
        f"Expected error about body, got: {result}"
    )

    # Whitespace-only body
    result = asyncio.run(
        reply_to_email(
            email_id="msg123",
            body="   ",
            access_token="fake-token",
        )
    )
    assert result["sent"] is False
    assert "body" in result.get("error", "").lower()


@pytest.mark.feature
def test_search_emails_sse_streaming(email_test_client):
    """E2E-15: SSE streaming search returns valid SSE with search results.

    Similar to E2E-02 but with a search message. Verifies SSE format,
    content-type, and accumulated tokens contain search keywords.
    """
    client, fake_handler = email_test_client

    resp = client.post(
        "/invocations",
        json={"message": "帮我查一下项目进度的邮件", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "e2e-session-search-sse",
            "Accept": "text/event-stream",
        },
    )
    assert resp.status_code == 200, (
        f"Expected 200 for search SSE, got {resp.status_code}: {resp.text[:300]}"
    )

    # Content-type
    content_type = resp.headers.get("content-type", "")
    assert "text/event-stream" in content_type, (
        f"Expected text/event-stream, got: {content_type}"
    )

    # SSE infrastructure headers
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("connection") == "keep-alive"

    # Verify stream_calls recorded
    assert len(fake_handler.stream_calls) == 1, (
        f"Expected 1 stream call, got {len(fake_handler.stream_calls)}"
    )
    msg, user_id, session_id = fake_handler.stream_calls[0]
    assert "项目进度" in msg
    assert user_id == "test-user"

    # Parse SSE and validate format
    body = resp.text
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    assert len(lines) > 0, "SSE response should have data lines"

    accumulated = ""
    for line in lines:
        assert line.startswith("data: "), (
            f"SSE line should start with 'data: ': {line[:80]}"
        )
        payload = line[6:]
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON in SSE: {payload[:100]}")
        assert "done" in data, f"SSE data missing 'done' field: {data}"
        if data.get("token") and not data.get("done"):
            accumulated += data["token"]

    # Last event must signal completion
    last_event = json.loads(lines[-1][6:])
    assert last_event["done"] is True, (
        f"Last SSE event should have done=True: {last_event}"
    )

    # Accumulated text must contain search keywords
    assert len(accumulated) > 0, "No tokens accumulated from SSE stream"
    assert any(
        kw in accumulated for kw in ("搜索", "项目进度", "封")
    ), f"Expected search keywords in stream: {accumulated[:200]}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 5: Integration-level Tests (Subprocess-based)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
@pytest.mark.slow
def test_real_service_invocations_non_streaming():
    """E2E-09: Start real uvicorn, POST non-streaming — responds without crash.

    Skips if no LLM API key is set. Verifies the endpoint plumbing works
    even if email tools fail due to missing OAuth credentials.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MAAS_API_KEY")
    if not api_key:
        pytest.skip("No LLM API key set — skipping real service test")

    # Lazy import to avoid dependency when skipped
    from conftest import ServiceProcess  # noqa: E402

    PORT = 18900
    sp = ServiceProcess(port=PORT)
    try:
        sp.start(env={"MAAS_API_KEY": api_key, "DEEPSEEK_API_KEY": api_key})
        import httpx

        resp = httpx.post(
            f"http://127.0.0.1:{PORT}/invocations",
            json={"message": "帮我看看收件箱"},
            headers={
                "X-HW-AgentGateway-User-Id": "e2e-test-user",
                "x-hw-agentarts-session-id": "e2e-real-1",
            },
            timeout=60.0,
        )
        # Should respond (200 on success, 500 if email tools fail due to
        # missing M365 credentials — but should not crash the process)
        assert resp.status_code in (200, 500), (
            f"Real service responded with {resp.status_code}: {resp.text[:300]}"
        )
    finally:
        sp.stop()


@pytest.mark.feature
@pytest.mark.slow
def test_real_service_invocations_streaming():
    """E2E-10: Start real uvicorn, POST streaming — responds with SSE or error.

    Skips if no LLM API key. Verifies SSE content-type on success.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MAAS_API_KEY")
    if not api_key:
        pytest.skip("No LLM API key set — skipping real service test")

    from conftest import ServiceProcess  # noqa: E402

    PORT = 18901
    sp = ServiceProcess(port=PORT)
    try:
        sp.start(env={"MAAS_API_KEY": api_key, "DEEPSEEK_API_KEY": api_key})
        import httpx

        resp = httpx.post(
            f"http://127.0.0.1:{PORT}/invocations",
            json={"message": "帮我看看收件箱", "stream": True},
            headers={
                "Accept": "text/event-stream",
                "X-HW-AgentGateway-User-Id": "e2e-test-user",
                "x-hw-agentarts-session-id": "e2e-real-2",
            },
            timeout=60.0,
        )
        # Streaming endpoint should not cause 5xx
        assert resp.status_code < 500, (
            f"SSE streaming should not 5xx, got {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type, (
                f"Expected SSE content-type, got: {content_type}"
            )
    finally:
        sp.stop()
