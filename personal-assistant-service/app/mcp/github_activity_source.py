"""Internal GitHub MCP activity data source functions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.mcp.gateway_client import (
    MCPGatewayClient,
    MCPGatewayError,
    MCPToolInfo,
    run_with_github_mcp_sts,
)

GitHubActivityType = Literal[
    "commit",
    "pull_request",
    "issue",
    "review",
    "comment",
]

_DEFAULT_EVENT_TYPES: tuple[GitHubActivityType, ...] = (
    "commit",
    "pull_request",
    "issue",
    "review",
    "comment",
)

_ISSUE_READ_METHODS = (
    "get",
    "get_comments",
    "get_sub_issues",
    "get_parent",
    "get_labels",
)

_ISSUE_DETAIL_KEYS = {
    "get": "issue",
    "get_comments": "comments",
    "get_sub_issues": "sub_issues",
    "get_parent": "parent",
    "get_labels": "labels",
}

_READ_TOOL_SUFFIXES = frozenset(
    {
        "get_me",
        "search_repositories",
        "list_commits",
        "get_commit",
        "list_pull_requests",
        "search_pull_requests",
        "get_pull_request",
        "pull_request_read",
        "get_pull_request_comments",
        "get_pull_request_files",
        "get_pull_request_reviews",
        "list_issues",
        "search_issues",
        "get_issue",
        "issue_read",
        "get_issue_comments",
    }
)

_SENSITIVE_WORDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer",
        "secret",
        "security_token",
        "x_security_token",
        "x_sdk_date",
        "sts",
    }
)

_ACTIVITY_CURSOR_VERSION = 2
_MAX_PAGE_CALLS_PER_SEARCH = 100
_MAX_CONCURRENT_DETAIL_CALLS = 5

_PaginationKind = Literal["initial", "page", "cursor", "none"]


@dataclass(slots=True)
class GitHubActivityEvent:
    provider: str
    event_type: GitHubActivityType
    repository: str
    external_id: str
    title: str
    parent_external_id: str | None = None
    url: str | None = None
    actor: str | None = None
    state: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    summary: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GitHubMCPWarning:
    ok: bool
    warning_type: str
    message: str
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GitHubActivityResult:
    events: list[GitHubActivityEvent] = field(default_factory=list)
    warnings: list[GitHubMCPWarning] = field(default_factory=list)
    next_cursor: str | None = None
    identity_scope: Literal["platform"] = "platform"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _RemotePagination:
    kind: _PaginationKind = "initial"
    value: int | str | None = None


@dataclass(slots=True)
class _CollectedPage:
    events: list[GitHubActivityEvent]
    current: _RemotePagination
    next: _RemotePagination | None = None
    warning: GitHubMCPWarning | None = None


@dataclass(slots=True)
class _ActivityPageTask:
    repository: str
    event_type: GitHubActivityType
    page_size: int
    pagination: _RemotePagination = field(default_factory=_RemotePagination)
    offset: int = 0
    parent_external_id: str | None = None
    parent_type: Literal["issue", "pull_request"] | None = None
    discover_parents: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "event_type": self.event_type,
            "page_size": self.page_size,
            "pagination": {
                "kind": self.pagination.kind,
                "value": self.pagination.value,
            },
            "offset": self.offset,
            "parent_external_id": self.parent_external_id,
            "parent_type": self.parent_type,
            "discover_parents": self.discover_parents,
        }


def _warning(
    warning_type: str,
    message: str,
    *,
    retryable: bool = False,
) -> GitHubMCPWarning:
    return GitHubMCPWarning(
        ok=False,
        warning_type=warning_type,
        message=message,
        retryable=retryable,
    )


def _warning_from_error(error: Exception) -> GitHubMCPWarning:
    if isinstance(error, MCPGatewayError):
        return _warning(
            error.warning_type,
            str(error),
            retryable=error.retryable,
        )
    return _warning(
        "mcp_error",
        "GitHub MCP activity source failed.",
        retryable=False,
    )


def _normalize_tool_name(name: str) -> str:
    return name.replace("-", "_").lower()


def _matches_tool_suffix(tool_name: str, suffix: str) -> bool:
    normalized = _normalize_tool_name(tool_name)
    normalized_suffix = _normalize_tool_name(suffix)
    return normalized == normalized_suffix or normalized.endswith(
        f"_{normalized_suffix}"
    )


def is_read_only_activity_tool(tool_name: str) -> bool:
    """Return whether a remote GitHub MCP tool is in the activity allowlist."""
    return any(
        _matches_tool_suffix(tool_name, suffix) for suffix in _READ_TOOL_SUFFIXES
    )


def _build_tool_index(tools: list[MCPToolInfo]) -> dict[str, MCPToolInfo]:
    return {tool.name: tool for tool in tools if is_read_only_activity_tool(tool.name)}


def _find_tool(
    tools: dict[str, MCPToolInfo],
    suffixes: tuple[str, ...],
) -> MCPToolInfo:
    for suffix in suffixes:
        for tool in tools.values():
            if _matches_tool_suffix(tool.name, suffix):
                return tool
    raise MCPGatewayError(
        "capability_missing",
        "GitHub MCP Gateway does not expose the required read-only tool.",
        retryable=False,
    )


def _find_optional_tool(
    tools: dict[str, MCPToolInfo],
    suffixes: tuple[str, ...],
) -> MCPToolInfo | None:
    try:
        return _find_tool(tools, suffixes)
    except MCPGatewayError:
        return None


def _schema_properties(tool: MCPToolInfo) -> dict[str, Any]:
    properties = tool.input_schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _candidate_names(name: str) -> tuple[str, ...]:
    if "_" not in name:
        return (name,)
    parts = name.split("_")
    camel = parts[0] + "".join(part.title() for part in parts[1:])
    return (name, camel)


def _argument_name(tool: MCPToolInfo, *candidates: str) -> str | None:
    properties = _schema_properties(tool)
    if not properties:
        return candidates[0] if candidates else None

    for candidate in candidates:
        for expanded in _candidate_names(candidate):
            if expanded in properties:
                return expanded
    return None


def _set_arg(
    args: dict[str, Any],
    tool: MCPToolInfo,
    value: Any,
    *candidates: str,
    required: bool = False,
) -> None:
    if value is None:
        return
    name = _argument_name(tool, *candidates)
    if name is None:
        if not required:
            return
        name = candidates[0]
    args[name] = value


def _declared_argument_name(
    tool: MCPToolInfo,
    *candidates: str,
) -> str | None:
    properties = _schema_properties(tool)
    for candidate in candidates:
        for expanded in _candidate_names(candidate):
            if expanded in properties:
                return expanded
    return None


def _prepare_remote_pagination(
    args: dict[str, Any],
    tool: MCPToolInfo,
    *,
    page_size: int,
    pagination: _RemotePagination,
) -> _RemotePagination:
    _set_arg(args, tool, page_size, "per_page", "perPage", "limit")
    cursor_arg = _declared_argument_name(tool, "after", "cursor")
    page_arg = _declared_argument_name(tool, "page", "page_number", "pageNumber")

    if pagination.kind == "initial":
        # Prefer page-based pagination over cursor-based when both are
        # available.  Page-based has a raw_count >= page_size heuristic
        # that works even when the remote response omits pagination
        # metadata (e.g. GitHub Copilot MCP returns bare arrays for
        # list_commits / list_pull_requests).  Cursor-based depends on
        # endCursor in the response body, which is not always present.
        if page_arg is not None:
            args[page_arg] = 1
            return _RemotePagination("page", 1)
        if cursor_arg is not None:
            return _RemotePagination("cursor", None)
        return _RemotePagination("none", None)

    if pagination.kind == "cursor":
        if cursor_arg is None:
            raise MCPGatewayError(
                "pagination_incompatible",
                f"GitHub MCP tool {tool.name} no longer accepts a cursor.",
                retryable=False,
            )
        if pagination.value is not None:
            args[cursor_arg] = pagination.value
        return _RemotePagination("cursor", pagination.value)

    if pagination.kind == "page":
        if page_arg is None or not isinstance(pagination.value, int):
            raise MCPGatewayError(
                "pagination_incompatible",
                f"GitHub MCP tool {tool.name} no longer accepts a page number.",
                retryable=False,
            )
        args[page_arg] = pagination.value
        return _RemotePagination("page", pagination.value)

    return _RemotePagination("none", None)


def _pagination_metadata(payload: Any) -> tuple[bool | None, str | None]:
    if not isinstance(payload, dict):
        return None, None

    containers = [payload]
    for key in ("pageInfo", "page_info", "pagination"):
        value = payload.get(key)
        if isinstance(value, dict):
            containers.insert(0, value)

    has_more: bool | None = None
    next_cursor: str | None = None
    for container in containers:
        for key in ("hasNextPage", "has_next_page", "hasMore", "has_more"):
            value = container.get(key)
            if isinstance(value, bool):
                has_more = value
                break
        for key in ("endCursor", "end_cursor", "nextCursor", "next_cursor"):
            value = container.get(key)
            if isinstance(value, str) and value:
                next_cursor = value
                break
        if has_more is not None or next_cursor is not None:
            break
    return has_more, next_cursor


def _next_remote_pagination(
    tool: MCPToolInfo,
    payload: Any,
    *,
    raw_count: int,
    page_size: int,
    current: _RemotePagination,
) -> tuple[_RemotePagination | None, GitHubMCPWarning | None]:
    has_more, next_cursor = _pagination_metadata(payload)
    page_size_supported = (
        _declared_argument_name(tool, "per_page", "perPage", "limit") is not None
    )

    if current.kind == "cursor":
        if has_more is False:
            return None, None
        if next_cursor is not None:
            return _RemotePagination("cursor", next_cursor), None
        # When the remote response lacks endCursor despite having more
        # data, try falling back to page-based pagination if the tool
        # declares a page argument.  This covers the edge case where a
        # tool with both 'after' and 'page' ends up in cursor mode (e.g.
        # after a cursor was persisted in a previous session) and the
        # response is a bare array without pageInfo.
        page_arg = _declared_argument_name(tool, "page", "page_number", "pageNumber")
        if page_arg is not None and raw_count >= page_size:
            return _RemotePagination("page", 2), None
        if has_more is True or raw_count > 0:
            return None, _warning(
                "pagination_unsupported",
                f"GitHub MCP tool {tool.name} did not return a continuation cursor.",
            )
        return None, None

    if current.kind == "page":
        if has_more is False:
            return None, None
        if (
            has_more is True
            or next_cursor is not None
            or (page_size_supported and raw_count >= page_size)
            or (not page_size_supported and raw_count > 0)
        ):
            page = current.value if isinstance(current.value, int) else 1
            return _RemotePagination("page", page + 1), None
        return None, None

    if has_more is True or next_cursor is not None or raw_count > 0:
        return None, _warning(
            "pagination_unsupported",
            f"GitHub MCP tool {tool.name} does not expose a pagination input.",
        )
    return None, None


def _repo_parts(repository: str) -> tuple[str, str]:
    owner, separator, repo = repository.strip().partition("/")
    if not owner or not separator or not repo:
        raise ValueError("repository must use owner/repo format")
    return owner, repo


def _get_nested(item: Any, *keys: str) -> Any:
    current = item
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _first_text(value: str | None, *, limit: int = 160) -> str:
    if not value:
        return ""
    text = " ".join(value.strip().split())
    return text[:limit]


def _coerce_items(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("items", "repositories", "commits", "pull_requests", "issues"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _parse_datetime(value: str | datetime | None, timezone: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _activity_query_key(
    *,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    repositories: list[str] | None,
    actor: str | None,
    event_types: tuple[GitHubActivityType, ...],
) -> str:
    query = {
        "start_at": _iso_utc(start_at),
        "end_at": _iso_utc(end_at),
        "timezone": timezone,
        "repositories": sorted(set(repositories or [])),
        "actor": actor,
        "event_types": sorted(set(event_types)),
    }
    encoded = json.dumps(query, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_activity_cursor(
    query_key: str,
    tasks: list[_ActivityPageTask],
) -> str:
    payload = {
        "version": _ACTIVITY_CURSOR_VERSION,
        "query": query_key,
        "tasks": [task.to_dict() for task in tasks],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _activity_task_from_dict(value: Any) -> _ActivityPageTask:
    if not isinstance(value, dict):
        raise ValueError("cursor task must be an object")

    repository = value.get("repository")
    event_type = value.get("event_type")
    page_size = value.get("page_size")
    offset = value.get("offset", 0)
    pagination_value = value.get("pagination")
    parent_external_id = value.get("parent_external_id")
    parent_type = value.get("parent_type")
    discover_parents = value.get("discover_parents", False)

    if not isinstance(repository, str) or not repository:
        raise ValueError("cursor task repository is invalid")
    if event_type not in _DEFAULT_EVENT_TYPES:
        raise ValueError("cursor task event type is invalid")
    if not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValueError("cursor task page size is invalid")
    if not isinstance(offset, int) or not 0 <= offset <= 100:
        raise ValueError("cursor task offset is invalid")
    if not isinstance(pagination_value, dict):
        raise ValueError("cursor task pagination is invalid")

    pagination_kind = pagination_value.get("kind")
    remote_value = pagination_value.get("value")
    if pagination_kind not in {"initial", "page", "cursor", "none"}:
        raise ValueError("cursor task pagination kind is invalid")
    if pagination_kind == "page" and (
        not isinstance(remote_value, int) or remote_value < 1
    ):
        raise ValueError("cursor task page number is invalid")
    if (
        pagination_kind == "cursor"
        and remote_value is not None
        and not isinstance(remote_value, str)
    ):
        raise ValueError("cursor task remote cursor is invalid")
    if pagination_kind in {"initial", "none"} and remote_value is not None:
        raise ValueError("cursor task pagination value is invalid")
    if pagination_kind == "initial" and offset:
        raise ValueError("cursor task initial offset is invalid")
    if parent_external_id is not None and not isinstance(parent_external_id, str):
        raise ValueError("cursor task parent id is invalid")
    if parent_type not in {None, "issue", "pull_request"}:
        raise ValueError("cursor task parent type is invalid")
    if not isinstance(discover_parents, bool):
        raise ValueError("cursor task discovery flag is invalid")
    if discover_parents and event_type not in {"comment", "review"}:
        raise ValueError("cursor task discovery type is invalid")
    if (
        not discover_parents
        and event_type in {"comment", "review"}
        and not parent_external_id
    ):
        raise ValueError("cursor child task parent id is missing")
    if event_type in {"comment", "review"} and parent_type is None:
        raise ValueError("cursor nested activity parent type is missing")
    if event_type == "review" and parent_type != "pull_request":
        raise ValueError("cursor review parent type is invalid")
    if event_type not in {"comment", "review"} and parent_type is not None:
        raise ValueError("cursor parent type is not allowed")

    return _ActivityPageTask(
        repository=repository,
        event_type=event_type,
        page_size=page_size,
        pagination=_RemotePagination(pagination_kind, remote_value),
        offset=offset,
        parent_external_id=parent_external_id,
        parent_type=parent_type,
        discover_parents=discover_parents,
    )


def _decode_activity_cursor(
    cursor: str,
    *,
    query_key: str,
    selected_types: tuple[GitHubActivityType, ...],
    repositories: list[str] | None,
) -> list[_ActivityPageTask]:
    if not cursor or len(cursor) > 262_144:
        raise ValueError("activity cursor is invalid")
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.b64decode(padded, altchars=b"-_", validate=True)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("activity cursor payload is invalid")
    if payload.get("version") != _ACTIVITY_CURSOR_VERSION:
        raise ValueError("activity cursor version is invalid")
    if payload.get("query") != query_key:
        raise ValueError("activity cursor does not match the query")

    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks or len(raw_tasks) > 10_000:
        raise ValueError("activity cursor tasks are invalid")
    tasks = [_activity_task_from_dict(item) for item in raw_tasks]
    task_keys = [
        (
            task.repository,
            task.event_type,
            task.discover_parents,
            task.parent_external_id,
            task.parent_type,
        )
        for task in tasks
    ]
    if len(task_keys) != len(set(task_keys)):
        raise ValueError("activity cursor contains duplicate tasks")
    selected = set(selected_types)
    allowed_repositories = set(repositories) if repositories else None
    if any(task.event_type not in selected for task in tasks):
        raise ValueError("activity cursor event type does not match the query")
    if allowed_repositories is not None and any(
        task.repository not in allowed_repositories for task in tasks
    ):
        raise ValueError("activity cursor repository does not match the query")
    return tasks


def _timestamp_in_window(
    value: str | None,
    *,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
) -> bool:
    parsed = _parse_datetime(value, timezone)
    if parsed is None:
        return True
    return start_at <= parsed <= end_at


def _actor_matches(actor: str | None, expected: str | None) -> bool:
    return expected is None or (
        actor is not None and actor.casefold() == expected.casefold()
    )


def _event_matches(
    event: GitHubActivityEvent,
    *,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
) -> bool:
    event_time = event.updated_at or event.created_at
    return _actor_matches(event.actor, actor) and _timestamp_in_window(
        event_time,
        start_at=start_at,
        end_at=end_at,
        timezone=timezone,
    )


def _login_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    login = payload.get("login")
    if isinstance(login, str) and login:
        return login
    user = payload.get("user")
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        return user["login"]
    return None


def _commit_to_event(item: dict[str, Any], repository: str) -> GitHubActivityEvent:
    commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
    author = _get_nested(item, "author", "login") or _get_nested(
        commit, "author", "name"
    )
    message = _get_nested(commit, "message")
    title = _first_text(message).split("\\n", maxsplit=1)[0]
    created_at = _get_nested(commit, "author", "date") or _get_nested(
        commit, "committer", "date"
    )
    sha = str(item.get("sha") or item.get("node_id") or "")
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    return GitHubActivityEvent(
        provider="github",
        event_type="commit",
        repository=repository,
        external_id=sha,
        title=title or sha[:12],
        url=item.get("html_url"),
        actor=author,
        state=None,
        created_at=created_at,
        updated_at=created_at,
        summary=title or None,
        metrics={
            key: stats[key]
            for key in ("additions", "deletions", "total")
            if key in stats
        },
    )


def _pull_request_to_event(
    item: dict[str, Any],
    repository: str,
) -> GitHubActivityEvent:
    number = item.get("number") or item.get("pull_number") or item.get("id")
    merged_at = item.get("merged_at")
    state = "merged" if merged_at else item.get("state")
    title = str(item.get("title") or f"Pull request {number}")
    return GitHubActivityEvent(
        provider="github",
        event_type="pull_request",
        repository=repository,
        external_id=str(number or ""),
        title=title,
        url=item.get("html_url") or item.get("url"),
        actor=_get_nested(item, "user", "login") or item.get("author"),
        state=state,
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at") or merged_at,
        summary=title,
        metrics={
            key: item[key]
            for key in ("additions", "deletions", "changed_files", "comments")
            if key in item
        },
    )


def _issue_to_event(item: dict[str, Any], repository: str) -> GitHubActivityEvent:
    number = item.get("number") or item.get("id")
    title = str(item.get("title") or f"Issue {number}")
    return GitHubActivityEvent(
        provider="github",
        event_type="issue",
        repository=repository,
        external_id=str(number or ""),
        title=title,
        url=item.get("html_url") or item.get("url"),
        actor=_get_nested(item, "user", "login") or item.get("author"),
        state=item.get("state"),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at") or item.get("closed_at"),
        summary=title,
        metrics={
            key: item[key]
            for key in ("comments", "reactions")
            if key in item and not isinstance(item[key], dict)
        },
    )


def _comment_to_event(
    item: dict[str, Any],
    repository: str,
    *,
    parent_external_id: str,
    title_prefix: str,
) -> GitHubActivityEvent:
    body = _first_text(item.get("body"))
    external_id = item.get("id") or item.get("node_id")
    return GitHubActivityEvent(
        provider="github",
        event_type="comment",
        repository=repository,
        external_id=str(external_id or ""),
        title=f"{title_prefix}: {body}" if body else title_prefix,
        parent_external_id=parent_external_id,
        url=item.get("html_url") or item.get("url"),
        actor=_get_nested(item, "user", "login") or item.get("author"),
        state=None,
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at") or item.get("created_at"),
        summary=body or None,
    )


def _review_to_event(
    item: dict[str, Any],
    repository: str,
    *,
    parent_external_id: str,
) -> GitHubActivityEvent:
    external_id = item.get("id") or item.get("node_id")
    body = _first_text(item.get("body"))
    state = item.get("state")
    return GitHubActivityEvent(
        provider="github",
        event_type="review",
        repository=repository,
        external_id=str(external_id or ""),
        title=f"Pull request review {state or ''}".strip(),
        parent_external_id=parent_external_id,
        url=item.get("html_url") or item.get("url"),
        actor=_get_nested(item, "user", "login") or item.get("author"),
        state=state,
        created_at=item.get("submitted_at") or item.get("created_at"),
        updated_at=item.get("submitted_at") or item.get("updated_at"),
        summary=body or state,
    )


async def _tool_index(client: MCPGatewayClient) -> dict[str, MCPToolInfo]:
    return _build_tool_index(await client.list_tools())


async def _call(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    suffixes: tuple[str, ...],
    arguments: dict[str, Any],
) -> Any:
    tool = _find_tool(tools, suffixes)
    return await client.call_tool(tool.name, arguments)


async def _resolve_identity_with_tools(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
) -> dict[str, Any]:
    payload = await _call(client, tools, ("get_me",), {})
    return payload if isinstance(payload, dict) else {}


async def github_mcp_resolve_identity() -> dict[str, Any] | GitHubMCPWarning:
    """Return the platform GitHub account used by the MCP Target."""

    async def _operation(client: MCPGatewayClient) -> dict[str, Any]:
        tools = await _tool_index(client)
        return await _resolve_identity_with_tools(client, tools)

    try:
        return await run_with_github_mcp_sts(_operation)
    except Exception as exc:
        return _warning_from_error(exc)


async def _list_repositories_with_tools(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    query: str | None,
    limit: int,
    include_archived: bool,
) -> list[dict[str, Any]]:
    identity = await _resolve_identity_with_tools(client, tools)
    login = _login_from_payload(identity)
    search_query = query or (f"user:{login}" if login else "sort:updated-desc")
    limit = min(max(limit, 1), 100)
    tool = _find_tool(tools, ("search_repositories",))
    args: dict[str, Any] = {}
    _set_arg(args, tool, search_query, "query", "q", required=True)
    _set_arg(args, tool, limit, "per_page", "perPage", "limit")
    payload = await client.call_tool(tool.name, args)
    repositories = _coerce_items(payload, "repositories", "items")
    if include_archived:
        return repositories[:limit]
    return [repo for repo in repositories if not repo.get("archived")][:limit]


async def github_mcp_list_repositories(
    *,
    query: str | None = None,
    limit: int = 30,
    include_archived: bool = False,
) -> list[dict[str, Any]] | GitHubMCPWarning:
    """List repositories visible to the platform GitHub MCP account."""

    async def _operation(client: MCPGatewayClient) -> list[dict[str, Any]]:
        tools = await _tool_index(client)
        return await _list_repositories_with_tools(
            client,
            tools,
            query=query,
            limit=limit,
            include_archived=include_archived,
        )

    try:
        return await run_with_github_mcp_sts(_operation)
    except Exception as exc:
        return _warning_from_error(exc)


async def _discover_activity_repositories(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    platform_login: str | None,
) -> tuple[list[str], list[GitHubMCPWarning]]:
    tool = _find_optional_tool(tools, ("search_repositories",))
    if tool is None:
        return [], [
            _warning(
                "capability_missing",
                "GitHub MCP Gateway cannot discover repositories because the "
                "required read-only tool is unavailable.",
            )
        ]

    if platform_login is None:
        identity = await _resolve_identity_with_tools(client, tools)
        platform_login = _login_from_payload(identity)
    search_query = f"user:{platform_login}" if platform_login else "sort:updated-desc"
    page_size = 100
    args: dict[str, Any] = {}
    _set_arg(args, tool, search_query, "query", "q", required=True)
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=page_size,
        pagination=_RemotePagination(),
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload, "repositories", "items")
    next_page, pagination_warning = _next_remote_pagination(
        tool,
        payload,
        raw_count=len(items),
        page_size=page_size,
        current=current,
    )

    repositories = list(
        dict.fromkeys(
            str(item.get("full_name") or item.get("name"))
            for item in items
            if not item.get("archived") and (item.get("full_name") or item.get("name"))
        )
    )
    warnings = [pagination_warning] if pagination_warning is not None else []
    if next_page is not None or pagination_warning is not None:
        warnings.append(
            _warning(
                "repository_discovery_truncated",
                "GitHub MCP repository discovery has additional or unverifiable "
                "results; specify repositories explicitly to guarantee completeness.",
            )
        )
    return repositories, warnings


def _collected_page(
    events: list[GitHubActivityEvent],
    *,
    tool: MCPToolInfo,
    payload: Any,
    raw_count: int,
    page_size: int,
    current: _RemotePagination,
) -> _CollectedPage:
    next_page, warning = _next_remote_pagination(
        tool,
        payload,
        raw_count=raw_count,
        page_size=page_size,
        current=current,
    )
    return _CollectedPage(
        events=events,
        current=current,
        next=next_page,
        warning=warning,
    )


def _missing_activity_page(
    *,
    repository: str,
    event_type: GitHubActivityType,
) -> _CollectedPage:
    return _CollectedPage(
        events=[],
        current=_RemotePagination("none", None),
        warning=_warning(
            "capability_missing",
            f"GitHub MCP Gateway cannot collect {event_type} activity for "
            f"{repository} because the required read-only tool is unavailable.",
        ),
    )


async def _collect_commits(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    repository: str,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
    limit: int,
    pagination: _RemotePagination,
) -> _CollectedPage:
    owner, repo = _repo_parts(repository)
    tool = _find_optional_tool(tools, ("list_commits",))
    if tool is None:
        return _missing_activity_page(repository=repository, event_type="commit")

    args: dict[str, Any] = {}
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(args, tool, _iso_utc(start_at), "since")
    _set_arg(args, tool, _iso_utc(end_at), "until")
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=limit,
        pagination=pagination,
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload)
    events = [_commit_to_event(item, repository) for item in items]
    filtered = [
        event
        for event in events
        if _event_matches(
            event,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            actor=actor,
        )
    ]
    return _collected_page(
        filtered,
        tool=tool,
        payload=payload,
        raw_count=len(items),
        page_size=limit,
        current=current,
    )


async def _collect_pull_requests(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    repository: str,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
    limit: int,
    pagination: _RemotePagination,
) -> _CollectedPage:
    owner, repo = _repo_parts(repository)
    tool = _find_optional_tool(tools, ("list_pull_requests",))
    if tool is None:
        return _missing_activity_page(
            repository=repository,
            event_type="pull_request",
        )

    args: dict[str, Any] = {}
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(args, tool, "all", "state")
    _set_arg(args, tool, "updated", "sort")
    _set_arg(args, tool, "desc", "direction")
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=limit,
        pagination=pagination,
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload)
    events = [_pull_request_to_event(item, repository) for item in items]
    filtered = [
        event
        for event in events
        if _event_matches(
            event,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            actor=actor,
        )
    ]
    return _collected_page(
        filtered,
        tool=tool,
        payload=payload,
        raw_count=len(items),
        page_size=limit,
        current=current,
    )


async def _collect_issues(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    repository: str,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
    limit: int,
    pagination: _RemotePagination,
) -> _CollectedPage:
    owner, repo = _repo_parts(repository)
    tool = _find_optional_tool(tools, ("list_issues",))
    if tool is None:
        return _missing_activity_page(repository=repository, event_type="issue")

    args: dict[str, Any] = {}
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(args, tool, "all", "state")
    _set_arg(args, tool, _iso_utc(start_at), "since")
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=limit,
        pagination=pagination,
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload)
    events = [
        _issue_to_event(item, repository)
        for item in items
        if not item.get("pull_request")
    ]
    filtered = [
        event
        for event in events
        if _event_matches(
            event,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            actor=actor,
        )
    ]
    return _collected_page(
        filtered,
        tool=tool,
        payload=payload,
        raw_count=len(items),
        page_size=limit,
        current=current,
    )


async def _collect_issue_comments(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    repository: str,
    issue_number: str,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
    limit: int,
    pagination: _RemotePagination,
) -> _CollectedPage:
    owner, repo = _repo_parts(repository)
    tool = _find_optional_tool(tools, ("get_issue_comments", "issue_read"))
    if tool is None:
        return _missing_activity_page(repository=repository, event_type="comment")

    args: dict[str, Any] = {}
    if _matches_tool_suffix(tool.name, "issue_read"):
        _set_arg(args, tool, "get_comments", "method", required=True)
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(
        args,
        tool,
        int(issue_number),
        "issue_number",
        "issueNumber",
        required=True,
    )
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=limit,
        pagination=pagination,
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload, "comments")
    events = [
        _comment_to_event(
            item,
            repository,
            parent_external_id=issue_number,
            title_prefix=f"Issue or pull request #{issue_number} comment",
        )
        for item in items
    ]
    filtered = [
        event
        for event in events
        if _event_matches(
            event,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            actor=actor,
        )
    ]
    return _collected_page(
        filtered,
        tool=tool,
        payload=payload,
        raw_count=len(items),
        page_size=limit,
        current=current,
    )


async def _collect_pull_request_comments(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    repository: str,
    pull_number: str,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
    limit: int,
    pagination: _RemotePagination,
) -> _CollectedPage:
    owner, repo = _repo_parts(repository)
    tool = _find_optional_tool(
        tools,
        ("get_pull_request_comments", "pull_request_read"),
    )
    if tool is None:
        return _missing_activity_page(repository=repository, event_type="comment")

    args: dict[str, Any] = {}
    if _matches_tool_suffix(tool.name, "pull_request_read"):
        _set_arg(args, tool, "get_comments", "method", required=True)
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(
        args,
        tool,
        int(pull_number),
        "pull_number",
        "pullNumber",
        required=True,
    )
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=limit,
        pagination=pagination,
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload, "comments")
    events = [
        _comment_to_event(
            item,
            repository,
            parent_external_id=pull_number,
            title_prefix=f"Pull request #{pull_number} comment",
        )
        for item in items
    ]
    filtered = [
        event
        for event in events
        if _event_matches(
            event,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            actor=actor,
        )
    ]
    return _collected_page(
        filtered,
        tool=tool,
        payload=payload,
        raw_count=len(items),
        page_size=limit,
        current=current,
    )


async def _collect_pull_request_reviews(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    repository: str,
    pull_number: str,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
    limit: int,
    pagination: _RemotePagination,
) -> _CollectedPage:
    owner, repo = _repo_parts(repository)
    tool = _find_optional_tool(
        tools,
        ("get_pull_request_reviews", "pull_request_read"),
    )
    if tool is None:
        return _missing_activity_page(repository=repository, event_type="review")

    args: dict[str, Any] = {}
    if _matches_tool_suffix(tool.name, "pull_request_read"):
        _set_arg(args, tool, "get_reviews", "method", required=True)
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(
        args,
        tool,
        int(pull_number),
        "pull_number",
        "pullNumber",
        required=True,
    )
    current = _prepare_remote_pagination(
        args,
        tool,
        page_size=limit,
        pagination=pagination,
    )
    payload = await client.call_tool(tool.name, args)
    items = _coerce_items(payload, "reviews")
    events = [
        _review_to_event(
            item,
            repository,
            parent_external_id=pull_number,
        )
        for item in items
    ]
    filtered = [
        event
        for event in events
        if _event_matches(
            event,
            start_at=start_at,
            end_at=end_at,
            timezone=timezone,
            actor=actor,
        )
    ]
    return _collected_page(
        filtered,
        tool=tool,
        payload=payload,
        raw_count=len(items),
        page_size=limit,
        current=current,
    )


def _initial_activity_tasks(
    repositories: list[str],
    event_types: tuple[GitHubActivityType, ...],
    *,
    page_size: int,
) -> list[_ActivityPageTask]:
    tasks: list[_ActivityPageTask] = []
    for repository in dict.fromkeys(repositories):
        for event_type in event_types:
            if event_type == "comment":
                tasks.extend(
                    _ActivityPageTask(
                        repository=repository,
                        event_type=event_type,
                        page_size=page_size,
                        parent_type=parent_type,
                        discover_parents=True,
                    )
                    for parent_type in ("issue", "pull_request")
                )
            elif event_type == "review":
                tasks.append(
                    _ActivityPageTask(
                        repository=repository,
                        event_type=event_type,
                        page_size=page_size,
                        parent_type="pull_request",
                        discover_parents=True,
                    )
                )
            else:
                tasks.append(
                    _ActivityPageTask(
                        repository=repository,
                        event_type=event_type,
                        page_size=page_size,
                    )
                )
    return tasks


async def _collect_activity_task(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    task: _ActivityPageTask,
    *,
    start_at: datetime,
    end_at: datetime,
    timezone: str,
    actor: str | None,
) -> _CollectedPage:
    common = {
        "repository": task.repository,
        "start_at": start_at,
        "end_at": end_at,
        "timezone": timezone,
        "actor": actor,
        "limit": task.page_size,
        "pagination": task.pagination,
    }
    if task.discover_parents:
        common["actor"] = None
        if task.parent_type == "pull_request":
            return await _collect_pull_requests(client, tools, **common)
        return await _collect_issues(client, tools, **common)
    if task.event_type == "commit":
        return await _collect_commits(client, tools, **common)
    if task.event_type == "pull_request":
        return await _collect_pull_requests(client, tools, **common)
    if task.event_type == "issue":
        return await _collect_issues(client, tools, **common)
    if task.event_type == "comment" and task.parent_external_id is not None:
        if task.parent_type == "pull_request":
            return await _collect_pull_request_comments(
                client,
                tools,
                pull_number=task.parent_external_id,
                **common,
            )
        return await _collect_issue_comments(
            client,
            tools,
            issue_number=task.parent_external_id,
            **common,
        )
    if task.event_type == "review" and task.parent_external_id is not None:
        return await _collect_pull_request_reviews(
            client,
            tools,
            pull_number=task.parent_external_id,
            **common,
        )
    raise MCPGatewayError(
        "configuration_error",
        "GitHub MCP activity pagination task is invalid.",
        retryable=False,
    )


def _child_tasks_from_parent_page(
    task: _ActivityPageTask,
    page: _CollectedPage,
) -> list[_ActivityPageTask]:
    parent_ids: list[str] = []
    seen: set[str] = set()
    for event in page.events:
        if event.external_id and event.external_id not in seen:
            seen.add(event.external_id)
            parent_ids.append(event.external_id)
    return [
        _ActivityPageTask(
            repository=task.repository,
            event_type=task.event_type,
            page_size=task.page_size,
            parent_external_id=parent_id,
            parent_type=task.parent_type,
        )
        for parent_id in parent_ids
    ]


async def github_mcp_search_activity(
    *,
    start_at: str | datetime,
    end_at: str | datetime,
    timezone: str = "Asia/Shanghai",
    provider: str = "github",
    repositories: list[str] | None = None,
    actor: str | None = "platform",
    event_types: list[GitHubActivityType] | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> GitHubActivityResult:
    """Search GitHub engineering activity through the MCP data source."""
    if provider != "github":
        return GitHubActivityResult(
            warnings=[
                _warning("configuration_error", "Only provider='github' is supported.")
            ]
        )
    start = _parse_datetime(start_at, timezone)
    end = _parse_datetime(end_at, timezone)
    if start is None or end is None or start > end:
        return GitHubActivityResult(
            warnings=[_warning("configuration_error", "Invalid activity time window.")]
        )

    selected_types = tuple(dict.fromkeys(event_types or _DEFAULT_EVENT_TYPES))
    if any(event_type not in _DEFAULT_EVENT_TYPES for event_type in selected_types):
        return GitHubActivityResult(
            warnings=[
                _warning("configuration_error", "Unsupported GitHub activity type.")
            ]
        )
    capped_limit = min(max(limit, 1), 100)
    query_key = _activity_query_key(
        start_at=start,
        end_at=end,
        timezone=timezone,
        repositories=repositories,
        actor=actor,
        event_types=selected_types,
    )
    cursor_tasks: list[_ActivityPageTask] | None = None
    if cursor is not None:
        try:
            cursor_tasks = _decode_activity_cursor(
                cursor,
                query_key=query_key,
                selected_types=selected_types,
                repositories=repositories,
            )
        except Exception:
            return GitHubActivityResult(
                warnings=[
                    _warning(
                        "configuration_error",
                        "Invalid or incompatible GitHub activity cursor.",
                    )
                ]
            )

    async def _operation(client: MCPGatewayClient) -> GitHubActivityResult:
        tools = await _tool_index(client)
        warnings: list[GitHubMCPWarning] = []
        activity_actor = actor
        if actor == "platform":
            identity = await _resolve_identity_with_tools(client, tools)
            activity_actor = _login_from_payload(identity)

        tasks = list(cursor_tasks) if cursor_tasks is not None else None
        repo_names = repositories if tasks is None else None
        if tasks is None and not repo_names:
            repo_names, discovery_warnings = await _discover_activity_repositories(
                client,
                tools,
                platform_login=activity_actor,
            )
            warnings.extend(discovery_warnings)
        if tasks is None:
            tasks = _initial_activity_tasks(
                repo_names or [],
                selected_types,
                page_size=capped_limit,
            )

        events: list[GitHubActivityEvent] = []
        page_calls = 0
        parent_page_cache: dict[
            tuple[str, str, int, _PaginationKind, int | str | None],
            _CollectedPage,
        ] = {}
        while tasks and len(events) < capped_limit:
            task = tasks.pop(0)
            parent_kind: str | None = None
            if task.parent_external_id is None:
                if task.discover_parents:
                    parent_kind = task.parent_type
                elif task.event_type in {"pull_request", "issue"}:
                    parent_kind = task.event_type
            cache_key = (
                (
                    task.repository,
                    parent_kind,
                    task.page_size,
                    task.pagination.kind,
                    task.pagination.value,
                )
                if parent_kind is not None
                else None
            )
            base_page = parent_page_cache.get(cache_key) if cache_key else None
            if base_page is None:
                if page_calls >= _MAX_PAGE_CALLS_PER_SEARCH:
                    tasks.insert(0, task)
                    break
                page_calls += 1
                try:
                    base_page = await _collect_activity_task(
                        client,
                        tools,
                        task,
                        start_at=start,
                        end_at=end,
                        timezone=timezone,
                        actor=None if cache_key else activity_actor,
                    )
                except Exception as exc:
                    warnings.append(_warning_from_error(exc))
                    if isinstance(exc, MCPGatewayError) and exc.retryable:
                        tasks.insert(0, task)
                        break
                    continue
                if cache_key is not None:
                    parent_page_cache[cache_key] = base_page

            page = base_page
            if (
                cache_key is not None
                and not task.discover_parents
                and activity_actor is not None
            ):
                page = _CollectedPage(
                    events=[
                        event
                        for event in base_page.events
                        if _actor_matches(event.actor, activity_actor)
                    ],
                    current=base_page.current,
                    next=base_page.next,
                    warning=base_page.warning,
                )
            if page.warning is not None:
                warnings.append(page.warning)

            if task.discover_parents:
                child_tasks = _child_tasks_from_parent_page(task, page)
                continuation: list[_ActivityPageTask] = []
                if page.next is not None:
                    task.pagination = page.next
                    task.offset = 0
                    continuation.append(task)
                # Append children and continuation to the end of the
                # queue so other event types get a fair share before we
                # dive deeper into the same type.  Without this, a
                # single event type (typically commits) can fill the
                # capped_limit before other types are ever touched.
                tasks.extend(child_tasks + continuation)
                continue

            remaining = capped_limit - len(events)
            page_events = page.events[task.offset :]
            emitted = page_events[:remaining]
            events.extend(emitted)
            consumed = task.offset + len(emitted)
            if consumed < len(page.events):
                task.pagination = page.current
                task.offset = consumed
                tasks.append(task)
            elif page.next is not None:
                task.pagination = page.next
                task.offset = 0
                tasks.append(task)

        if tasks and page_calls >= _MAX_PAGE_CALLS_PER_SEARCH:
            warnings.append(
                _warning(
                    "pagination_budget_exhausted",
                    "GitHub MCP activity search reached its per-request page budget; "
                    "continue with next_cursor.",
                    retryable=True,
                )
            )
        events.sort(key=lambda item: item.updated_at or item.created_at or "")
        next_cursor = _encode_activity_cursor(query_key, tasks) if tasks else None
        return GitHubActivityResult(
            events=events,
            warnings=warnings,
            next_cursor=next_cursor,
        )

    try:
        return await run_with_github_mcp_sts(_operation)
    except Exception as exc:
        return GitHubActivityResult(warnings=[_warning_from_error(exc)])


def _supported_issue_read_methods(tool: MCPToolInfo) -> tuple[str, ...]:
    method_schema = _schema_properties(tool).get("method")
    if not isinstance(method_schema, dict):
        return ("get",)

    enum = method_schema.get("enum")
    if not isinstance(enum, list):
        return ("get",)

    supported = tuple(method for method in _ISSUE_READ_METHODS if method in enum)
    if "get" not in supported:
        return ("get", *supported)
    return supported


def _issue_read_arguments(
    tool: MCPToolInfo,
    *,
    method: str,
    owner: str,
    repo: str,
    issue_number: int,
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    _set_arg(args, tool, method, "method", required=True)
    _set_arg(args, tool, owner, "owner", required=True)
    _set_arg(args, tool, repo, "repo", "repository", required=True)
    _set_arg(
        args,
        tool,
        issue_number,
        "issue_number",
        "issueNumber",
        "number",
        required=True,
    )
    return args


def _detail_item_by_external_id(
    payload: Any,
    external_id: str,
    *collection_keys: str,
) -> dict[str, Any]:
    for item in _coerce_items(payload, *collection_keys):
        item_id = next(
            (
                item.get(key)
                for key in ("id", "node_id", "review_id", "comment_id")
                if item.get(key) is not None
            ),
            None,
        )
        if item_id is not None and str(item_id) == external_id:
            return item

    raise MCPGatewayError(
        "mcp_error",
        "GitHub MCP activity detail item was not found.",
        retryable=False,
    )


def _detail_parent_number(
    event_type: GitHubActivityType,
    parent_external_id: str | None,
) -> tuple[int | None, GitHubMCPWarning | None]:
    parent_number: int | None = None
    if event_type in {"review", "comment"}:
        if not parent_external_id:
            return (
                None,
                _warning(
                    "configuration_error",
                    f"{event_type} detail requires parent_external_id.",
                ),
            )
        try:
            parent_number = int(parent_external_id)
        except ValueError:
            return (
                None,
                _warning(
                    "configuration_error",
                    "parent_external_id must be a PR or issue number.",
                ),
            )
        if parent_number < 1:
            return (
                None,
                _warning(
                    "configuration_error",
                    "parent_external_id must be a positive PR or issue number.",
                ),
            )
    return parent_number, None


async def _github_mcp_get_detail_with_tools(
    client: MCPGatewayClient,
    tools: dict[str, MCPToolInfo],
    *,
    event_type: GitHubActivityType,
    repository: str,
    external_id: str,
    parent_number: int | None,
) -> GitHubActivityEvent:
    owner, repo = _repo_parts(repository)
    if event_type == "commit":
        tool = _find_tool(tools, ("get_commit",))
        args: dict[str, Any] = {}
        _set_arg(args, tool, owner, "owner", required=True)
        _set_arg(args, tool, repo, "repo", "repository", required=True)
        _set_arg(args, tool, external_id, "sha", "ref", required=True)
        payload = await client.call_tool(tool.name, args)
        items = _coerce_items(payload)
        item = items[0] if items else {}
        event = _commit_to_event(item, repository)
        event.details = {"commit": item}
        return event

    if event_type == "pull_request":
        tool = _find_tool(tools, ("get_pull_request", "pull_request_read"))
        args = {}
        if _matches_tool_suffix(tool.name, "pull_request_read"):
            _set_arg(args, tool, "get", "method", required=True)
        _set_arg(args, tool, owner, "owner", required=True)
        _set_arg(args, tool, repo, "repo", "repository", required=True)
        _set_arg(
            args,
            tool,
            int(external_id),
            "pull_number",
            "pullNumber",
            "number",
            required=True,
        )
        payload = await client.call_tool(tool.name, args)
        items = _coerce_items(payload)
        item = items[0] if items else {}
        event = _pull_request_to_event(item, repository)
        event.details = {"pull_request": item}
        return event

    if event_type == "issue":
        tool = _find_tool(tools, ("issue_read", "get_issue"))
        if _matches_tool_suffix(tool.name, "issue_read"):
            payloads: dict[str, Any] = {}
            for method in _supported_issue_read_methods(tool):
                args = _issue_read_arguments(
                    tool,
                    method=method,
                    owner=owner,
                    repo=repo,
                    issue_number=int(external_id),
                )
                payloads[method] = await client.call_tool(tool.name, args)

            payload = payloads["get"]
            items = _coerce_items(payload)
            event = _issue_to_event(items[0] if items else {}, repository)
            event.details = {
                _ISSUE_DETAIL_KEYS[method]: value for method, value in payloads.items()
            }
            return event

        args = {}
        _set_arg(args, tool, owner, "owner", required=True)
        _set_arg(args, tool, repo, "repo", "repository", required=True)
        _set_arg(
            args,
            tool,
            int(external_id),
            "issue_number",
            "issueNumber",
            "number",
            required=True,
        )
        payload = await client.call_tool(tool.name, args)
        items = _coerce_items(payload)
        return _issue_to_event(items[0] if items else {}, repository)

    if event_type == "review":
        tool = _find_tool(
            tools,
            ("get_pull_request_reviews", "pull_request_read"),
        )
        args = {}
        if _matches_tool_suffix(tool.name, "pull_request_read"):
            _set_arg(args, tool, "get_reviews", "method", required=True)
        _set_arg(args, tool, owner, "owner", required=True)
        _set_arg(args, tool, repo, "repo", "repository", required=True)
        _set_arg(
            args,
            tool,
            parent_number,
            "pull_number",
            "pullNumber",
            "number",
            required=True,
        )
        payload = await client.call_tool(tool.name, args)
        item = _detail_item_by_external_id(payload, external_id, "reviews")
        event = _review_to_event(
            item,
            repository,
            parent_external_id=str(parent_number),
        )
        event.details = {"review": item}
        return event

    if event_type == "comment":
        tool = _find_tool(tools, ("get_issue_comments", "issue_read"))
        args = {}
        if _matches_tool_suffix(tool.name, "issue_read"):
            _set_arg(args, tool, "get_comments", "method", required=True)
        _set_arg(args, tool, owner, "owner", required=True)
        _set_arg(args, tool, repo, "repo", "repository", required=True)
        _set_arg(
            args,
            tool,
            parent_number,
            "issue_number",
            "issueNumber",
            "number",
            required=True,
        )
        payload = await client.call_tool(tool.name, args)
        item = _detail_item_by_external_id(payload, external_id, "comments")
        event = _comment_to_event(
            item,
            repository,
            parent_external_id=str(parent_number),
            title_prefix=f"Issue or pull request #{parent_number} comment",
        )
        event.details = {"comment": item}
        return event

    raise MCPGatewayError(
        "capability_missing",
        "Detail lookup supports commit, pull_request, and issue events.",
        retryable=False,
    )


async def github_mcp_get_detail(
    *,
    event_type: GitHubActivityType,
    repository: str,
    external_id: str,
    parent_external_id: str | None = None,
) -> GitHubActivityEvent | GitHubMCPWarning:
    """Fetch details for one GitHub activity event."""
    parent_number, validation_warning = _detail_parent_number(
        event_type,
        parent_external_id,
    )
    if validation_warning is not None:
        return validation_warning

    async def _operation(client: MCPGatewayClient) -> GitHubActivityEvent:
        tools = await _tool_index(client)
        return await _github_mcp_get_detail_with_tools(
            client,
            tools,
            event_type=event_type,
            repository=repository,
            external_id=external_id,
            parent_number=parent_number,
        )

    try:
        return await run_with_github_mcp_sts(_operation)
    except Exception as exc:
        return _warning_from_error(exc)


async def github_mcp_get_details(
    events: list[GitHubActivityEvent],
    *,
    max_concurrency: int = _MAX_CONCURRENT_DETAIL_CALLS,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[GitHubActivityEvent | GitHubMCPWarning]:
    """Fetch multiple activity details in one bounded MCP session."""
    if not events:
        return []

    concurrency = min(max(max_concurrency, 1), _MAX_CONCURRENT_DETAIL_CALLS)

    async def _operation(
        client: MCPGatewayClient,
    ) -> list[GitHubActivityEvent | GitHubMCPWarning]:
        tools = await _tool_index(client)
        semaphore = asyncio.Semaphore(concurrency)
        completed = 0

        def _notify_progress() -> None:
            nonlocal completed
            completed += 1
            if on_progress is None:
                return
            with suppress(Exception):
                # Observability must never change the collection result.
                on_progress(completed, len(events))

        async def _fetch(
            event: GitHubActivityEvent,
        ) -> GitHubActivityEvent | GitHubMCPWarning:
            try:
                parent_number, validation_warning = _detail_parent_number(
                    event.event_type,
                    event.parent_external_id,
                )
                if validation_warning is not None:
                    return validation_warning
                async with semaphore:
                    return await _github_mcp_get_detail_with_tools(
                        client,
                        tools,
                        event_type=event.event_type,
                        repository=event.repository,
                        external_id=event.external_id,
                        parent_number=parent_number,
                    )
            except Exception as exc:
                return _warning_from_error(exc)
            finally:
                _notify_progress()

        return list(await asyncio.gather(*(_fetch(event) for event in events)))

    try:
        return await run_with_github_mcp_sts(_operation)
    except Exception as exc:
        return [_warning_from_error(exc) for _ in events]


def github_mcp_public_schema_is_secret_free() -> bool:
    """Return whether internal source function signatures avoid credential names."""
    import inspect

    for func in (
        github_mcp_resolve_identity,
        github_mcp_list_repositories,
        github_mcp_search_activity,
        github_mcp_get_detail,
        github_mcp_get_details,
    ):
        names = {name.lower() for name in inspect.signature(func).parameters}
        if any(secret in name for name in names for secret in _SENSITIVE_WORDS):
            return False
    return True
