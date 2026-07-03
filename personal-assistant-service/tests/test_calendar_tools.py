"""Unit tests for Microsoft 365 Calendar tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.tools.calendar_tools as ct

_AUTHORIZED_BOUNDARIES = [
    "_list_calendar_events_authorized",
    "_get_calendar_event_authorized",
    "_search_calendar_events_authorized",
]


@pytest.fixture(autouse=True)
def unwrap_calendar_authorized_boundaries():
    saved = {}
    for name in _AUTHORIZED_BOUNDARIES:
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
@pytest.mark.parametrize(
    ("boundary_name", "kwargs"),
    [
        (
            "_list_calendar_events_authorized",
            {
                "start_time": "2026-06-22T00:00:00",
                "end_time": "2026-06-23T00:00:00",
                "calendar_id": "primary",
                "limit": 20,
            },
        ),
        (
            "_get_calendar_event_authorized",
            {"event_id": "event-1", "calendar_id": "primary"},
        ),
        (
            "_search_calendar_events_authorized",
            {
                "query": "design",
                "start_time": None,
                "end_time": None,
                "calendar_id": "primary",
                "limit": 20,
            },
        ),
    ],
)
async def test_calendar_authorized_boundaries_without_token_are_programming_errors(
    boundary_name,
    kwargs,
):
    boundary = getattr(ct, boundary_name)
    with pytest.raises(RuntimeError, match="access_token"):
        await boundary(**kwargs, access_token=None)


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
async def test_calendar_public_tool_schema_excludes_access_token():
    import inspect

    assert list(inspect.signature(ct.list_calendar_events).parameters) == [
        "start_time",
        "end_time",
        "calendar_id",
        "limit",
    ]
    assert list(inspect.signature(ct.get_calendar_event).parameters) == [
        "event_id",
        "calendar_id",
    ]
    assert list(inspect.signature(ct.search_calendar_events).parameters) == [
        "query",
        "start_time",
        "end_time",
        "calendar_id",
        "limit",
    ]


@pytest.mark.asyncio
async def test_calendar_public_tool_calls_authorized_boundary():
    async def fake_authorized(**kwargs):
        return {"ok": True, "kwargs": kwargs}

    with (
        patch(
            "app.tools.calendar_tools.AgentArtsRuntimeContext.get_workload_access_token",
            return_value="jwt-mode-wat",
        ),
        patch(
            "app.tools.calendar_tools._list_calendar_events_authorized",
            side_effect=fake_authorized,
        ),
    ):
        result = await ct.list_calendar_events(
            "2026-06-22T00:00:00",
            "2026-06-23T00:00:00",
        )

    assert result["ok"] is True
    assert result["kwargs"]["start_time"] == "2026-06-22T00:00:00"
    assert "access_token" not in result["kwargs"]


@pytest.mark.asyncio
async def test_calendar_public_tool_without_wat_returns_local_login_error():
    with (
        patch(
            "app.tools.calendar_tools.AgentArtsRuntimeContext.get_workload_access_token",
            return_value=None,
        ),
        patch(
            "app.tools.calendar_tools.get_workload_access_token_source",
            return_value="missing_authorization_user_token",
        ),
        patch("app.tools.calendar_tools._list_calendar_events_authorized") as boundary,
    ):
        result = await ct.list_calendar_events(
            "2026-06-22T00:00:00",
            "2026-06-23T00:00:00",
        )

    assert "本地日历授权需要先使用 Microsoft 登录" in result["error"]
    boundary.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_public_tool_reports_local_wat_exchange_failure():
    with (
        patch(
            "app.tools.calendar_tools.AgentArtsRuntimeContext.get_workload_access_token",
            return_value=None,
        ),
        patch(
            "app.tools.calendar_tools.get_workload_access_token_source",
            return_value="local_jwt_wat_failed",
        ),
        patch("app.tools.calendar_tools._list_calendar_events_authorized") as boundary,
    ):
        result = await ct.list_calendar_events(
            "2026-06-22T00:00:00",
            "2026-06-23T00:00:00",
        )

    assert "workload token" in result["error"]
    boundary.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_authorized_boundary_forwards_injected_token_to_impl():
    async def fake_impl(**kwargs):
        return {"ok": True, "kwargs": kwargs}

    with patch(
        "app.tools.calendar_tools._list_calendar_events_impl",
        side_effect=fake_impl,
    ):
        result = await ct._list_calendar_events_authorized(
            start_time="2026-06-22T00:00:00",
            end_time="2026-06-23T00:00:00",
            calendar_id="primary",
            limit=20,
            access_token="token",
        )

    assert result["ok"] is True
    assert result["kwargs"]["start_time"] == "2026-06-22T00:00:00"
    assert result["kwargs"]["access_token"] == "token"
