"""Unit tests for app.tools.email_tools — mock Graph API responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.tools.email_tools import (
    _extract_body,
    _extract_sender,
    _graph_error,
    _truncate_preview,
    draft_reply,
    get_email,
    list_emails,
    search_emails,
    send_email,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_async_client():
    """Mock httpx.AsyncClient to control Graph API responses.

    Uses patch() without a replacement class so mock_class is a MagicMock.
    Configures the return_value (the instance) with AsyncMock get/post
    and proper __aenter__/__aexit__ for async context manager support.
    """
    with patch("app.tools.email_tools.httpx.AsyncClient") as mock_class:
        mock_instance = MagicMock()
        mock_instance.get = AsyncMock()
        mock_instance.post = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_class.return_value = mock_instance
        yield mock_class


def _make_response(json_data, status_code=200):
    """Helper: create a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _mock_email(
    idx=1,
    subject="测试邮件",
    sender_name="张三",
    sender_email="zhangsan@example.com",
    received="2026-06-09T10:00:00Z",
    is_read=False,
    body_preview="这是一封测试邮件",
):
    return {
        "id": f"AAMkAG{idx:08d}",
        "subject": subject,
        "from": {
            "emailAddress": {"name": sender_name, "address": sender_email}
        },
        "receivedDateTime": received,
        "isRead": is_read,
        "bodyPreview": body_preview,
    }


# ── list_emails tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_emails_returns_formatted_list(mock_async_client):
    """Mock Graph API returning an email list — verify formatted output."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {
            "value": [
                _mock_email(1, "项目进度", "张三", "zhang@example.com"),
                _mock_email(2, "会议纪要", "李四", "lisi@example.com", is_read=True),
            ]
        }
    )

    result = await list_emails(folder="inbox", limit=10, access_token="fake-token")

    assert "emails" in result
    assert len(result["emails"]) == 2
    assert result["emails"][0]["subject"] == "项目进度"
    assert result["emails"][0]["from"] == "张三 <zhang@example.com>"
    assert result["emails"][0]["is_read"] is False
    assert "preview" in result["emails"][0]
    assert result["emails"][1]["is_read"] is True


@pytest.mark.asyncio
async def test_list_emails_empty_inbox(mock_async_client):
    """Mock Graph API returning an empty list."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response({"value": []})

    result = await list_emails(folder="inbox", limit=10, access_token="fake-token")

    assert "emails" in result
    assert result["emails"] == []


@pytest.mark.asyncio
async def test_list_emails_graph_error(mock_async_client):
    """Mock Graph API returning 401 — verify error dict."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {"error": {"message": "Unauthorized"}}, status_code=401
    )

    result = await list_emails(access_token="wrong-token")

    assert "error" in result
    assert result["status_code"] == 401


# ── get_email tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_email_returns_full_detail(mock_async_client):
    """Mock Graph API returning a full email with body and attachments."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {
            "id": "AAMkAG12345678",
            "subject": "项目进度同步",
            "from": {
                "emailAddress": {"name": "张三", "address": "zhang@example.com"}
            },
            "toRecipients": [
                {"emailAddress": {"name": "我", "address": "me@example.com"}}
            ],
            "ccRecipients": [
                {"emailAddress": {"name": "领导", "address": "boss@example.com"}}
            ],
            "body": {"contentType": "Text", "content": "请查收项目进度报告。"},
            "receivedDateTime": "2026-06-09T10:00:00Z",
            "hasAttachments": True,
            "attachments": [
                {"name": "report.pdf", "contentType": "application/pdf", "size": 102400}
            ],
        }
    )

    result = await get_email("AAMkAG12345678", access_token="fake-token")

    assert result["id"] == "AAMkAG12345678"
    assert result["subject"] == "项目进度同步"
    assert result["from"] == "张三 <zhang@example.com>"
    assert result["to"] == [{"name": "我", "email": "me@example.com"}]
    assert result["cc"] == [{"name": "领导", "email": "boss@example.com"}]
    assert result["received"] == "2026-06-09T10:00:00Z"
    assert len(result["attachments"]) == 1
    assert result["attachments"][0]["name"] == "report.pdf"


