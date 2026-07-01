"""GitHub repository tools for delegated end-user access."""

from __future__ import annotations

import base64
import logging
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

import httpx
from agentarts.sdk import require_access_token
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.identity import (
    capture_github_authorization_url,
    get_github_provider_name,
    get_github_scopes_list,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"


# ---------------------------------------------------------------------------
# Auth-stream helpers
# ---------------------------------------------------------------------------


async def _handle_auth_url(auth_url: str) -> None:
    """Push the GitHub authorization URL to the frontend as an auth card."""
    capture_github_authorization_url(auth_url)
    logger.info("GitHub authorization required — auth URL: %s", auth_url)
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "system_message",
                "system_message": "GitHub 功能需要您的授权。请点击该链接进行授权",
                "auth_url": auth_url,
                "auth_required": True,
                "provider": get_github_provider_name(),
            }
        )
    except RuntimeError:
        logger.warning(
            "get_stream_writer unavailable — GitHub auth URL not streamed: %s",
            auth_url,
        )


def _push_auth_complete() -> None:
    """Push an ``auth_complete`` event to the frontend via the stream writer."""
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "system_message",
                "system_message": "GitHub 授权已完成 ✅",
                "auth_complete": True,
                "provider": get_github_provider_name(),
            }
        )
    except RuntimeError:
        logger.warning(
            "get_stream_writer unavailable — GitHub auth_complete not streamed"
        )


def _auth_required_response() -> dict[str, Any]:
    """Return a tool result indicating authorization is pending."""
    return {
        "auth_required": True,
        "error": (
            "GitHub authorization pending. Please follow the authorization link."
        ),
    }


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GitHubRepositoryItem:
    name: str
    full_name: str
    private: bool
    default_branch: str | None = None
    html_url: str | None = None


@dataclass(slots=True)
class GitHubContentItem:
    path: str
    type: str
    name: str | None = None
    size: int | None = None
    sha: str | None = None
    download_url: str | None = None
    content: str | None = None
    encoding: str | None = None


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def _normalize_repo_item(item: dict[str, Any]) -> GitHubRepositoryItem:
    return GitHubRepositoryItem(
        name=item.get("name", ""),
        full_name=item.get("full_name", item.get("name", "")),
        private=bool(item.get("private", False)),
        default_branch=item.get("default_branch"),
        html_url=item.get("html_url"),
    )


def _repo_item_to_dict(item: GitHubRepositoryItem) -> dict[str, Any]:
    return asdict(item)


def _normalize_content_item(item: dict[str, Any]) -> GitHubContentItem:
    content = item.get("content")
    encoding = item.get("encoding")
    decoded_content: str | None = None
    if content and encoding == "base64":
        decoded_content = base64.b64decode(content).decode("utf-8", errors="replace")
    elif isinstance(content, str):
        decoded_content = content

    return GitHubContentItem(
        path=item.get("path", ""),
        type=item.get("type", "file"),
        name=item.get("name"),
        size=item.get("size"),
        sha=item.get("sha"),
        download_url=item.get("download_url"),
        content=decoded_content,
        encoding=encoding,
    )


def _content_item_to_dict(item: GitHubContentItem) -> dict[str, Any]:
    return asdict(item)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _raw_github_request(
    access_token: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if method.upper() == "PUT":
        headers["Content-Length"] = "0"
    async with httpx.AsyncClient(base_url=GITHUB_API_BASE_URL, timeout=30.0) as client:
        response = await client.request(method, path, headers=headers, params=params)
        response.raise_for_status()
        if response.status_code == httpx.codes.NO_CONTENT or not response.content:
            return None
        return response.json()


# ---------------------------------------------------------------------------
# Decorated request helper (auth gate)
# ---------------------------------------------------------------------------


@require_access_token(
    provider_name=get_github_provider_name(),
    into="access_token",
    scopes=get_github_scopes_list(),
    on_auth_url=_handle_auth_url,
    auth_flow="USER_FEDERATION",
)
async def _github_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    access_token: str | None = None,
) -> Any:
    if not access_token:
        return _auth_required_response()
    _push_auth_complete()
    return await _raw_github_request(access_token, method, path, params=params)


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


