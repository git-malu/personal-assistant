"""Unit tests for app.tools.email_tools — Microsoft 365 email tools.

Feature 10a: Outbound Email — tests all 5 tool functions
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.tools.email_tools as et

# ── Shared Fixtures ──


# The real @require_access_token decorator wraps each tool function at
# module import time.  Patching require_access_token after the fact has
# no effect because the wrapper is already bound.  Instead we replace the
# module-level names with their undecorated originals (accessible via
# __wrapped__ thanks to @functools.wraps in the decorator).

# Note: initial access_token=None protection is now handled by the
# `if not access_token` guard inside each function body rather than
# a separate decorator, so we only need to unwrap @require_access_token.

_TOOL_NAMES = [
    "list_emails",
    "get_email",
    "search_emails",
    "send_email",
    "reply_to_email",
]


@pytest.fixture(autouse=True)
def unwrap_email_tools():
    """Replace decorated tool functions with their undecorated originals.

    Each tool has one decorator: @require_access_token. We unwrap it
    to get the raw function for direct unit testing.
    """
    saved = {}
    for name in _TOOL_NAMES:
        wrapped = getattr(et, name)
        saved[name] = wrapped
        # Unwrap both decorator layers to reach the raw tool function
        raw = wrapped
        while hasattr(raw, "__wrapped__"):
            raw = raw.__wrapped__
        setattr(et, name, raw)
    yield
    for name, orig in saved.items():
        setattr(et, name, orig)


@pytest.fixture(autouse=True)
def reset_shared_client():
    """Reset shared HTTP client before/after each test."""
    import app.tools.email_tools as _et

    _et._client = None
    yield
    _et._client = None


# ── Helpers ──


def _make_resp(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Create a mock httpx Response with the given status and JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    resp.text = "Error detail"
    return resp


@contextmanager
def _mock_httpx(method: str, resp: MagicMock):
    """Mock _get_client() to return a mock client with the given method/response.

    Usage:
        with _mock_httpx("get", resp) as mock_client:
            await et.list_emails(...)
            mock_client.get.call_args  # inspect the call
    """
    mock_client = AsyncMock()
    getattr(mock_client, method).return_value = resp

    with patch("app.tools.email_tools._get_client", return_value=mock_client):
        yield mock_client


# ═══════════════════════════════════════════════════════════════
# list_emails tests
# ═══════════════════════════════════════════════════════════════


class TestListEmails:
    """Tests for list_emails()."""

    @pytest.mark.asyncio
    async def test_list_emails_returns_formatted_list(self):
        """UT-LE-01: returns formatted dict with emails list, count, folder."""
        resp = _make_resp(
            200,
            {
                "value": [
                    {
                        "id": "msg-1",
                        "subject": "Hello",
                        "from": {"emailAddress": {"name": "Alice"}},
                        "receivedDateTime": "2026-06-14T10:00:00Z",
                        "isRead": False,
                        "importance": "normal",
                        "bodyPreview": "Hi there",
                    }
                ]
            },
        )

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.list_emails(
                folder="inbox", limit=10, access_token="mock-token"
            )

        assert result["count"] == 1
        assert result["folder"] == "inbox"
        assert len(result["emails"]) == 1
        email = result["emails"][0]
        assert email["id"] == "msg-1"
        assert email["subject"] == "Hello"
        assert email["from"] == "Alice"
        assert email["receivedDateTime"] == "2026-06-14T10:00:00Z"
        assert email["isRead"] is False
        assert email["importance"] == "normal"
        assert email["bodyPreview"] == "Hi there"

    @pytest.mark.asyncio
    async def test_list_emails_default_folder_inbox(self):
        """UT-LE-02: default folder is inbox — verified in URL."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.list_emails(access_token="mock-token")
            call_url = mock_client.get.call_args[0][0]

        assert "mailFolders/inbox/messages" in call_url

    @pytest.mark.asyncio
    async def test_list_emails_custom_folder(self):
        """UT-LE-03: custom folder name appears in URL."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.list_emails(folder="sentitems", access_token="mock-token")
            call_url = mock_client.get.call_args[0][0]

        assert "mailFolders/sentitems/messages" in call_url

    @pytest.mark.asyncio
    async def test_list_emails_limit_parameter(self):
        """UT-LE-04: limit is passed as $top query param."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.list_emails(limit=5, access_token="mock-token")
            params = mock_client.get.call_args[1]["params"]

        assert params["$top"] == 5

    @pytest.mark.asyncio
    async def test_list_emails_empty_inbox(self):
        """UT-LE-05: empty inbox returns count=0 and empty list."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.list_emails(access_token="mock-token")

        assert result["emails"] == []
        assert result["count"] == 0
        assert result["folder"] == "inbox"

    @pytest.mark.asyncio
    async def test_list_emails_http_error(self):
        """UT-LE-06: HTTP error returns error dict (caught by try/except)."""
        resp = _make_resp(200, {"value": []})
        error = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        resp.raise_for_status.side_effect = error

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.list_emails(access_token="mock-token")

        assert "error" in result
        assert "500" in result["error"] or "邮件服务" in result["error"]

    @pytest.mark.asyncio
    async def test_list_emails_null_from_field(self):
        """UT-LE-07: null 'from' field falls back to 'Unknown'."""
        resp = _make_resp(
            200,
            {
                "value": [
                    {
                        "id": "msg-1",
                        "subject": "Test",
                        "from": None,
                        "receivedDateTime": "2026-06-14T10:00:00Z",
                        "isRead": False,
                        "importance": "normal",
                        "bodyPreview": "",
                    }
                ]
            },
        )

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.list_emails(access_token="mock-token")

        assert result["emails"][0]["from"] == "Unknown"


# ═══════════════════════════════════════════════════════════════
# get_email tests
# ═══════════════════════════════════════════════════════════════


class TestGetEmail:
    """Tests for get_email()."""

    @pytest.mark.asyncio
    async def test_get_email_returns_full_detail(self):
        """UT-GE-01: returns full email detail dict."""
        resp = _make_resp(
            200,
            {
                "id": "msg-1",
                "subject": "Hello",
                "body": {"content": "Hi Bob"},
                "from": {
                    "emailAddress": {
                        "name": "Alice",
                        "address": "alice@x.com",
                    }
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "name": "Bob",
                            "address": "bob@x.com",
                        }
                    }
                ],
                "ccRecipients": [],
                "receivedDateTime": "2026-06-14T10:00:00Z",
                "attachments": [],
            },
        )

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.get_email(email_id="msg-1", access_token="mock-token")

        assert result["id"] == "msg-1"
        assert result["subject"] == "Hello"
        assert result["body"] == "Hi Bob"
        assert result["from"] == {
            "name": "Alice",
            "address": "alice@x.com",
        }
        assert result["toRecipients"] == [{"name": "Bob", "address": "bob@x.com"}]
        assert result["ccRecipients"] == []
        assert result["receivedDateTime"] == "2026-06-14T10:00:00Z"
        assert result["attachments"] == []

    @pytest.mark.asyncio
    async def test_get_email_with_attachments(self):
        """UT-GE-02: email with attachments returns non-empty attachment list."""
        resp = _make_resp(
            200,
            {
                "id": "msg-1",
                "subject": "Report",
                "body": {"content": "See attached"},
                "from": {
                    "emailAddress": {
                        "name": "Alice",
                        "address": "alice@x.com",
                    }
                },
                "toRecipients": [],
                "ccRecipients": [],
                "receivedDateTime": "2026-06-14T10:00:00Z",
                "hasAttachments": True,
                "attachments": [
                    {
                        "name": "report.pdf",
                        "size": 1024,
                        "contentType": "application/pdf",
                    }
                ],
            },
        )

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.get_email(email_id="msg-1", access_token="mock-token")

        assert len(result["attachments"]) == 1
        att = result["attachments"][0]
        assert att["name"] == "report.pdf"
        assert att["size"] == 1024
        assert att["contentType"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_get_email_without_attachments(self):
        """UT-GE-03: email without attachments returns empty attachments list."""
        resp = _make_resp(
            200,
            {
                "id": "msg-1",
                "subject": "No attachments",
                "body": {"content": "Plain text"},
                "from": {
                    "emailAddress": {
                        "name": "Alice",
                        "address": "alice@x.com",
                    }
                },
                "toRecipients": [],
                "ccRecipients": [],
                "receivedDateTime": "2026-06-14T10:00:00Z",
                "attachments": [],
            },
        )

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.get_email(email_id="msg-1", access_token="mock-token")

        assert result["attachments"] == []

    @pytest.mark.asyncio
    async def test_get_email_not_found(self):
        """UT-GE-04: 404 error returns error dict (caught by try/except)."""
        resp = _make_resp(200, {})
        error = httpx.HTTPStatusError(
            "Not found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        resp.raise_for_status.side_effect = error

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.get_email(email_id="invalid", access_token="mock-token")

        assert "error" in result
        assert "get_email" in result["error"] or "404" in result["error"]


# ═══════════════════════════════════════════════════════════════
# search_emails tests
# ═══════════════════════════════════════════════════════════════


class TestSearchEmails:
    """Tests for search_emails()."""

    @pytest.mark.asyncio
    async def test_search_emails_returns_results(self):
        """UT-SE-01: returns formatted results dict."""
        resp = _make_resp(
            200,
            {
                "value": [
                    {
                        "id": "msg-2",
                        "subject": "Project Update",
                        "from": {"emailAddress": {"name": "Alice"}},
                        "receivedDateTime": "2026-06-14T10:00:00Z",
                        "isRead": False,
                        "bodyPreview": "The project is on track",
                    }
                ]
            },
        )

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.search_emails(query="project", access_token="mock-token")

        assert result["count"] == 1
        assert result["query"] == "project"
        assert len(result["results"]) == 1
        r = result["results"][0]
        assert r["id"] == "msg-2"
        assert r["subject"] == "Project Update"
        assert r["from"] == "Alice"
        assert r["bodyPreview"] == "The project is on track"

    @pytest.mark.asyncio
    async def test_search_emails_empty_results(self):
        """UT-SE-02: empty search returns count=0."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.search_emails(
                query="nonexistent", access_token="mock-token"
            )

        assert result["results"] == []
        assert result["count"] == 0
        assert result["query"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_search_emails_uses_search_param(self):
        """UT-SE-03: $search param is properly quoted (simple query)."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(query="hello world", access_token="mock-token")
            params = mock_client.get.call_args[1]["params"]

        assert params["$search"] == '"hello world"'

    @pytest.mark.asyncio
    async def test_search_emails_limit_parameter(self):
        """UT-SE-04: limit is passed as $top."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(query="test", limit=20, access_token="mock-token")
            params = mock_client.get.call_args[1]["params"]

        assert params["$top"] == 20

    @pytest.mark.asyncio
    async def test_search_emails_http_error(self):
        """UT-SE-05: HTTP error returns error dict (caught by try/except)."""
        resp = _make_resp(200, {"value": []})
        error = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        resp.raise_for_status.side_effect = error

        with _mock_httpx("get", resp) as _rc:  # noqa: F841
            result = await et.search_emails(query="test", access_token="mock-token")

        assert "error" in result
        assert "search_emails" in result["error"] or "400" in result["error"]

    @pytest.mark.asyncio
    async def test_search_emails_escapes_quotes(self):
        """UT-SE-06: double-quotes in query are escaped for KQL safety."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(query='hello "world"', access_token="mock-token")
            params = mock_client.get.call_args[1]["params"]

        # Double-quotes inside the query should be backslash-escaped
        assert params["$search"] == '"hello \\"world\\""'

    @pytest.mark.asyncio
    async def test_search_emails_no_orderby_param(self):
        """UT-SE-07: $orderby param is not sent (Graph API incompatibility)."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(query="test", access_token="mock-token")
            params = mock_client.get.call_args[1]["params"]

        assert "$orderby" not in params


# ═══════════════════════════════════════════════════════════════
# send_email tests
# ═══════════════════════════════════════════════════════════════


class TestSendEmail:
    """Tests for send_email()."""

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """UT-SND-01: 202 Accepted returns sent=True."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as _rc:  # noqa: F841
            result = await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="Hi",
                access_token="mock-token",
            )

        assert result["sent"] is True
        assert result["message_id"] is None
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_send_email_with_cc(self):
        """UT-SND-02: cc recipients included in request body."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="Hi",
                cc=["cc@x.com"],
                access_token="mock-token",
            )
            req_body = mock_client.post.call_args[1]["json"]

        assert "ccRecipients" in req_body["message"]
        assert req_body["message"]["ccRecipients"] == [
            {"emailAddress": {"address": "cc@x.com"}}
        ]

    @pytest.mark.asyncio
    async def test_send_email_failure(self):
        """UT-SND-03: non-202 status returns sent=False with error text."""
        resp = _make_resp(403)
        resp.text = "Forbidden: insufficient permissions"

        with _mock_httpx("post", resp) as _rc:  # noqa: F841
            result = await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="Hi",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["message_id"] is None
        assert "Forbidden" in result["error"]

    @pytest.mark.asyncio
    async def test_send_email_formats_recipients(self):
        """UT-SND-04: multiple to and cc are formatted correctly."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.send_email(
                to=["a@x.com", "b@x.com"],
                subject="Test",
                body="Body",
                cc=["c@x.com"],
                access_token="mock-token",
            )
            msg = mock_client.post.call_args[1]["json"]["message"]

        assert msg["toRecipients"] == [
            {"emailAddress": {"address": "a@x.com"}},
            {"emailAddress": {"address": "b@x.com"}},
        ]
        assert msg["ccRecipients"] == [
            {"emailAddress": {"address": "c@x.com"}},
        ]

    @pytest.mark.asyncio
    async def test_send_email_save_to_sent_items(self):
        """UT-SND-05: saveToSentItems is True in request body."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="Hi",
                access_token="mock-token",
            )
            req_body = mock_client.post.call_args[1]["json"]

        assert req_body["saveToSentItems"] is True

    @pytest.mark.asyncio
    async def test_send_email_content_type_text(self):
        """UT-SND-06: body contentType is 'Text'."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="plain text",
                access_token="mock-token",
            )
            msg = mock_client.post.call_args[1]["json"]["message"]

        assert msg["body"]["contentType"] == "Text"
        assert msg["body"]["content"] == "plain text"

    @pytest.mark.asyncio
    async def test_send_email_empty_to_list(self):
        """UT-SND-07: empty 'to' list returns error without HTTP call."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.send_email(
                to=[],
                subject="Hello",
                body="Hi",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["message_id"] is None
        assert "At least one recipient" in result["error"]
        mock_client.post.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# reply_to_email tests
