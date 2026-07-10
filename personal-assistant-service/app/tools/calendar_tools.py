"""Microsoft 365 Calendar read-only tools backed by AgentArts OAuth2."""

import logging
from typing import Any

import httpx
from agentarts.sdk import require_access_token
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from langgraph.config import get_stream_writer

from app.settings import get_settings

logger = logging.getLogger(__name__)

_SETTINGS = get_settings()
GRAPH_BASE_URL = str(_SETTINGS.graph_base_url).rstrip("/")
CALENDAR_PROVIDER = _SETTINGS.m365_calendar_provider_name
CALENDAR_SCOPES = _SETTINGS.m365_calendar_scope_list
CALENDAR_CALLBACK_URL = (
    str(_SETTINGS.oauth2_calendar_callback_url)
    if _SETTINGS.oauth2_calendar_callback_url
    else None
)


async def handle_auth_url(auth_url: str) -> None:
    """Push Calendar authorization URL to the frontend as an AuthCard."""
    logger.info("Calendar authorization required.")
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "system_message",
                "system_message": "日历功能需要您的授权。请点击该链接进行授权",
                "auth_url": auth_url,
                "auth_required": True,
                "provider": CALENDAR_PROVIDER,
                "oauth2_state": AgentArtsRuntimeContext.get_oauth2_custom_state(),
            }
        )
    except RuntimeError:
        logger.warning("Calendar auth URL not streamed outside graph context.")


def _push_auth_complete() -> None:
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "system_message",
                "system_message": "日历授权已完成 ✅",
                "auth_complete": True,
                "provider": CALENDAR_PROVIDER,
                "oauth2_state": AgentArtsRuntimeContext.get_oauth2_custom_state(),
            }
        )
    except RuntimeError:
        logger.warning("Calendar auth_complete not streamed outside graph context.")


def _format_tool_error(e: Exception, tool_name: str) -> dict[str, Any]:
    if isinstance(e, httpx.TimeoutException):
        return {"error": f"日历请求超时，请稍后再试。（{tool_name}）"}
    if isinstance(e, httpx.ConnectError):
        return {"error": f"无法连接到 Microsoft Graph，请检查网络。（{tool_name}）"}
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            return {"error": "日历功能未授权或授权已失效，请重新授权。"}
        if status == 403:
            return {"error": "当前账号没有读取日历的权限。"}
        if status == 429:
            return {"error": "日历请求过于频繁，请稍后再试。"}
        if status == 503:
            return {"error": "Microsoft Calendar 服务暂时不可用，请稍后再试。"}
        return {"error": f"日历服务返回错误（{status}），请稍后再试。"}
    return {"error": f"日历操作失败: {tool_name}。如果问题持续，请联系支持。"}


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.graph_request_timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _client


def _calendar_view_url(calendar_id: str) -> str:
    if calendar_id == "primary":
        return f"{GRAPH_BASE_URL}/calendarView"
    return f"{GRAPH_BASE_URL}/calendars/{calendar_id}/calendarView"


def _event_url(event_id: str, calendar_id: str) -> str:
    if calendar_id == "primary":
        return f"{GRAPH_BASE_URL}/events/{event_id}"
    return f"{GRAPH_BASE_URL}/calendars/{calendar_id}/events/{event_id}"


def _headers(access_token: str) -> dict[str, str]:
    timezone = get_settings().graph_timezone
    return {
        "Authorization": f"Bearer {access_token}",
        "Prefer": f'outlook.timezone="{timezone}"',
    }


def _require_calendar_jwt_workload_context() -> None:
    if AgentArtsRuntimeContext.get_workload_access_token():
        return

    logger.warning(
        "Calendar OAuth2 blocked before SDK local fallback "
        "source=missing_authorization_user_token identity_mode=jwt provider=%s",
        CALENDAR_PROVIDER,
    )
    raise RuntimeError(
        "Calendar OAuth2 local full flow requires an Authorization user token. "
        "Enable local Entra login and retry."
    )