@pytest.mark.asyncio
async def test_get_email_no_attachments(mock_async_client):
    """Mock email without attachments."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {
            "id": "AAMkAG0001",
            "subject": "无附件邮件",
            "from": {"emailAddress": {"name": "测试", "address": "test@example.com"}},
            "toRecipients": [],
            "ccRecipients": [],
            "body": {"contentType": "Text", "content": "无附件"},
            "receivedDateTime": "2026-06-09T10:00:00Z",
            "hasAttachments": False,
            "attachments": [],
        }
    )

    result = await get_email("AAMkAG0001", access_token="fake-token")
    # hasAttachments is False, so attachments should be False (not a list)
    assert result["attachments"] is False


# ── search_emails tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_emails_with_query(mock_async_client):
    """Mock Graph API search returning matching emails."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {
            "value": [
                _mock_email(1, "项目进度", "张三", "zhang@example.com"),
                _mock_email(2, "项目预算", "李四", "lisi@example.com"),
            ]
        }
    )

    result = await search_emails("项目", access_token="fake-token")

    assert len(result["emails"]) == 2
    assert result["emails"][0]["subject"] == "项目进度"
    assert result["emails"][1]["subject"] == "项目预算"


@pytest.mark.asyncio
async def test_search_emails_no_results(mock_async_client):
    """Mock Graph API search returning no matches."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response({"value": []})

    result = await search_emails("不存在", access_token="fake-token")

    assert result["emails"] == []


# ── send_email tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_email_success(mock_async_client):
    """Mock Graph API accepting the sendMail request."""
    mock_client = mock_async_client.return_value
    mock_client.post.return_value = _make_response({}, status_code=202)

    result = await send_email(
        to="zhang@example.com",
        subject="测试",
        body="测试正文",
        access_token="fake-token",
    )

    assert result["sent"] is True


@pytest.mark.asyncio
async def test_send_email_with_cc(mock_async_client):
    """Mock send_email with CC recipient."""
    mock_client = mock_async_client.return_value
    mock_client.post.return_value = _make_response({}, status_code=202)

    result = await send_email(
        to="zhang@example.com",
        subject="测试",
        body="测试正文",
        cc="boss@example.com",
        access_token="fake-token",
    )

    assert result["sent"] is True
    # Verify the cc was included in the request
    call_args = mock_client.post.call_args
    payload = call_args[1]["json"]
    assert "ccRecipients" in payload["message"]
    cc_addr = payload["message"]["ccRecipients"][0]["emailAddress"]["address"]
    assert cc_addr == "boss@example.com"


@pytest.mark.asyncio
async def test_send_email_recipient_not_found(mock_async_client):
    """Mock Graph API returning 400 Bad Request."""
    mock_client = mock_async_client.return_value
    mock_client.post.return_value = _make_response(
        {"error": {"message": "Invalid recipient"}}, status_code=400
    )

    result = await send_email(
        to="nonexistent@example.com",
        subject="测试",
        body="测试正文",
        access_token="fake-token",
    )

    assert "error" in result
    assert result["status_code"] == 400


@pytest.mark.asyncio
async def test_send_email_multiple_recipients(mock_async_client):
    """Mock send_email with comma-separated recipients."""
    mock_client = mock_async_client.return_value
    mock_client.post.return_value = _make_response({}, status_code=202)

    result = await send_email(
        to="a@example.com, b@example.com",
        subject="群发",
        body="测试",
        access_token="fake-token",
    )

    assert result["sent"] is True
    call_args = mock_client.post.call_args
    recipients = call_args[1]["json"]["message"]["toRecipients"]
    assert len(recipients) == 2


# ── draft_reply tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_draft_reply_creates_draft(mock_async_client):
    """Mock createReply API returning a draft message."""
    mock_client = mock_async_client.return_value
    mock_client.post.return_value = _make_response(
        {
            "id": "AAMkAGdraft001",
            "subject": "Re: 项目进度同步",
            "toRecipients": [
                {"emailAddress": {"name": "张三", "address": "zhang@example.com"}}
            ],
            "body": {"contentType": "Text", "content": "收到，谢谢。"},
            "conversationId": "AAQkAGconv001",
        },
        status_code=201,
    )

    result = await draft_reply(
        "AAMkAGorig001", "收到，谢谢。", access_token="fake-token"
    )

    assert "draft" in result
    draft = result["draft"]
    assert draft["to"] == [{"name": "张三", "email": "zhang@example.com"}]
    assert draft["subject"] == "Re: 项目进度同步"
    assert draft["body"] == "收到，谢谢。"
    # Fix 1: original_email_id is now the input email_id param, not msg.get("id")
    assert draft["original_email_id"] == "AAMkAGorig001"
    assert draft["conversation_id"] == "AAQkAGconv001"
    assert draft["cc"] == []
    assert "note" in draft


@pytest.mark.asyncio
async def test_draft_reply_graph_error(mock_async_client):
    """Mock createReply returning error (e.g., original email not found)."""
    mock_client = mock_async_client.return_value
    mock_client.post.return_value = _make_response(
        {"error": {"message": "Resource not found"}}, status_code=404
    )

    result = await draft_reply(
        "nonexistent-id", "回复内容", access_token="fake-token"
    )

    assert "error" in result
    assert result["status_code"] == 404


# ── Unauthorized error tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthorized_error_handling(mock_async_client):
    """Mock 401 across any email tool — verify error dict, never raises."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {"error": {"message": "Access token expired"}}, status_code=401
    )

    result = await list_emails(access_token="expired-token")

    assert "error" in result
    assert result["status_code"] == 401
    assert "emails" not in result  # error dict, not success dict


