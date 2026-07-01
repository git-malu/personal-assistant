"""Gitee repository tools for delegated end-user access."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx
from agentarts.sdk import require_access_token
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.identity import (
    capture_github_authorization_url,
    get_gitee_provider_name,
)

logger = logging.getLogger(__name__)

GITEE_API_BASE_URL = "https://gitee.com/api/v5"
DEFAULT_GITEE_SCOPES = ("user_info", "projects")

GiteeVisibility = Literal["all", "public", "private"]
GiteeRepoType = Literal["all", "owner", "personal", "member", "public", "private"]
GiteeSort = Literal["created", "updated", "pushed", "full_name"]
GiteeDirection = Literal["asc", "desc"]


def _push_auth_complete(provider: str) -> None:
    """Push an ``auth_complete`` event to the frontend via the stream writer.

    Called from within a tool function body after the SDK decorator has
    successfully resolved the access token — meaning the user completed
    authorization.  The frontend uses this to transition the AuthCard
    from its blue "awaiting" state to a green "complete" state.
    """
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "system_message",
                "system_message": "授权已完成",
                "auth_complete": True,
                "provider": provider,
            }
        )
    except RuntimeError:
        logger.warning("get_stream_writer unavailable — auth_complete not streamed")


async def handle_auth_url(auth_url: str) -> None:
    """Push the Gitee authorization URL to the frontend as an auth card."""
    capture_github_authorization_url(auth_url)
    logger.info("Gitee authorization required — auth URL: %s", auth_url)
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "system_message",
                "system_message": "Gitee 功能需要您的授权。请点击该链接进行授权",
                "auth_url": auth_url,
                "auth_required": True,
                "provider": get_gitee_provider_name(),
            }
        )
    except RuntimeError:
        logger.warning(
            "get_stream_writer unavailable (not in graph context) — "
            "Gitee auth URL not streamed: %s",
            auth_url,
        )


@dataclass(slots=True)
class GiteeToolError:
    ok: bool
    message: str
    authorization_url: str | None = None
    provider_name: str | None = None
    details: str | None = None


@dataclass(slots=True)
class GiteeRepositoryItem:
    name: str
    full_name: str
    private: bool
    human_name: str | None = None
    path: str | None = None
    namespace: str | None = None
    description: str | None = None
    html_url: str | None = None
    default_branch: str | None = None
    updated_at: str | None = None


def _normalize_repo_item(item: dict[str, Any]) -> GiteeRepositoryItem:
    namespace = item.get("namespace")
    namespace_path = None
    if isinstance(namespace, dict):
        namespace_path = namespace.get("path") or namespace.get("name")
    elif isinstance(namespace, str):
        namespace_path = namespace

    name = str(item.get("name") or item.get("path") or "")
    full_name = str(item.get("full_name") or item.get("path_with_namespace") or name)
    return GiteeRepositoryItem(
        name=name,
        full_name=full_name,
        private=bool(item.get("private", False)),
        human_name=item.get("human_name"),
        path=item.get("path"),
        namespace=namespace_path,
        description=item.get("description"),
        html_url=item.get("html_url"),
        default_branch=item.get("default_branch"),
        updated_at=item.get("updated_at"),
    )


def _repo_item_to_dict(item: GiteeRepositoryItem) -> dict[str, Any]:
    return asdict(item)


def _auth_required_response() -> dict[str, Any]:
    """Return a tool result indicating authorization is pending."""
    return {
        "auth_required": True,
        "error": (
            "Authorization pending. Please follow the authorization link sent to you."
        ),
    }


async def _raw_gitee_request(
    access_token: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    query = {k: v for k, v in (params or {}).items() if v is not None}
    query["access_token"] = access_token
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(base_url=GITEE_API_BASE_URL, timeout=30.0) as client:
        response = await client.request(method, path, headers=headers, params=query)
        response.raise_for_status()
        if response.status_code == httpx.codes.NO_CONTENT or not response.content:
            return None
        return response.json()


async def _gitee_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    access_token: str,
) -> Any:
    return await _raw_gitee_request(access_token, method, path, params=params)


@require_access_token(
    provider_name=get_gitee_provider_name(),
    into="access_token",
    scopes=list(DEFAULT_GITEE_SCOPES),
    on_auth_url=handle_auth_url,
    auth_flow="USER_FEDERATION",
)
async def list_repositories(
    visibility: GiteeVisibility = "all",
    affiliation: str | None = None,
    repo_type: GiteeRepoType | None = None,
    sort: GiteeSort = "full_name",
    direction: GiteeDirection | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 20,
    access_token: str | None = None,
) -> dict[str, Any]:
    """List repositories visible to the current Gitee end user."""
    if not access_token:
        return _auth_required_response()
    _push_auth_complete(get_gitee_provider_name())
    if repo_type and (visibility != "all" or affiliation):
        return {
            "ok": False,
            "message": (
                "repo_type cannot be combined with visibility or affiliation "
                "because Gitee returns 422 for that combination."
            ),
        }

    params = {
        "visibility": visibility,
        "affiliation": affiliation,
        "type": repo_type,
        "sort": sort,
        "direction": direction,
        "q": q,
        "page": max(page, 1),
        "per_page": min(max(per_page, 1), 100),
    }
    try:
        data = await _gitee_request(
            "GET", "/user/repos", params=params, access_token=access_token
        )
        items = [
            _repo_item_to_dict(_normalize_repo_item(item))
            for item in data
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "count": len(items),
            "page": params["page"],
            "per_page": params["per_page"],
            "repositories": items,
        }
    except Exception as e:
        logger.exception("list_repositories failed")
        return {"ok": False, "message": f"Request failed: {e!s}"}


GITEE_TOOLS = [
    tool(
        "gitee_list_repositories",
        description=(
            "List repositories visible to the current Gitee end user. Uses the "
            "AgentArts OAuth2 access token from the configured gitee-provider."
        ),
    )(list_repositories),
]