def _format_event(event: dict[str, Any]) -> dict[str, Any]:
    organizer = event.get("organizer", {}).get("emailAddress", {})
    location = event.get("location", {})
    return {
        "id": event.get("id"),
        "subject": event.get("subject") or "(无标题)",
        "start": event.get("start"),
        "end": event.get("end"),
        "location": location.get("displayName") or "",
        "organizer": {
            "name": organizer.get("name") or "",
            "address": organizer.get("address") or "",
        },
        "attendees": [
            {
                "name": attendee.get("emailAddress", {}).get("name") or "",
                "address": attendee.get("emailAddress", {}).get("address") or "",
                "response": attendee.get("status", {}).get("response") or "",
            }
            for attendee in event.get("attendees", [])
        ],
        "isOnlineMeeting": event.get("isOnlineMeeting", False),
        "onlineMeetingUrl": event.get("onlineMeetingUrl"),
        "webLink": event.get("webLink"),
        "bodyPreview": event.get("bodyPreview") or "",
    }


@require_access_token(
    provider_name=CALENDAR_PROVIDER,
    scopes=CALENDAR_SCOPES,
    auth_flow="USER_FEDERATION",
    on_auth_url=handle_auth_url,
    callback_url=CALENDAR_CALLBACK_URL,
)
async def _list_calendar_events_authorized(
    *,
    start_time: str,
    end_time: str,
    calendar_id: str,
    limit: int,
    access_token: str | None = None,
) -> dict[str, Any]:
    if not access_token:
        raise RuntimeError("access_token was not injected by require_access_token")
    _push_auth_complete()
    return await _list_calendar_events_impl(
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        limit=limit,
        access_token=access_token,
    )


async def list_calendar_events(
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    limit: int = 20,
) -> dict[str, Any]:
    """列出指定时间范围内的 Microsoft 365 日历事件。"""
    _require_calendar_jwt_workload_context()
    return await _list_calendar_events_authorized(
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        limit=limit,
    )