# ── Additional HTTP error response tests ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_email_graph_error(mock_async_client):
    """Mock Graph API returning 404 for get_email — verify error dict."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {"error": {"message": "Message not found"}}, status_code=404
    )

    result = await get_email("nonexistent-id", access_token="fake-token")

    assert "error" in result
    assert result["status_code"] == 404


@pytest.mark.asyncio
async def test_search_emails_graph_error(mock_async_client):
    """Mock Graph API returning 500 for search_emails — verify error dict."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response(
        {"error": {"message": "Internal server error"}}, status_code=500
    )

    result = await search_emails("query", access_token="fake-token")

    assert "error" in result
    assert result["status_code"] == 500


@pytest.mark.asyncio
async def test_list_emails_custom_folder(mock_async_client):
    """Verify custom folder parameter is passed in the Graph API URL."""
    mock_client = mock_async_client.return_value
    mock_client.get.return_value = _make_response({"value": []})

    await list_emails(folder="sentitems", limit=5, access_token="fake-token")

    call_url = mock_client.get.call_args[0][0]
    assert "/mailFolders/sentitems/messages" in call_url


@pytest.mark.asyncio
async def test_send_email_network_error(mock_async_client):
    """Mock httpx.RequestError — verify error dict with descriptive message."""
    mock_client = mock_async_client.return_value
    mock_client.post.side_effect = httpx.RequestError("Connection timeout")

    result = await send_email(
        to="test@example.com",
        subject="Test",
        body="Body",
        access_token="fake-token",
    )

    assert "error" in result
    assert "HTTP 请求失败" in result["error"]


# ── Internal helper tests ──────────────────────────────────────────────────


def test_extract_sender_none_returns_unknown():
    """_extract_sender(None) returns '未知'."""
    assert _extract_sender(None) == "未知"


def test_extract_sender_empty_dict_returns_unknown():
    """_extract_sender({}) returns '未知'."""
    assert _extract_sender({}) == "未知"


def test_extract_sender_email_only():
    """_extract_sender with only email address — returns email alone."""
    sender = {"emailAddress": {"address": "test@example.com"}}
    assert _extract_sender(sender) == "test@example.com"


def test_extract_sender_name_only():
    """_extract_sender with only name — returns name alone."""
    sender = {"emailAddress": {"name": "张三"}}
    assert _extract_sender(sender) == "张三"


def test_truncate_preview_empty():
    """_truncate_preview('') returns ''."""
    assert _truncate_preview("") == ""


def test_truncate_preview_short():
    """Short preview is returned unchanged."""
    assert _truncate_preview("Hello") == "Hello"


def test_truncate_preview_long():
    """Preview > 150 chars gets truncated with '...'."""
    long_text = "A" * 200
    result = _truncate_preview(long_text)
    assert len(result) == 153  # 150 + "..."
    assert result.endswith("...")


def test_extract_body_empty():
    """_extract_body(None) returns ''."""
    assert _extract_body({}) == ""
    assert _extract_body(None) == ""


def test_extract_body_html():
    """_extract_body with HTML contentType prepends [html]."""
    body_obj = {"contentType": "html", "content": "<p>Hello</p>"}
    assert _extract_body(body_obj) == "[html] <p>Hello</p>"


def test_extract_body_text_no_prefix():
    """_extract_body with text contentType returns content unchanged."""
    body_obj = {"contentType": "Text", "content": "Plain text"}
    assert _extract_body(body_obj) == "Plain text"


def test_graph_error_non_json_response():
    """_graph_error handles non-JSON response body gracefully."""
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "<html>Server Error</html>"
    resp.json.side_effect = ValueError("not json")

    result = _graph_error(resp)
    assert result["error"] == "<html>Server Error</html>"
    assert result["status_code"] == 500
