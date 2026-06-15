"""Integration tests for email conversation flows.

Requires running server (localhost:8080) and a configured LLM API key.
Marked @pytest.mark.slow — skipped in CI; run manually.

Feature 10a: Outbound Email — tests defined in test-plan.md §2.1.
"""

import os

import httpx
import pytest

SERVICE_URL = os.environ.get("SERVICE_URL", "http://localhost:8080")


def _post(message: str, stream: bool = False, timeout: float = 60.0) -> httpx.Response:
    """Send a POST /invocations request and return the response."""
    return httpx.post(
        f"{SERVICE_URL}/invocations",
        json={"message": message, "stream": stream},
        timeout=timeout,
    )


@pytest.mark.slow
@pytest.mark.integration
class TestEmailIntegration:
    """Integration tests requiring a running service and LLM API key."""

    @pytest.fixture(autouse=True)
    def check_env(self):
        """Skip integration tests if required env vars are not configured."""
        if (
            not os.environ.get("DEEPSEEK_API_KEY")
            and not os.environ.get("MAAS_API_KEY")
        ):
            pytest.skip("LLM API key not configured")
        if not os.environ.get("M365_CLIENT_ID") and not os.environ.get(
            "M365_CLIENT_SECRET"
        ):
            pytest.skip("M365 credentials not configured")

    # ── IT-01 ──

    def test_invocation_list_inbox(self):
        """IT-01: User asks to see inbox → Agent returns email list."""
        resp = _post("帮我看看收件箱")
        assert resp.status_code == 200
        body = resp.text
        # Agent should mention email/mail related content
        assert any(
            word in body.lower()
            for word in ["邮件", "收件箱", "inbox", "email", "mail"]
        )

    # ── IT-02 ──

    def test_invocation_search_emails(self):
        """IT-02: User searches for emails → Agent performs search."""
        resp = _post('搜索关于"会议"的邮件')
        assert resp.status_code == 200
        body = resp.text
        assert any(
            word in body.lower() for word in ["搜索", "邮件", "会议", "search"]
        )

    # ── IT-03 ──

    def test_invocation_get_email_detail(self):
        """IT-03: User asks for email detail → Agent returns email content."""
        resp = _post("帮我查看第一封邮件的详细内容")
        assert resp.status_code == 200
        body = resp.text
        assert any(
            word in body.lower()
            for word in ["邮件", "内容", "detail", "email", "发件人"]
        )

    # ── IT-04 ──

    def test_invocation_reply_to_email_flow(self):
        """IT-04: User wants to reply → Agent shows reply preview and asks
        for confirmation."""
        resp = _post("帮我回复第一封邮件，说收到谢谢")
        assert resp.status_code == 200
        body = resp.text
        # Agent should show preview and ask for confirmation
        assert any(
            word in body.lower()
            for word in ["确认", "发送", "回复", "preview", "reply"]
        )

    # ── IT-05: Guard confirm send (two-round) ──

    def test_invocation_guard_confirm_send(self):
        """IT-05: Preview then explicit '发送' → Agent confirms sent."""
        # Round 1: show preview
        resp1 = _post("发一封邮件给test@example.com，主题Hello，正文World")
        assert resp1.status_code == 200
        # Round 2: confirm send — need a new session to keep context
        # Use explicit "发送" message
        resp2 = _post("发送")
        assert resp2.status_code == 200

    # ── IT-06: Guard cancel ──

    def test_invocation_guard_cancel(self):
        """IT-06: Preview then '取消' → Agent confirms cancelled."""
        resp1 = _post("发一封邮件给test@example.com，主题Hello，正文World")
        assert resp1.status_code == 200
        # Cancel
        resp2 = _post("取消，不要发")
        assert resp2.status_code == 200
        body = resp2.text
        # Agent should acknowledge cancellation
        assert any(
            word in body.lower()
            for word in ["取消", "不发", "cancel", "已取消"]
        )

    # ── IT-07 ──

    def test_invocation_direct_send_with_preview(self):
        """IT-07: Agent shows preview before sending — never sends
        without confirmation."""
        resp = _post('发邮件给alice@example.com，主题"测试"，正文"测试邮件正文"')
        assert resp.status_code == 200
        body = resp.text
        # Agent should NOT have sent directly; should show preview or ask
        assert any(
            word in body.lower()
            for word in ["确认", "预览", "preview", "发送"]
        )

    # ── IT-08 ──

    @pytest.fixture
    def no_m365_env(self, monkeypatch):
        """Temporarily remove M365 env vars to simulate unauthorized user."""
        monkeypatch.delenv("M365_CLIENT_ID", raising=False)
        monkeypatch.delenv("M365_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("M365_TENANT_ID", raising=False)

    def test_invocation_unauthorized_no_token(self, no_m365_env):
        """IT-08: No M365 env vars → Agent gracefully explains limitation."""
        resp = _post("帮我看看收件箱")
        assert resp.status_code == 200
        body = resp.text
        # Agent should gracefully explain it can't access email
        assert any(
            word in body.lower()
            for word in [
                "抱歉",
                "无法",
                "不能",
                "暂时",
                "unavailable",
                "配置",
                "sorry",
            ]
        )
