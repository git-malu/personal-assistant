"""Unit tests for app.tools.email_tools — Microsoft 365 email tools.

Feature 10a: Outbound Email — tests all 5 tool functions plus
provider initialization (ensure_provider_sync).
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.tools.email_tools as et
from app.tools.email_tools import AuthUrlRequired, _handle_provider_error

# ── Shared Fixtures ──


# The real @require_access_token decorator wraps each tool function at
# module import time.  Patching require_access_token after the fact has
# no effect because the wrapper is already bound.  Instead we replace the
# module-level names with their undecorated originals (accessible via
# __wrapped__ thanks to @functools.wraps in the decorator).

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

    Each tool has two decorators: @_handle_provider_error (outer) and
    @require_access_token (inner).  We unwrap both to get the raw function.
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
def mock_identity_client():
    """Mock IdentityClient to avoid real AgentArts calls."""
    with patch("app.tools.email_tools.IdentityClient") as mock:
        yield mock


@pytest.fixture(autouse=True)
def reset_provider_and_client():
    """Reset provider state and shared client before/after each test."""
    import app.tools.email_tools as _et

    _et._PROVIDER_INITIALIZED = False
    _et._client = None
    yield
    _et._PROVIDER_INITIALIZED = False
    _et._client = None


# ── Helpers ──


def _make_resp(
    status_code: int = 200, json_data: dict | None = None
) -> MagicMock:
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
            await et.list_emails(
                folder="sentitems", access_token="mock-token"
            )
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
        """UT-LE-06: HTTP error propagates as exception."""
        resp = _make_resp(200, {"value": []})
        error = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        resp.raise_for_status.side_effect = error

        with (
            _mock_httpx("get", resp) as _rc,  # noqa: F841
            pytest.raises(httpx.HTTPStatusError),
        ):
            await et.list_emails(access_token="mock-token")

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
            result = await et.get_email(
                email_id="msg-1", access_token="mock-token"
            )

        assert result["id"] == "msg-1"
        assert result["subject"] == "Hello"
        assert result["body"] == "Hi Bob"
        assert result["from"] == {
            "name": "Alice",
            "address": "alice@x.com",
        }
        assert result["toRecipients"] == [
            {"name": "Bob", "address": "bob@x.com"}
        ]
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
            result = await et.get_email(
                email_id="msg-1", access_token="mock-token"
            )

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
            result = await et.get_email(
                email_id="msg-1", access_token="mock-token"
            )

        assert result["attachments"] == []

    @pytest.mark.asyncio
    async def test_get_email_not_found(self):
        """UT-GE-04: 404 error propagates as exception."""
        resp = _make_resp(200, {})
        error = httpx.HTTPStatusError(
            "Not found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        resp.raise_for_status.side_effect = error

        with (
            _mock_httpx("get", resp) as _rc,  # noqa: F841
            pytest.raises(httpx.HTTPStatusError),
        ):
            await et.get_email(
                email_id="invalid", access_token="mock-token"
            )


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
            result = await et.search_emails(
                query="project", access_token="mock-token"
            )

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
            await et.search_emails(
                query="hello world", access_token="mock-token"
            )
            params = mock_client.get.call_args[1]["params"]

        assert params["$search"] == '"hello world"'

    @pytest.mark.asyncio
    async def test_search_emails_limit_parameter(self):
        """UT-SE-04: limit is passed as $top."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(
                query="test", limit=20, access_token="mock-token"
            )
            params = mock_client.get.call_args[1]["params"]

        assert params["$top"] == 20

    @pytest.mark.asyncio
    async def test_search_emails_http_error(self):
        """UT-SE-05: HTTP error propagates."""
        resp = _make_resp(200, {"value": []})
        error = httpx.HTTPStatusError(
            "Bad request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        resp.raise_for_status.side_effect = error

        with (
            _mock_httpx("get", resp) as _rc,  # noqa: F841
            pytest.raises(httpx.HTTPStatusError),
        ):
            await et.search_emails(
                query="test", access_token="mock-token"
            )

    @pytest.mark.asyncio
    async def test_search_emails_escapes_quotes(self):
        """UT-SE-06: double-quotes in query are escaped for KQL safety."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(
                query='hello "world"', access_token="mock-token"
            )
            params = mock_client.get.call_args[1]["params"]

        # Double-quotes inside the query should be backslash-escaped
        assert params["$search"] == '"hello \\"world\\""'

    @pytest.mark.asyncio
    async def test_search_emails_no_orderby_param(self):
        """UT-SE-07: $orderby param is not sent (Graph API incompatibility)."""
        resp = _make_resp(200, {"value": []})

        with _mock_httpx("get", resp) as mock_client:
            await et.search_emails(
                query="test", access_token="mock-token"
            )
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
                confirm=True,
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
                confirm=True,
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
                confirm=True,
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
                confirm=True,
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
                confirm=True,
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
                confirm=True,
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
                confirm=True,
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["message_id"] is None
        assert "At least one recipient" in result["error"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_email_confirm_false_returns_preview(self):
        """UT-SND-08: confirm=False returns preview, does not send."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="Hi",
                confirm=False,
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["requires_confirmation"] is True
        assert "preview" in result
        assert result["preview"]["to"] == ["bob@x.com"]
        assert result["preview"]["subject"] == "Hello"
        assert "body_preview" in result["preview"]
        assert "请确认" in result["error"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_email_confirm_default_is_false(self):
        """UT-SND-09: default confirm=False (not passed) returns preview."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.send_email(
                to=["bob@x.com"],
                subject="Hello",
                body="Hi",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["requires_confirmation"] is True
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
                confirm=True,
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
                confirm=True,
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
                confirm=True,
                access_token="mock-token",
            )
            call_url = mock_client.post.call_args[0][0]
            req_body = mock_client.post.call_args[1]["json"]

        assert "messages/msg-1/reply" in call_url
        assert req_body["message"]["body"]["contentType"] == "Text"
        assert req_body["message"]["body"]["content"] == "Thanks"

    @pytest.mark.asyncio
    async def test_reply_to_email_no_access_token(self):
        """UT-RE-04: function can be called with access_token=None."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            result = await et.reply_to_email(
                email_id="msg-1",
                body="Thanks",
                confirm=True,
                access_token=None,
            )
            headers = mock_client.post.call_args[1]["headers"]

        assert result["sent"] is True
        assert headers["Authorization"] == "Bearer None"

    @pytest.mark.asyncio
    async def test_reply_to_email_formats_body(self):
        """UT-RE-05: body correctly wrapped in message structure."""
        resp = _make_resp(202)

        with _mock_httpx("post", resp) as mock_client:
            await et.reply_to_email(
                email_id="msg-1",
                body="Hello world",
                confirm=True,
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
    async def test_reply_to_email_confirm_false_returns_preview(self):
        """UT-RE-06: confirm=False returns preview, does not send."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="msg-1",
                body="Thanks for the info",
                confirm=False,
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["requires_confirmation"] is True
        assert "preview" in result
        assert result["preview"]["email_id"] == "msg-1"
        assert "body_preview" in result["preview"]
        assert "请确认" in result["error"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_to_email_confirm_default_is_false(self):
        """UT-RE-07: default confirm=False returns preview."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="msg-1",
                body="Thanks",
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert result["requires_confirmation"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_to_email_empty_email_id(self):
        """UT-RE-08: empty email_id returns error without HTTP call."""
        with _mock_httpx("post", _make_resp(202)) as mock_client:
            result = await et.reply_to_email(
                email_id="",
                body="Thanks",
                confirm=True,
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
                confirm=True,
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
                confirm=True,
                access_token="mock-token",
            )

        assert result["sent"] is False
        assert "email_id" in result["error"]
        mock_client.post.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# _handle_provider_error decorator tests
# ═══════════════════════════════════════════════════════════════


class TestHandleProviderError:
    """Tests for the @_handle_provider_error decorator behavior.

    The autouse unwrap_email_tools fixture strips both decorator layers,
    so we manually re-apply @_handle_provider_error to test its error
    handling in isolation.
    """

    @pytest.mark.asyncio
    async def test_empty_exception_message_falls_back_to_type_name(self):
        """UT-HPE-01: empty str(e) falls back to exception type name."""
        @_handle_provider_error
        async def _failing_tool(access_token=None):
            raise RuntimeError()

        result = await _failing_tool()

        assert "RuntimeError" in result["error"]
        assert result["detail"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_empty_exception_message_uses_args(self):
        """UT-HPE-02: empty str(e) with non-empty e.args uses args."""
        @_handle_provider_error
        async def _failing_tool(access_token=None):
            raise RuntimeError("detail from args")

        result = await _failing_tool()

        assert "detail from args" in result["error"]

    @pytest.mark.asyncio
    async def test_whitespace_only_exception_message_falls_back(self):
        """UT-HPE-03: whitespace-only str(e) treated as empty."""
        @_handle_provider_error
        async def _failing_tool(access_token=None):
            e = RuntimeError()
            e.args = ("   ",)
            raise e

        result = await _failing_tool()

        assert "RuntimeError" in result["error"]

    @pytest.mark.asyncio
    async def test_write_tool_exception_includes_sent_false(self):
        """UT-HPE-04: send_email exception includes sent=False in result."""
        @_handle_provider_error
        async def send_email(access_token=None):
            raise RuntimeError()

        result = await send_email()

        assert result["sent"] is False
        assert "RuntimeError" in result["error"]

    @pytest.mark.asyncio
    async def test_reply_to_email_exception_includes_sent_false(self):
        """UT-HPE-05: reply_to_email exception includes sent=False in result."""
        @_handle_provider_error
        async def reply_to_email(access_token=None):
            raise RuntimeError()

        result = await reply_to_email()

        assert result["sent"] is False

    @pytest.mark.asyncio
    async def test_read_tool_exception_excludes_sent(self):
        """UT-HPE-06: list_emails exception does NOT include sent field."""
        @_handle_provider_error
        async def list_emails(access_token=None):
            raise RuntimeError()

        result = await list_emails()

        assert "sent" not in result

    @pytest.mark.asyncio
    async def test_auth_url_required_returns_auth_info(self):
        """UT-HPE-07: AuthUrlRequired returns auth_url and auth_required."""
        @_handle_provider_error
        async def _failing_tool(access_token=None):
            raise AuthUrlRequired("https://auth.example.com/login")

        result = await _failing_tool()

        assert result["auth_required"] is True
        assert "https://auth.example.com/login" in result["error"]

    @pytest.mark.asyncio
    async def test_provider_not_found_returns_setup_required(self):
        """UT-HPE-08: 'm365-provider' error returns setup_required."""
        @_handle_provider_error
        async def _failing_tool(access_token=None):
            raise Exception("m365-provider not found")

        result = await _failing_tool()

        assert result["setup_required"] is True

    @pytest.mark.asyncio
    async def test_provider_not_found_write_tool_includes_sent(self):
        """UT-HPE-09: 'm365-provider' error on write tool includes sent=False."""
        @_handle_provider_error
        async def send_email(access_token=None):
            raise Exception("m365-provider not found")

        result = await send_email()

        assert result["setup_required"] is True
        assert result["sent"] is False

    @pytest.mark.asyncio
    async def test_500_error_returns_retryable(self):
        """UT-HPE-10: 500 error returns retryable."""
        @_handle_provider_error
        async def _failing_tool(access_token=None):
            raise Exception("internal server error (500)")

        result = await _failing_tool()

        assert result["retryable"] is True


# ═══════════════════════════════════════════════════════════════
# Provider initialization tests
# ═══════════════════════════════════════════════════════════════


class TestProviderInit:
    """Tests for ensure_provider_sync()."""

    def test_provider_init_skips_if_env_vars_missing(
        self, mock_identity_client, monkeypatch
    ):
        """UT-PI-01: returns False when M365 env vars not set."""
        monkeypatch.delenv("M365_CLIENT_ID", raising=False)
        monkeypatch.delenv("M365_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("M365_TENANT_ID", raising=False)

        result = et.ensure_provider_sync()

        assert result is False
        mock_identity_client.assert_not_called()
        assert et._PROVIDER_INITIALIZED is False

    def test_provider_init_with_valid_env(
        self, mock_identity_client, monkeypatch
    ):
        """UT-PI-02: creates provider with correct arguments, returns True."""
        monkeypatch.setenv("M365_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("M365_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("M365_TENANT_ID", "test-tenant-id")
        monkeypatch.setenv("AGENTARTS_REGION", "test-region")

        mock_client_instance = MagicMock()
        mock_identity_client.return_value = mock_client_instance

        result = et.ensure_provider_sync()

        assert result is True
        mock_identity_client.assert_called_once_with(region="test-region")
        mock_client_instance.create_oauth2_credential_provider.assert_called_once_with(
            name="m365-provider",
            vendor=et.OAuth2Vendor.MICROSOFTOAUTH2,
            client_id="test-client-id",
            client_secret="test-client-secret",
            tenant_id="test-tenant-id",
        )
        assert et._PROVIDER_INITIALIZED is True

    def test_provider_only_initialized_once(
        self, mock_identity_client, monkeypatch
    ):
        """UT-PI-03: create_oauth2_credential_provider called exactly once."""
        monkeypatch.setenv("M365_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("M365_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("M365_TENANT_ID", "test-tenant-id")

        mock_client_instance = MagicMock()
        mock_identity_client.return_value = mock_client_instance

        et.ensure_provider_sync()
        et.ensure_provider_sync()
        et.ensure_provider_sync()

        mock_client_instance.create_oauth2_credential_provider.assert_called_once()

    def test_provider_init_handles_identity_client_error(
        self, mock_identity_client, monkeypatch
    ):
        """UT-PI-04: IdentityClient error returns False; flag stays False."""
        monkeypatch.setenv("M365_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("M365_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("M365_TENANT_ID", "test-tenant-id")

        mock_client_instance = MagicMock()
        mock_client_instance.create_oauth2_credential_provider.side_effect = (
            RuntimeError("API error")
        )
        mock_identity_client.return_value = mock_client_instance

        result = et.ensure_provider_sync()

        assert result is False
        assert et._PROVIDER_INITIALIZED is False

    def test_provider_init_handles_already_exists(
        self, mock_identity_client, monkeypatch
    ):
        """UT-PI-05: 'already exists' error treated as success, returns True."""
        monkeypatch.setenv("M365_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("M365_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("M365_TENANT_ID", "test-tenant-id")

        mock_client_instance = MagicMock()
        mock_client_instance.create_oauth2_credential_provider.side_effect = (
            RuntimeError("provider already exists")
        )
        mock_identity_client.return_value = mock_client_instance

        result = et.ensure_provider_sync()

        assert result is True
        assert et._PROVIDER_INITIALIZED is True