async def list_repositories() -> list[dict[str, Any]] | dict[str, Any]:
    """List repositories visible to the current end user."""
    try:
        data = await _github_request("GET", "/user/repos")
        if isinstance(data, dict) and data.get("auth_required"):
            return data
        return [_repo_item_to_dict(_normalize_repo_item(item)) for item in data]
    except Exception as e:
        logger.exception("list_repositories failed")
        return {"ok": False, "error": f"Request failed: {e!s}"}


async def list_repo_contents(
    owner: str,
    repo: str,
    path: str = "",
) -> dict[str, Any]:
    """List a repository directory or return a single file entry."""
    encoded_path = quote(path.strip("/"), safe="/")
    api_path = f"/repos/{owner}/{repo}/contents"
    if encoded_path:
        api_path = f"{api_path}/{encoded_path}"
    try:
        data = await _github_request("GET", api_path)
        if isinstance(data, dict) and data.get("auth_required"):
            return data
        if isinstance(data, list):
            items = [
                _content_item_to_dict(_normalize_content_item(item)) for item in data
            ]
        else:
            items = [_content_item_to_dict(_normalize_content_item(data))]
        return {
            "owner": owner,
            "repo": repo,
            "path": path.strip("/"),
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        logger.exception("list_repo_contents failed")
        return {"ok": False, "error": f"Request failed: {e!s}"}


async def get_file_content(
    owner: str,
    repo: str,
    path: str,
    *,
    ref: str | None = None,
) -> dict[str, Any]:
    """Fetch and decode a text file from GitHub."""
    params = {"ref": ref} if ref else None
    encoded_path = quote(path.strip("/"), safe="/")
    api_path = (
        f"/repos/{owner}/{repo}/contents/{encoded_path}"
        if encoded_path
        else f"/repos/{owner}/{repo}/contents"
    )
    try:
        data = await _github_request("GET", api_path, params=params)
        if isinstance(data, dict) and data.get("auth_required"):
            return data
        return _content_item_to_dict(_normalize_content_item(data))
    except Exception as e:
        logger.exception("get_file_content failed")
        return {"ok": False, "error": f"Request failed: {e!s}"}


async def search_code(query: str) -> list[dict[str, Any]] | dict[str, Any]:
    """Search GitHub code with the delegated end-user token."""
    try:
        data = await _github_request("GET", "/search/code", params={"q": query})
        if isinstance(data, dict) and data.get("auth_required"):
            return data
        return list(data.get("items", []))
    except Exception as e:
        logger.exception("search_code failed")
        return {"ok": False, "error": f"Request failed: {e!s}"}


async def star_repository(
    owner: str,
    repo: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Star a GitHub repository for the current end user after confirmation."""
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        return {
            "starred": False,
            "repository": None,
            "error": "owner and repo are required",
        }

    repository = f"{owner}/{repo}"
    if not confirm:
        return {
            "starred": False,
            "repository": repository,
            "requires_confirmation": True,
            "preview": {"owner": owner, "repo": repo, "repository": repository},
            "error": "请确认是否为该 GitHub 仓库点赞。调用时设置 confirm=True。",
        }

    encoded_owner = quote(owner, safe="")
    encoded_repo = quote(repo, safe="")
    try:
        data = await _github_request(
            "PUT", f"/user/starred/{encoded_owner}/{encoded_repo}"
        )
        if isinstance(data, dict) and data.get("auth_required"):
            return data
        return {"starred": True, "repository": repository, "error": None}
    except Exception as e:
        logger.exception("star_repository failed")
        return {
            "starred": False,
            "repository": repository,
            "error": f"Request failed: {e!s}",
        }


GITHUB_TOOLS = [
    tool(
        "github_list_repositories",
        description=(
            "List GitHub repositories visible to the current end user. "
            "Returns repository names, privacy flags, default branches, and URLs."
        ),
    )(list_repositories),
    tool(
        "github_list_repo_contents",
        description=(
            "List files and directories in a GitHub repository path visible to "
            "the current end user."
        ),
    )(list_repo_contents),
    tool(
        "github_get_file_content",
        description=(
            "Fetch and decode a text file from a GitHub repository visible to "
            "the current end user."
        ),
    )(get_file_content),
    tool(
        "github_search_code",
        description=(
            "Search GitHub code visible to the current end user using GitHub "
            "search query syntax."
        ),
    )(search_code),
    tool(
        "github_star_repository",
        description=(
            "Star a GitHub repository for the current end user. This is a "
            "sensitive write operation: call with confirm=False to preview, "
            "then call with confirm=True only after explicit user confirmation."
        ),
    )(star_repository),
]
