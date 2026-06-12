from typing import Annotated, Literal

import httpx
from agentarts.sdk import require_access_token
from langchain_core.tools import InjectedToolArg, tool

PROJECT_OWNER = "git-malu"
PROJECT_REPO = "personal-assistant"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_PROVIDER_NAME = "github-provider"
GITHUB_SCOPES = ["repo", "read:user"]

IssueState = Literal["open", "closed", "all"]


class GitHubToolError(RuntimeError):
    """Raised when GitHub returns an error that should be visible to the agent."""


def _normalize_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _raise_for_github_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return

    messages = {
        401: "GitHub authorization failed. Please reconnect your GitHub account.",
        403: "GitHub denied this request. Check repository permission or rate limit.",
        404: f"GitHub repository {PROJECT_OWNER}/{PROJECT_REPO} was not found.",
    }
    default = f"GitHub API request failed with status {response.status_code}."

    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or "")
    except ValueError:
        detail = response.text[:200]

    message = messages.get(response.status_code, default)
    if detail:
        message = f"{message} Detail: {detail}"
    raise GitHubToolError(message)


def _issue_summary(item: dict) -> dict:
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "html_url": item.get("html_url"),
        "author": (item.get("user") or {}).get("login"),
        "updated_at": item.get("updated_at"),
        "labels": [label.get("name") for label in item.get("labels", [])],
    }


def _pull_request_summary(item: dict) -> dict:
    summary = _issue_summary(item)
    summary.update(
        {
            "draft": item.get("draft"),
            "base": (item.get("base") or {}).get("ref"),
            "head": (item.get("head") or {}).get("ref"),
        }
    )
    return summary


async def fetch_project_issues(
    *,
    access_token: str,
    state: IssueState = "open",
    limit: int = 20,
) -> list[dict]:
    """Fetch repository issues and filter out pull requests."""
    per_page = _normalize_limit(limit)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{PROJECT_OWNER}/{PROJECT_REPO}/issues",
            headers=_headers(access_token),
            params={"state": state, "per_page": per_page},
        )
    _raise_for_github_error(response)

    items = response.json()
    if not isinstance(items, list):
        raise GitHubToolError("GitHub issues response was not a list.")
    issues = [item for item in items if "pull_request" not in item]
    return [_issue_summary(item) for item in issues[:per_page]]


async def fetch_project_pull_requests(
    *,
    access_token: str,
    state: IssueState = "open",
    limit: int = 20,
) -> list[dict]:
    """Fetch repository pull requests."""
    per_page = _normalize_limit(limit)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{PROJECT_OWNER}/{PROJECT_REPO}/pulls",
            headers=_headers(access_token),
            params={"state": state, "per_page": per_page},
        )
    _raise_for_github_error(response)

    items = response.json()
    if not isinstance(items, list):
        raise GitHubToolError("GitHub pull requests response was not a list.")
    return [_pull_request_summary(item) for item in items[:per_page]]


async def _list_project_issues_impl(
    state: IssueState = "open",
    limit: int = 20,
    access_token: Annotated[str | None, InjectedToolArg] = None,
) -> list[dict]:
    """List issues for git-malu/personal-assistant, excluding pull requests."""
    if not access_token:
        raise GitHubToolError("Missing GitHub access token from AgentArts Identity.")
    return await fetch_project_issues(
        access_token=access_token,
        state=state,
        limit=limit,
    )


async def _list_project_pull_requests_impl(
    state: IssueState = "open",
    limit: int = 20,
    access_token: Annotated[str | None, InjectedToolArg] = None,
) -> list[dict]:
    """List pull requests for git-malu/personal-assistant."""
    if not access_token:
        raise GitHubToolError("Missing GitHub access token from AgentArts Identity.")
    return await fetch_project_pull_requests(
        access_token=access_token,
        state=state,
        limit=limit,
    )


list_project_issues = tool(
    "list_project_issues",
    description="List issues for git-malu/personal-assistant, excluding pull requests.",
)(
    require_access_token(
        provider_name=GITHUB_PROVIDER_NAME,
        scopes=GITHUB_SCOPES,
        auth_flow="USER_FEDERATION",
    )(_list_project_issues_impl)
)
list_project_pull_requests = tool(
    "list_project_pull_requests",
    description="List pull requests for git-malu/personal-assistant.",
)(
    require_access_token(
        provider_name=GITHUB_PROVIDER_NAME,
        scopes=GITHUB_SCOPES,
        auth_flow="USER_FEDERATION",
    )(_list_project_pull_requests_impl)
)

GITHUB_TOOLS = [list_project_issues, list_project_pull_requests]