# ═══════════════════════════════════════════════════════════════


class TestReplyToEmail:
    """Tests for reply_to_email()."""

    @pytest.mark.asyncio
    async def test_reply_to_email_success(self):
        """UT-RE-01: 202 Accepted returns sent=True."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as _rc:  # noqa: F841
            result = await et.reply_to_email(
                email_id="msg-1",
                body="Thanks",
                access_token="mock-token",
            )

        assert result["sent"] is True
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_reply_to_email_failure(self):
        """UT-RE-02: non-202 status returns sent=False with error."""
        resp = _make_resp(403)
        resp.text = "Forbidden"

        with _mock_httpx("post", resp) as _rc:  # noqa: F841
            result = await et.reply_to_email(
                email_id="msg-1",
                body="Thanks",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert "Forbidden" in result["error"]

    @pytest.mark.asyncio
    async def test_reply_to_email_calls_reply_endpoint(self):
        """UT-RE-03: calls /messages/{id}/reply with correct body."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.reply_to_email(
                email_id="msg-1",
                body="Thanks",
                access_token="mock-token",
            )
            call_url = mock_client.post.call_args[0][0]
            req_body = mock_client.post.call_args[1]["json"]

        assert "messages/msg-1/reply" in call_url
        assert req_body["message"]["body"]["contentType"] == "Text"
        assert req_body["message"]["body"]["content"] == "Thanks"

    @pytest.mark.asyncio
    async def test_reply_to_email_no_access_token(self):
        """UT-RE-04: access_token=None returns auth_required without HTTP call."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="msg-1",
                body="Thanks",
                access_token=None,
            )

        assert result["auth_required"] is True
        assert "Authorization pending" in result["error"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_to_email_formats_body(self):
        """UT-RE-05: body correctly wrapped in message structure."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.reply_to_email(
                email_id="msg-1",
                body="Hello world",
                access_token="mock-token",
            )
            req_body = mock_client.post.call_args[1]["json"]

        assert req_body == {
            "message": {
                "body": {
                    "contentType": "Text",
                    "content": "Hello world",
                }
            }
        }

    @pytest.mark.asyncio
    async def test_reply_to_email_empty_email_id(self):
        """UT-RE-08: empty email_id returns error without HTTP call."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="",
                body="Thanks",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert "email_id" in result["error"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_to_email_empty_body(self):
        """UT-RE-09: empty body returns error without HTTP call."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="msg-1",
                body="",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert "body" in result["error"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_to_email_whitespace_email_id(self):
        """UT-RE-10: whitespace-only email_id returns error."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="   ",
                body="Thanks",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert "email_id" in result["error"]
        mock_client.post.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# handle_auth_url — ContextVar-based auth URL delivery
# ═══════════════════════════════════════════════════════════════


class TestHandleAuthUrl:
    """Tests for handle_auth_url() with get_stream_writer."""

    @pytest.mark.asyncio
    async def test_handle_auth_url_writes_to_stream_writer(self):
        """UT-HAU-01: handle_auth_url calls get_stream_writer with auth URL."""
        writer_mock = MagicMock()
        with patch("app.tools.email_tools.get_stream_writer", return_value=writer_mock):
            await et.handle_auth_url("https://auth.example.com/login")

            writer_mock.assert_called_once()
            data = writer_mock.call_args[0][0]
            assert data["auth_url"] == "https://auth.example.com/login"
            assert data["auth_required"] is True
            assert data["provider"] == "m365-email-provider"

    @pytest.mark.asyncio
    async def test_handle_auth_url_runtime_error_graceful(self):
        """UT-HAU-02: handle_auth_url logs warning when get_stream_writer fails."""
        with (
            patch(
                "app.tools.email_tools.get_stream_writer",
                side_effect=RuntimeError("not in graph context"),
            ),
            patch("app.tools.email_tools.logger") as mock_logger,
        ):
            await et.handle_auth_url("https://auth.example.com/login")

            mock_logger.warning.assert_called_once()
            assert (
                "get_stream_writer unavailable" in mock_logger.warning.call_args[0][0]
            )


# ═══════════════════════════════════════════════════════════════
# Access token guard — if not access_token → auth_required
# ═══════════════════════════════════════════════════════════════


class TestAccessTokenGuard:
    """Tests for the `if not access_token` guard in each tool function."""

    @pytest.mark.asyncio
    async def test_list_emails_no_token_returns_auth_required(self):
        """UT-ATG-01: list_emails with access_token=None returns auth_required."""
        result = await et.list_emails(access_token=None)
        assert result["auth_required"] is True
        assert "Authorization pending" in result["error"]

    @pytest.mark.asyncio
    async def test_send_email_no_token_returns_auth_required(self):
        """UT-ATG-02: send_email with access_token=None returns auth_required."""
        result = await et.send_email(
            to=["bob@x.com"],
            subject="Test",
            body="Body",
            access_token=None,
        )
        assert result["auth_required"] is True
        assert "Authorization pending" in result["error"]

    def test_auth_required_response_format(self):
        """UT-ATG-03: _auth_required_response() returns correct dict format."""
        resp = et._auth_required_response()
        assert resp["auth_required"] is True
        assert "error" in resp
        assert "Authorization pending" in resp["error"]

    @pytest.mark.asyncio
    async def test_list_emails_with_token_proceeds_normally(self):
        """UT-ATG-04: with valid access_token, guard passes through to normal logic."""
        resp = _make_resp(200, {"value": []})
        with _mock_httpx("get", resp) as _rc:
            result = await et.list_emails(access_token="valid-token")
        assert result["count"] == 0
        assert "auth_required" not in result

    @pytest.mark.asyncio
    async def test_get_email_no_token_returns_auth_required(self):
        """UT-ATG-05: get_email with access_token=None returns auth_required."""
        result = await et.get_email(email_id="msg-1", access_token=None)
        assert result["auth_required"] is True

    @pytest.mark.asyncio
    async def test_search_emails_no_token_returns_auth_required(self):
        """UT-ATG-06: search_emails with access_token=None returns auth_required."""
        result = await et.search_emails(query="test", access_token=None)
        assert result["auth_required"] is True

    @pytest.mark.asyncio
    async def test_reply_to_email_no_token_returns_auth_required(self):
        """UT-ATG-07: reply_to_email with access_token=None returns auth_required."""
        result = await et.reply_to_email(
            email_id="msg-1",
            body="Thanks",
            access_token=None,
        )
        assert result["auth_required"] is True


# ═══════════════════════════════════════════════════════════════
# _format_tool_error — user-friendly error conversion
# ═══════════════════════════════════════════════════════════════


class TestToolErrorFormatting:
    """Tests for _format_tool_error() — user-friendly error conversion."""

    def test_format_timeout_error(self):
        """UT-ERR-01: TimeoutException → 中文超时提示."""
        import httpx

        result = et._format_tool_error(httpx.TimeoutException("timeout"), "list_emails")
        assert "请求超时" in result["error"]
        assert "list_emails" in result["error"]

    def test_format_connect_error(self):
        """UT-ERR-02: ConnectError → 中文连接失败提示."""
        import httpx

        result = et._format_tool_error(
            httpx.ConnectError("connection refused"), "get_email"
        )
        assert "无法连接到邮件服务器" in result["error"]
        assert "get_email" in result["error"]

    def test_format_429_rate_limit(self):
        """UT-ERR-03: HTTPStatusError 429 → 限流提示."""
        from unittest.mock import MagicMock

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 429
        exc = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=mock_response
        )
        result = et._format_tool_error(exc, "search_emails")
        assert "请求过于频繁" in result["error"]

    def test_format_503_unavailable(self):
        """UT-ERR-04: HTTPStatusError 503 → 服务不可用提示."""
        from unittest.mock import MagicMock

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 503
        exc = httpx.HTTPStatusError(
            "unavailable", request=MagicMock(), response=mock_response
        )
        result = et._format_tool_error(exc, "send_email")
        assert "邮件服务暂时不可用" in result["error"]

    def test_format_401_expired(self):
        """UT-ERR-05: HTTPStatusError 401 → 授权过期提示."""
        from unittest.mock import MagicMock

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        exc = httpx.HTTPStatusError(
            "unauthorized", request=MagicMock(), response=mock_response
        )
        result = et._format_tool_error(exc, "reply_to_email")
        assert "邮件功能未授权" in result["error"]

    def test_format_generic_exception_fallback(self):
        """UT-ERR-06: Unknown exception → 通用错误提示."""
        result = et._format_tool_error(ValueError("unexpected"), "list_emails")
        assert "操作失败" in result["error"]
        assert "list_emails" in result["error"]


# ═══════════════════════════════════════════════════════════════