async def _list_calendar_events_impl(
    *,
    start_time: str,
    end_time: str,
    calendar_id: str,
    limit: int,
    access_token: str,
) -> dict[str, Any]:

    safe_limit = max(1, min(limit, 50))
    try:
        resp = await _get_client().get(
            _calendar_view_url(calendar_id),
            headers=_headers(access_token),
            params={
                "startDateTime": start_time,
                "endDateTime": end_time,
                "$top": safe_limit,
                "$orderby": "start/dateTime",
                "$select": (
                    "id,subject,start,end,location,organizer,attendees,"
                    "isOnlineMeeting,onlineMeetingUrl,webLink,bodyPreview"
                ),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        events = [_format_event(event) for event in data.get("value", [])]
        return {
            "events": events,
            "count": len(events),
            "calendar_id": calendar_id,
            "timezone": get_settings().graph_timezone,
            "has_more": bool(data.get("@odata.nextLink")),
        }
    except Exception as e:
        return _format_tool_error(e, "list_calendar_events")


@require_access_token(
    provider_name=CALENDAR_PROVIDER,
    scopes=CALENDAR_SCOPES,
    auth_flow="USER_FEDERATION",
    on_auth_url=handle_auth_url,
    callback_url=CALENDAR_CALLBACK_URL,
)
async def _get_calendar_event_authorized(
    *,
    event_id: str,
    calendar_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    if not access_token:
        raise RuntimeError("access_token was not injected by require_access_token")
    _push_auth_complete()
    return await _get_calendar_event_impl(
        event_id=event_id,
        calendar_id=calendar_id,
        access_token=access_token,
    )


async def get_calendar_event(
    event_id: str,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """获取单个 Microsoft 365 日历事件详情。"""
    _require_calendar_jwt_workload_context()
    return await _get_calendar_event_authorized(
        event_id=event_id,
        calendar_id=calendar_id,
    )


async def _get_calendar_event_impl(
    *,
    event_id: str,
    calendar_id: str,
    access_token: str,
) -> dict[str, Any]:

    try:
        resp = await _get_client().get(
            _event_url(event_id, calendar_id),
            headers=_headers(access_token),
            params={
                "$select": (
                    "id,subject,start,end,location,organizer,attendees,"
                    "isOnlineMeeting,onlineMeetingUrl,webLink,bodyPreview"
                ),
            },
        )
        resp.raise_for_status()
        return {"event": _format_event(resp.json()), "calendar_id": calendar_id}
    except Exception as e:
        return _format_tool_error(e, "get_calendar_event")


@require_access_token(
    provider_name=CALENDAR_PROVIDER,
    scopes=CALENDAR_SCOPES,
    auth_flow="USER_FEDERATION",
    on_auth_url=handle_auth_url,
    callback_url=CALENDAR_CALLBACK_URL,
)
async def _search_calendar_events_authorized(
    *,
    query: str,
    start_time: str | None,
    end_time: str | None,
    calendar_id: str,
    limit: int,
    access_token: str | None = None,
) -> dict[str, Any]:
    if not access_token:
        raise RuntimeError("access_token was not injected by require_access_token")
    _push_auth_complete()
    return await _search_calendar_events_impl(
        query=query,
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        limit=limit,
        access_token=access_token,
    )


async def search_calendar_events(
    query: str,
    start_time: str | None = None,
    end_time: str | None = None,
    calendar_id: str = "primary",
    limit: int = 20,
) -> dict[str, Any]:
    """按关键词搜索 Microsoft 365 日历事件。"""
    _require_calendar_jwt_workload_context()
    return await _search_calendar_events_authorized(
        query=query,
        start_time=start_time,
        end_time=end_time,
        calendar_id=calendar_id,
        limit=limit,
    )


async def _search_calendar_events_impl(
    *,
    query: str,
    start_time: str | None,
    end_time: str | None,
    calendar_id: str,
    limit: int,
    access_token: str,
) -> dict[str, Any]:

    safe_limit = max(1, min(limit, 50))
    try:
        if start_time and end_time:
            resp = await _get_client().get(
                _calendar_view_url(calendar_id),
                headers=_headers(access_token),
                params={
                    "startDateTime": start_time,
                    "endDateTime": end_time,
                    "$top": safe_limit,
                    "$orderby": "start/dateTime",
                    "$select": (
                        "id,subject,start,end,location,organizer,attendees,"
                        "isOnlineMeeting,onlineMeetingUrl,webLink,bodyPreview"
                    ),
                },
            )
            resp.raise_for_status()
            lowered_query = query.casefold()
            events = [
                _format_event(event)
                for event in resp.json().get("value", [])
                if lowered_query
                in " ".join(
                    [
                        str(event.get("subject") or ""),
                        str(event.get("bodyPreview") or ""),
                        str(event.get("location", {}).get("displayName") or ""),
                    ]
                ).casefold()
            ]
            return {"events": events, "count": len(events), "query": query}

        resp = await _get_client().get(
            f"{GRAPH_BASE_URL}/events",
            headers=_headers(access_token),
            params={
                "$search": f'"{query}"',
                "$top": safe_limit,
                "$select": (
                    "id,subject,start,end,location,organizer,attendees,"
                    "isOnlineMeeting,onlineMeetingUrl,webLink,bodyPreview"
                ),
            },
        )
        resp.raise_for_status()
        events = [_format_event(event) for event in resp.json().get("value", [])]
        return {"events": events, "count": len(events), "query": query}
    except Exception as e:
        return _format_tool_error(e, "search_calendar_events")


CALENDAR_TOOLS = [
    list_calendar_events,
    get_calendar_event,
    search_calendar_events,
]
