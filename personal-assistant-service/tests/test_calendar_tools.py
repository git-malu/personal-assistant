"""Unit tests for Microsoft 365 Calendar tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.tools.calendar_tools as ct

_TOOL_NAMES = [
    "list_calendar_events",
    "get_calendar_event",
    "search_calendar_events",
]


@pytest.fixture(autouse=True)
def unwrap_calendar_tools():
    saved = {}
    for name in _TOOL_NAMES:
        wrapped = getattr(ct, name)
        saved[name] = wrapped
        raw = wrapped
        while hasattr(raw, "__wrapped__"):
            raw = raw.__wrapped__
        setattr(ct, name, raw)
    yield
    for name, original in saved.items():
        setattr(ct, name, original)


@pytest.fixture(autouse=True)
def reset_shared_client():
    ct._client = None
    yield
    ct._client = None


def _response(json_data: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


def _mock_client(response: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = response
    return client


@pytest.mark.asyncio
async def test_list_calendar_events_formats_graph_request_and_response():
    response = _response(
        {
            "value": [
                {
                    "id": "event-1",
                    "subject": "Project Sync",
                    "start": {"dateTime": "2026-06-22T09:00:00", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-06-22T10:00:00", "timeZone": "UTC"},
                    "location": {"displayName": "Room A"},
                    "organizer": {
                        "emailAddress": {
                            "name": "Alice",
                            "address": "alice@example.com",
                        }
                    },
                    "attendees": [],
                    "isOnlineMeeting": True,
                    "onlineMeetingUrl": "https://teams.example/meet",
                    "webLink": "https://outlook.example/event",
                    "bodyPreview": "Weekly sync",
                }
            ]
        }
    )
    client = _mock_client(response)

    with (
        patch("app.tools.calendar_tools._get_client", return_value=client),
        patch("app.tools.calendar_tools._push_auth_complete"),
    ):
        result = await ct._list_calendar_events_impl(
            start_time="2026-06-22T00:00:00",
            end_time="2026-06-23T00:00:00",
            calendar_id="primary",
            limit=20,
            access_token="token",
        )

    assert result["count"] == 1
    assert result["events"][0]["subject"] == "Project Sync"
    assert result["events"][0]["location"] == "Room A"
    client.get.assert_awaited_once()
    args, kwargs = client.get.call_args
    assert args[0] == "https://graph.microsoft.com/v1.0/me/calendarView"
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert "outlook.timezone" in kwargs["headers"]["Prefer"]
    assert kwargs["params"]["startDateTime"] == "2026-06-22T00:00:00"
    assert kwargs["params"]["endDateTime"] == "2026-06-23T00:00:00"
    assert kwargs["params"]["$top"] == 20


@pytest.mark.asyncio
async def test_get_calendar_event_uses_calendar_scoped_url_when_calendar_id_given():
    response = _response({"id": "event-1", "subject": "One on One"})
    client = _mock_client(response)

    with (
        patch("app.tools.calendar_tools._get_client", return_value=client),
        patch("app.tools.calendar_tools._push_auth_complete"),
    ):
        result = await ct._get_calendar_event_impl(
            event_id="event-1",
            calendar_id="calendar-1",
            access_token="token",
        )

    assert result["event"]["subject"] == "One on One"
    args, _kwargs = client.get.call_args
    assert (
        args[0]
        == "https://graph.microsoft.com/v1.0/me/calendars/calendar-1/events/event-1"
    )


@pytest.mark.asyncio
async def test_search_calendar_events_with_time_window_filters_locally():
    response = _response(
        {
            "value": [
                {"id": "event-1", "subject": "Design Review"},
                {"id": "event-2", "subject": "Lunch"},
            ]
        }
    )
    client = _mock_client(response)

    with (
        patch("app.tools.calendar_tools._get_client", return_value=client),
        patch("app.tools.calendar_tools._push_auth_complete"),
    ):
        result = await ct._search_calendar_events_impl(
            query="design",
            start_time="2026-06-22T00:00:00",
            end_time="2026-06-23T00:00:00",
            calendar_id="primary",
            limit=20,
            access_token="token",
        )

    assert result["count"] == 1
    assert result["events"][0]["subject"] == "Design Review"


@pytest.mark.asyncio
async def test_calendar_tools_return_auth_required_without_access_token():
    result = await ct._list_calendar_events_impl(
        start_time="2026-06-22T00:00:00",
        end_time="2026-06-23T00:00:00",
        calendar_id="primary",
        limit=20,
        access_token=None,
    )

    assert result["auth_required"] is True


@pytest.mark.asyncio
async def test_handle_auth_url_streams_sdk_authorization_url_unchanged():
    writer_mock = MagicMock()
    with (
        patch("app.tools.calendar_tools.get_stream_writer", return_value=writer_mock),
        patch(
            "app.tools.calendar_tools.AgentArtsRuntimeContext.get_oauth2_custom_state",
            return_value="signed-state",
        ),
    ):
        await ct.handle_auth_url("https://auth.example.com/login?client_id=abc")

    writer_mock.assert_called_once()
    payload = writer_mock.call_args[0][0]
    assert payload["auth_url"] == "https://auth.example.com/login?client_id=abc"
    assert payload["oauth2_state"] == "signed-state"


def test_push_auth_complete_streams_matching_oauth2_state():
    writer_mock = MagicMock()
    with (
        patch("app.tools.calendar_tools.get_stream_writer", return_value=writer_mock),
        patch(
            "app.tools.calendar_tools.AgentArtsRuntimeContext.get_oauth2_custom_state",
            return_value="signed-state",
        ),
    ):
        ct._push_auth_complete()

    writer_mock.assert_called_once()
    payload = writer_mock.call_args[0][0]
    assert payload["auth_complete"] is True
    assert payload["provider"] == ct.CALENDAR_PROVIDER
    assert payload["oauth2_state"] == "signed-state"


@pytest.mark.asyncio
async def test_calendar_tool_forwards_injected_access_token_to_impl():
    async def fake_impl(**kwargs):
        return {"ok": True, "kwargs": kwargs}

    with patch(
        "app.tools.calendar_tools._list_calendar_events_impl",
        side_effect=fake_impl,
    ):
        result = await ct.list_calendar_events(
            "2026-06-22T00:00:00",
            "2026-06-23T00:00:00",
            access_token="token",
        )

    assert result["ok"] is True
    assert result["kwargs"]["start_time"] == "2026-06-22T00:00:00"
    assert result["kwargs"]["access_token"] == "token"
