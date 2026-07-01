"""Tests for app.tools.gitee_tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tools import gitee_tools as gt


@pytest.fixture(autouse=True)
def unwrap_gitee_tools(monkeypatch):
    """Replace decorated tool functions with their undecorated originals."""
    raw = gt.list_repositories
    while hasattr(raw, "__wrapped__"):
        raw = raw.__wrapped__
    monkeypatch.setattr(gt, "list_repositories", raw)


@pytest.mark.asyncio
async def test_handle_auth_url_writes_auth_card():
    writer = MagicMock()
    with (
        patch("app.tools.gitee_tools.get_stream_writer", return_value=writer),
        patch("app.tools.gitee_tools.capture_github_authorization_url") as capture,
    ):
        await gt.handle_auth_url("https://example.test/gitee-auth")

    capture.assert_called_once_with("https://example.test/gitee-auth")
    writer.assert_called_once()
    event = writer.call_args.args[0]
    assert event["auth_url"] == "https://example.test/gitee-auth"
    assert event["auth_required"] is True
    assert event["provider"] == gt.get_gitee_provider_name()


@pytest.mark.asyncio
async def test_handle_auth_url_without_stream_context_is_graceful():
    with (
        patch(
            "app.tools.gitee_tools.get_stream_writer",
            side_effect=RuntimeError("not in graph context"),
        ),
        patch("app.tools.gitee_tools.logger") as logger,
    ):
        await gt.handle_auth_url("https://example.test/gitee-auth")

    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_list_repositories_returns_structure(monkeypatch):
    async def fake_request(method, path, *, params=None, access_token=None):
        assert method == "GET"
        assert path == "/user/repos"
        assert params["visibility"] == "all"
        assert params["sort"] == "full_name"
        assert params["page"] == 1
        assert params["per_page"] == 20
        return [
            {
                "name": "repo-a",
                "full_name": "alice/repo-a",
                "private": True,
                "human_name": "Repo A",
                "namespace": {"path": "alice"},
                "html_url": "https://gitee.com/alice/repo-a",
            }
        ]

    monkeypatch.setattr("app.tools.gitee_tools._gitee_request", fake_request)

    result = await gt.list_repositories(access_token="fake")
    assert result["ok"] is True
    assert result["count"] == 1
    repo = result["repositories"][0]
    assert repo["full_name"] == "alice/repo-a"
    assert repo["namespace"] == "alice"
    assert repo["private"] is True


@pytest.mark.asyncio
async def test_list_repositories_clamps_pagination(monkeypatch):
    async def fake_request(method, path, *, params=None, access_token=None):
        assert params["page"] == 1
        assert params["per_page"] == 100
        return []

    monkeypatch.setattr("app.tools.gitee_tools._gitee_request", fake_request)

    result = await gt.list_repositories(page=0, per_page=200, access_token="fake")
    assert result["ok"] is True
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_repositories_rejects_conflicting_filters(monkeypatch):
    async def fake_request(method, path, *, params=None, access_token=None):
        raise AssertionError("validation should happen before Gitee request")

    monkeypatch.setattr("app.tools.gitee_tools._gitee_request", fake_request)

    result = await gt.list_repositories(
        visibility="private",
        repo_type="owner",
        access_token="fake",
    )
    assert result["ok"] is False
    assert "repo_type cannot be combined" in result["message"]


@pytest.mark.asyncio
async def test_auth_required_response_when_no_token(monkeypatch):
    result = await gt.list_repositories(access_token=None)
    assert result["auth_required"] is True
    assert "Authorization pending" in result["error"]
