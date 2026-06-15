"""Read-only GitHub repository tools for enduser delegated access."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

import httpx
from agentarts.sdk import require_access_token
from langchain_core.tools import tool

from app.identity import (
    DEFAULT_GITHUB_SCOPES,
    GITHUB_PROVIDER_NAME,
    AuthorizationRequired,
    GitHubAuthorizationRequiredPoller,
    capture_github_authorization_url,
    get_github_oauth2_callback_url,
)

GITHUB_API_BASE_URL = "https://api.github.com"


@dataclass(slots=True)
class GitHubToolError:
    """Structured tool response when GitHub access is unavailable."""

    ok: bool
    message: str
    authorization_url: str | None = None
    provider_name: str | None = None
    details: str | None = None


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
    async with httpx.AsyncClient(base_url=GITHUB_API_BASE_URL, timeout=30.0) as client:
        response = await client.request(method, path, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


@require_access_token(
    provider_name=GITHUB_PROVIDER_NAME,
    into="access_token",
    scopes=list(DEFAULT_GITHUB_SCOPES),
    on_auth_url=capture_github_authorization_url,
    auth_flow="USER_FEDERATION",
    callback_url=get_github_oauth2_callback_url(),
    force_authentication=False,
    token_poller=GitHubAuthorizationRequiredPoller(),
)
async def _github_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    access_token: str,
) -> Any:
    return await _raw_github_request(access_token, method, path, params=params)


def _authorization_error(exc: AuthorizationRequired) -> dict[str, Any]:
    return asdict(
        GitHubToolError(
            ok=False,
            message=exc.message,
            authorization_url=exc.authorization_url,
            provider_name=exc.provider_name,
        )
    )


async def list_repositories() -> list[dict[str, Any]] | dict[str, Any]:
    """List repositories visible to the current enduser."""

    try:
        data = await _github_request("GET", "/user/repos")
        return [_repo_item_to_dict(_normalize_repo_item(item)) for item in data]
    except AuthorizationRequired as exc:
        return _authorization_error(exc)


async def list_repo_contents(
    owner: str,
    repo: str,
    path: str = "",
) -> list[dict[str, Any]] | dict[str, Any]:
    """List a repository directory or return a single file entry."""

    encoded_path = quote(path.strip("/"), safe="/")
    api_path = f"/repos/{owner}/{repo}/contents"
    if encoded_path:
        api_path = f"{api_path}/{encoded_path}"
    try:
        data = await _github_request("GET", api_path)
        if isinstance(data, list):
            return [
                _content_item_to_dict(_normalize_content_item(item)) for item in data
            ]
        return [_content_item_to_dict(_normalize_content_item(data))]
    except AuthorizationRequired as exc:
        return _authorization_error(exc)


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
        return _content_item_to_dict(_normalize_content_item(data))
    except AuthorizationRequired as exc:
        return _authorization_error(exc)


async def search_code(query: str) -> list[dict[str, Any]] | dict[str, Any]:
    """Search GitHub code with the delegated enduser token."""

    try:
        data = await _github_request("GET", "/search/code", params={"q": query})
        return list(data.get("items", []))
    except AuthorizationRequired as exc:
        return _authorization_error(exc)


github_tools = [
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
]
