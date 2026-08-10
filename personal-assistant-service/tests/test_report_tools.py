"""Tests for the Feature 18 Report root capability."""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.mcp.github_activity_source import (
    GitHubActivityEvent,
    GitHubActivityResult,
    GitHubMCPWarning,
)
from app.tools import github_activity_tools, report_tools
from app.tools.github_tools import GitHubReportContext
from app.tools.report_tools import (
    generate_report,
    resolve_report_window,
    select_report_sources,
)


@pytest.fixture(autouse=True)
def authorize_report_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Report tests isolated from AgentArts OAuth network calls."""

    async def authorize_github() -> str:
        return "github-report-token"

    async def authorize_email() -> str:
        return "email-report-token"

    async def authorize_calendar() -> str:
        return "calendar-report-token"

    monkeypatch.setattr(
        report_tools,
        "authorize_github_report_access",
        authorize_github,
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_email_report_access",
        authorize_email,
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_calendar_report_access",
        authorize_calendar,
    )


@pytest.mark.parametrize(
    ("report_type", "expected_start", "expected_end"),
    [
        (
            "daily",
            "2026-07-21T00:00:00+08:00",
            "2026-07-21T23:59:59+08:00",
        ),
        (
            "weekly",
            "2026-07-20T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
        ),
        (
            "monthly",
            "2026-07-01T00:00:00+08:00",
            "2026-07-31T23:59:59+08:00",
        ),
    ],
)
def test_resolve_report_window_for_natural_periods(
    report_type: str,
    expected_start: str,
    expected_end: str,
) -> None:
    window = resolve_report_window(
        report_type,  # type: ignore[arg-type]
        timezone="Asia/Shanghai",
        now=datetime(2026, 7, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert window.start_at == expected_start
    assert window.end_at == expected_end
    assert window.timezone == "Asia/Shanghai"


def test_resolve_custom_window_normalizes_timezone_and_date_end() -> None:
    window = resolve_report_window(
        "custom",
        start_at="2026-07-20T16:00:00Z",
        end_at="2026-07-21",
        timezone="Asia/Shanghai",
    )

    assert window.start_at == "2026-07-21T00:00:00+08:00"
    assert window.end_at == "2026-07-21T23:59:59+08:00"


@pytest.mark.parametrize(
    ("report_type", "expected_start", "expected_end"),
    [
        (
            "daily",
            "2024-02-14T00:00:00+08:00",
            "2024-02-14T23:59:59+08:00",
        ),
        (
            "weekly",
            "2024-02-12T00:00:00+08:00",
            "2024-02-18T23:59:59+08:00",
        ),
        (
            "monthly",
            "2024-02-01T00:00:00+08:00",
            "2024-02-29T23:59:59+08:00",
        ),
    ],
)
def test_explicit_reference_date_overrides_current_period(
    report_type: str,
    expected_start: str,
    expected_end: str,
) -> None:
    window = resolve_report_window(
        report_type,  # type: ignore[arg-type]
        reference_date="2024-02-14",
        timezone="Asia/Shanghai",
        now=datetime(2026, 7, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert window.start_at == expected_start
    assert window.end_at == expected_end


def test_explicit_date_range_overrides_report_type_period() -> None:
    window = resolve_report_window(
        "weekly",
        start_at="2024-03-05",
        end_at="2024-03-07",
        timezone="Asia/Shanghai",
        now=datetime(2026, 7, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert window.start_at == "2024-03-05T00:00:00+08:00"
    assert window.end_at == "2024-03-07T23:59:59+08:00"


@pytest.mark.parametrize("date_parameter", ["start_at", "end_at"])
def test_single_legacy_date_parameter_is_used_as_reference_date(
    date_parameter: str,
) -> None:
    window = resolve_report_window(
        "daily",
        timezone="Asia/Shanghai",
        now=datetime(2026, 7, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        **{date_parameter: "2024-04-09"},
    )

    assert window.start_at == "2024-04-09T00:00:00+08:00"
    assert window.end_at == "2024-04-09T23:59:59+08:00"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"report_type": "custom"}, "require both"),
        (
            {
                "report_type": "custom",
                "start_at": "2026-07-22",
                "end_at": "2026-07-21",
            },
            "must not be later",
        ),
        (
            {"report_type": "daily", "timezone": "Unknown/Timezone"},
            "Unknown timezone",
        ),
        (
            {
                "report_type": "daily",
                "reference_date": "2024-02-14",
                "start_at": "2024-02-14",
                "end_at": "2024-02-14",
            },
            "cannot be combined",
        ),
    ],
)
def test_resolve_report_window_rejects_invalid_input(
    kwargs: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_report_window(**kwargs)  # type: ignore[arg-type]


def test_select_report_sources_defaults_to_all_sources() -> None:
    expected = ("github", "email", "calendar")

    assert select_report_sources(None) == expected
    assert select_report_sources([]) == expected


def test_select_report_sources_preserves_order_and_deduplicates() -> None:
    assert select_report_sources(["calendar", "github", "calendar"]) == (
        "calendar",
        "github",
    )

    with pytest.raises(ValueError, match="Unsupported report source"):
        select_report_sources(["unknown"])


@pytest.mark.asyncio
async def test_generate_report_combines_default_sources_and_internal_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email_calls: list[tuple[str, int]] = []
    github_kwargs: dict[str, object] = {}

    async def fake_list_emails(
        folder: str,
        limit: int,
        *,
        access_token: str,
    ) -> dict[str, object]:
        assert access_token == "email-report-token"
        email_calls.append((folder, limit))
        if folder == "inbox":
            emails = [
                {
                    "id": "mail-in",
                    "subject": "项目同步",
                    "from": "Alice",
                    "receivedDateTime": "2026-07-21T09:00:00+08:00",
                    "bodyPreview": "完成接口联调",
                    "importance": "normal",
                    "isRead": True,
                },
                {
                    "id": "mail-old",
                    "subject": "窗口外邮件",
                    "receivedDateTime": "2026-07-20T09:00:00+08:00",
                },
            ]
        else:
            emails = [
                {
                    "id": "mail-sent",
                    "subject": "已发送进展",
                    "from": "Me",
                    "receivedDateTime": "2026-07-21T17:00:00+08:00",
                    "bodyPreview": "周报材料",
                    "importance": "normal",
                    "isRead": True,
                }
            ]
        return {"emails": emails, "count": len(emails), "folder": folder}

    async def fake_list_calendar_events(**kwargs) -> dict[str, object]:
        assert kwargs["start_time"] == "2026-07-21T00:00:00+08:00"
        assert kwargs["end_time"] == "2026-07-21T23:59:59+08:00"
        return {
            "events": [
                {
                    "id": "event-1",
                    "subject": "研发例会",
                    "start": {
                        "dateTime": "2026-07-21T02:00:00",
                        "timeZone": "UTC",
                    },
                    "location": "线上",
                    "organizer": {"name": "Bob", "address": "bob@example.com"},
                    "attendees": [{"name": "Alice"}],
                    "bodyPreview": "同步开发进度",
                    "webLink": "https://calendar.example/event-1",
                },
                {
                    "id": "event-windows-timezone",
                    "subject": "时区回退会议",
                    "start": {
                        "dateTime": "2026-07-21T11:00:00",
                        "timeZone": "China Standard Time",
                    },
                    "organizer": {"name": "Carol"},
                },
                {
                    "id": "event-overlap",
                    "subject": "跨日发布窗口",
                    "start": {
                        "dateTime": "2026-07-20T23:00:00",
                        "timeZone": "Asia/Shanghai",
                    },
                    "end": {
                        "dateTime": "2026-07-21T01:00:00",
                        "timeZone": "Asia/Shanghai",
                    },
                    "organizer": {"name": "Deployment bot"},
                },
            ],
            "count": 3,
            "timezone": "Asia/Shanghai",
            "has_more": False,
        }

    async def fake_github_search(**kwargs) -> GitHubActivityResult:
        github_kwargs.update(kwargs)
        return GitHubActivityResult(
            events=[
                GitHubActivityEvent(
                    provider="github",
                    event_type="commit",
                    repository="owner/repo",
                    external_id="abc123",
                    title="Implement report root tool",
                    actor="OAuth-User",
                    created_at="2026-07-21T03:00:00Z",
                    summary="Add deterministic report orchestration",
                )
            ]
        )

    async def fake_github_context(access_token: str) -> GitHubReportContext:
        assert access_token == "github-report-token"
        return GitHubReportContext(
            login="oauth-user",
            user_id=1001,
            repositories=("owner/repo",),
        )

    async def fake_github_details(
        events,
        *,
        on_progress=None,
    ) -> list[GitHubActivityEvent]:
        assert [
            (
                event.event_type,
                event.repository,
                event.external_id,
                event.parent_external_id,
            )
            for event in events
        ] == [("commit", "owner/repo", "abc123", None)]
        details = [
            GitHubActivityEvent(
                provider="github",
                event_type="commit",
                repository="owner/repo",
                external_id="abc123",
                title="Implement report root tool",
                actor="oauth-user",
                created_at="2026-07-21T03:00:00Z",
                summary="Add deterministic report orchestration",
                metrics={"additions": 20, "deletions": 3},
                details={"files": [{"filename": "app/report.py"}]},
            )
        ]
        if on_progress is not None:
            on_progress(1, 1)
        return details

    async def fail_agent_facade(*args, **kwargs):
        pytest.fail("Report must not call the Agent-facing GitHub facade")

    monkeypatch.setattr(report_tools, "list_emails", fake_list_emails)
    monkeypatch.setattr(
        report_tools,
        "list_calendar_events",
        fake_list_calendar_events,
    )
    monkeypatch.setattr(
        report_tools,
        "github_mcp_search_activity",
        fake_github_search,
    )
    monkeypatch.setattr(report_tools, "get_github_report_context", fake_github_context)
    monkeypatch.setattr(report_tools, "github_mcp_get_details", fake_github_details)
    monkeypatch.setattr(
        github_activity_tools,
        "github_search_activity",
        fail_agent_facade,
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
    )

    assert email_calls == [("inbox", 50), ("sentitems", 50)]
    assert github_kwargs["actor"] == "oauth-user"
    assert github_kwargs["repositories"] == ["owner/repo"]
    assert github_kwargs["timezone"] == "Asia/Shanghai"
    assert result["source_coverage"] == {
        "github": "ok",
        "email": "ok",
        "calendar": "ok",
    }
    assert [item["source"] for item in result["evidence"]].count("email") == 2
    assert {item["source"] for item in result["evidence"]} == {
        "github",
        "email",
        "calendar",
    }
    calendar_evidence = next(
        item for item in result["evidence"] if item["source_id"] == "event-1"
    )
    assert calendar_evidence["occurred_at"] == "2026-07-21T10:00:00+08:00"
    fallback_evidence = next(
        item
        for item in result["evidence"]
        if item["source_id"] == "event-windows-timezone"
    )
    assert fallback_evidence["occurred_at"] == "2026-07-21T11:00:00+08:00"
    overlap_evidence = next(
        item for item in result["evidence"] if item["source_id"] == "event-overlap"
    )
    assert overlap_evidence["occurred_at"] == "2026-07-20T23:00:00+08:00"
    assert overlap_evidence["metadata"]["end_at"] == "2026-07-21T01:00:00+08:00"
    github_evidence = next(
        item for item in result["evidence"] if item["source"] == "github"
    )
    assert github_evidence["source_id"] == "abc123"
    assert github_evidence["metadata"]["subject_login"] == "oauth-user"
    assert github_evidence["metadata"]["repository_scope"] == "oauth_accessible"
    assert github_evidence["metadata"]["data_access_identity"] == "platform_mcp"
    assert github_evidence["metadata"]["detail_available"] is True
    assert "details" not in github_evidence["metadata"]
    assert result["source_context"]["github"] == {
        "subject_login": "oauth-user",
        "subject_user_id": 1001,
        "repository_scope": "oauth_accessible",
        "repository_count": 1,
        "data_access_identity": "platform_mcp",
    }
    assert "# 工作总结" in result["content"]
    json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_generate_report_follows_all_github_pages_before_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_calls: list[str | None] = []
    detail_calls: list[str] = []
    large_patch = "+" * 4_000
    large_detail = {
        "commit": {
            "files": [
                {"filename": f"src/generated-{index}.py", "patch": large_patch}
                for index in range(50)
            ]
        }
    }

    async def fake_github_search(**kwargs) -> GitHubActivityResult:
        search_calls.append(kwargs["cursor"])
        page = 1 if kwargs["cursor"] is None else 2
        base_at = (
            "2026-07-21T00:00:00+08:00" if page == 1 else "2026-07-22T00:00:00+08:00"
        )
        count = 100 if page == 1 else 30
        prefix = "old" if page == 1 else "new"
        events = [
            GitHubActivityEvent(
                provider="github",
                event_type="commit",
                repository="owner/repo",
                external_id=f"{prefix}-{index:03d}",
                title=f"{prefix} commit {index:03d}",
                actor="OAuth-User",
                created_at=base_at,
                summary=f"{prefix} summary {index:03d}",
            )
            for index in range(count)
        ]
        return GitHubActivityResult(
            events=events,
            warnings=(
                [
                    GitHubMCPWarning(
                        ok=False,
                        warning_type="pagination_budget_exhausted",
                        message="page budget exhausted",
                        retryable=True,
                    )
                ]
                if page == 1
                else []
            ),
            next_cursor="cursor-2" if page == 1 else None,
        )

    async def fake_github_context(access_token: str) -> GitHubReportContext:
        assert access_token == "github-report-token"
        return GitHubReportContext(
            login="oauth-user",
            user_id=1001,
            repositories=("owner/repo",),
        )

    async def fake_github_details(
        events,
        *,
        on_progress=None,
    ) -> list[GitHubActivityEvent]:
        details: list[GitHubActivityEvent] = []
        for index, event in enumerate(events, start=1):
            detail_calls.append(event.external_id)
            prefix = "old" if event.external_id.startswith("old-") else "new"
            details.append(
                GitHubActivityEvent(
                    provider="github",
                    event_type="commit",
                    repository="owner/repo",
                    external_id=event.external_id,
                    title=(
                        f"{prefix} commit {event.external_id.split('-', maxsplit=1)[1]}"
                    ),
                    actor="oauth-user",
                    created_at=(
                        "2026-07-21T00:00:00+08:00"
                        if prefix == "old"
                        else "2026-07-22T00:00:00+08:00"
                    ),
                    summary=f"{prefix} summary",
                    details=large_detail,
                )
            )
            if on_progress is not None:
                on_progress(index, len(events))
        return details

    monkeypatch.setattr(report_tools, "github_mcp_search_activity", fake_github_search)
    monkeypatch.setattr(report_tools, "get_github_report_context", fake_github_context)
    monkeypatch.setattr(report_tools, "github_mcp_get_details", fake_github_details)
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-22",
        sources=["github"],
    )

    assert search_calls == [None, "cursor-2"]
    assert len(detail_calls) == 100
    assert len(result["evidence"]) == 100
    assert result["evidence"][0]["source_id"].startswith("new-")
    assert result["source_coverage"]["github"] == "partial"
    assert {warning["warning_type"] for warning in result["warnings"]} == {
        "github_activity_truncated"
    }
    assert all(
        item["metadata"]["detail_available"] is True
        and "details" not in item["metadata"]
        for item in result["evidence"]
    )
    serialized = json.dumps(result, ensure_ascii=False).encode("utf-8")
    assert len(serialized) <= 256 * 1024


@pytest.mark.asyncio
async def test_generate_report_degrades_each_failed_source_without_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_sentinel = "do-not-leak-credential-value"

    async def failed_email(**kwargs) -> dict[str, str]:
        return {"error": f"Authorization: Bearer {secret_sentinel}"}

    async def failed_calendar(**kwargs):
        raise RuntimeError(secret_sentinel)

    async def partial_github(**kwargs) -> GitHubActivityResult:
        return GitHubActivityResult(
            events=[
                GitHubActivityEvent(
                    provider="github",
                    event_type="issue",
                    repository="owner/repo",
                    external_id="42",
                    title="Track report work",
                    actor="oauth-user",
                    created_at="2026-07-21T12:00:00+08:00",
                )
            ],
            warnings=[
                GitHubMCPWarning(
                    ok=False,
                    warning_type="sts_exchange_failed",
                    message=f"Bearer {secret_sentinel}",
                    retryable=True,
                )
            ],
        )

    async def fake_github_context(access_token: str) -> GitHubReportContext:
        assert access_token == "github-report-token"
        return GitHubReportContext(
            login="oauth-user",
            user_id=1001,
            repositories=("owner/repo",),
        )

    async def keep_summaries(events) -> list[GitHubMCPWarning]:
        return [
            GitHubMCPWarning(
                ok=False,
                warning_type="detail_unavailable",
                message=f"Bearer {secret_sentinel}",
                retryable=True,
            )
            for _ in events
        ]

    monkeypatch.setattr(report_tools, "list_emails", failed_email)
    monkeypatch.setattr(report_tools, "list_calendar_events", failed_calendar)
    monkeypatch.setattr(
        report_tools,
        "github_mcp_search_activity",
        partial_github,
    )
    monkeypatch.setattr(report_tools, "get_github_report_context", fake_github_context)
    monkeypatch.setattr(report_tools, "github_mcp_get_details", keep_summaries)
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
    )

    assert result["source_coverage"] == {
        "github": "partial",
        "email": "unavailable",
        "calendar": "unavailable",
    }
    assert {item["source"] for item in result["evidence"]} == {"github"}
    assert {warning["source"] for warning in result["warnings"]} == {
        "github",
        "email",
        "calendar",
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert secret_sentinel not in serialized
    assert "Authorization:" not in serialized
    assert "Bearer " not in serialized


@pytest.mark.asyncio
async def test_generate_report_github_oauth_failure_never_calls_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed_oauth(access_token: str) -> GitHubReportContext:
        assert access_token == "github-report-token"
        raise RuntimeError("oauth unavailable")

    async def unexpected_mcp(**kwargs):
        pytest.fail("MCP must not run when GitHub OAuth context is unavailable")

    monkeypatch.setattr(report_tools, "get_github_report_context", failed_oauth)
    monkeypatch.setattr(report_tools, "github_mcp_search_activity", unexpected_mcp)
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="daily",
        reference_date="2026-07-21",
        sources=["github"],
    )

    assert result["evidence"] == []
    assert result["source_coverage"]["github"] == "unavailable"
    assert result["warnings"][0]["warning_type"] == "github_oauth_unavailable"


@pytest.mark.asyncio
async def test_generate_report_empty_oauth_repository_allowlist_skips_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_context(access_token: str) -> GitHubReportContext:
        assert access_token == "github-report-token"
        return GitHubReportContext(
            login="oauth-user",
            user_id=1001,
            repositories=(),
        )

    async def unexpected_mcp(**kwargs):
        pytest.fail(
            "MCP must not discover repositories outside an empty OAuth allowlist"
        )

    monkeypatch.setattr(report_tools, "get_github_report_context", empty_context)
    monkeypatch.setattr(report_tools, "github_mcp_search_activity", unexpected_mcp)
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="daily",
        reference_date="2026-07-21",
        sources=["github"],
    )

    assert result["evidence"] == []
    assert result["warnings"] == []
    assert result["source_coverage"]["github"] == "ok"
    assert result["source_context"]["github"]["repository_count"] == 0


@pytest.mark.asyncio
async def test_generate_report_marks_disabled_github_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_email(**kwargs) -> dict[str, object]:
        return {"emails": [], "count": 0}

    async def empty_calendar(**kwargs) -> dict[str, object]:
        return {"events": [], "count": 0, "has_more": False}

    async def fail_github(**kwargs):
        pytest.fail("Disabled GitHub source must not be called")

    async def fail_github_context() -> GitHubReportContext:
        pytest.fail("Disabled GitHub source must not resolve OAuth context")

    async def fail_github_auth() -> str:
        pytest.fail("Disabled GitHub source must not request OAuth authorization")

    monkeypatch.setattr(report_tools, "list_emails", empty_email)
    monkeypatch.setattr(report_tools, "list_calendar_events", empty_calendar)
    monkeypatch.setattr(report_tools, "github_mcp_search_activity", fail_github)
    monkeypatch.setattr(report_tools, "get_github_report_context", fail_github_context)
    monkeypatch.setattr(
        report_tools,
        "authorize_github_report_access",
        fail_github_auth,
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=False),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
    )

    assert result["source_coverage"] == {
        "github": "unavailable",
        "email": "ok",
        "calendar": "ok",
    }
    assert any(
        warning["warning_type"] == "github_source_disabled"
        for warning in result["warnings"]
    )


@pytest.mark.asyncio
async def test_generate_report_respects_explicit_source_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_calendar(**kwargs) -> dict[str, object]:
        return {"events": [], "count": 0, "has_more": False}

    async def unexpected_call(**kwargs):
        pytest.fail("Unselected source was called")

    monkeypatch.setattr(report_tools, "list_calendar_events", empty_calendar)
    monkeypatch.setattr(report_tools, "list_emails", unexpected_call)
    monkeypatch.setattr(report_tools, "github_mcp_search_activity", unexpected_call)

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
        sources=["calendar", "calendar"],
    )

    assert result["source_coverage"] == {
        "github": "skipped",
        "email": "skipped",
        "calendar": "ok",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sources", "expected_trace"),
    [
        (
            None,
            [
                "auth:github",
                "auth:email",
                "auth:calendar",
                "collect:github",
                "collect:email",
                "collect:calendar",
            ],
        ),
        (
            ["calendar", "github"],
            [
                "auth:github",
                "auth:calendar",
                "collect:calendar",
                "collect:github",
            ],
        ),
    ],
)
async def test_generate_report_authorizes_selected_sources_before_collection(
    monkeypatch: pytest.MonkeyPatch,
    sources: list[str] | None,
    expected_trace: list[str],
) -> None:
    trace: list[str] = []

    def authorization(source: str):
        async def run() -> str:
            trace.append(f"auth:{source}")
            return f"{source}-token"

        return run

    def collector(source: str):
        async def run(window, *, access_token: str, progress=None):
            del window
            assert progress is not None
            assert access_token == f"{source}-token"
            trace.append(f"collect:{source}")
            return report_tools._SourceResult()

        return run

    monkeypatch.setattr(
        report_tools,
        "authorize_github_report_access",
        authorization("github"),
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_email_report_access",
        authorization("email"),
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_calendar_report_access",
        authorization("calendar"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_github_evidence",
        collector("github"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_email_evidence",
        collector("email"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_calendar_evidence",
        collector("calendar"),
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
        sources=sources,  # type: ignore[arg-type]
    )

    assert trace == expected_trace


@pytest.mark.asyncio
async def test_generate_report_collects_authorized_sources_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_complete = False
    started = {source: asyncio.Event() for source in ("github", "email", "calendar")}
    release_collection = asyncio.Event()

    def authorization(source: str):
        async def run() -> str:
            nonlocal authorization_complete
            if source == "calendar":
                authorization_complete = True
            return f"{source}-token"

        return run

    def collector(source: str):
        async def run(window, *, access_token: str, progress=None):
            del window
            assert authorization_complete is True
            assert access_token == f"{source}-token"
            assert progress is not None
            started[source].set()
            await release_collection.wait()
            return report_tools._SourceResult()

        return run

    monkeypatch.setattr(
        report_tools,
        "authorize_github_report_access",
        authorization("github"),
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_email_report_access",
        authorization("email"),
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_calendar_report_access",
        authorization("calendar"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_github_evidence",
        collector("github"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_email_evidence",
        collector("email"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_calendar_evidence",
        collector("calendar"),
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    report_task = asyncio.create_task(
        generate_report(
            report_type="custom",
            start_at="2026-07-21",
            end_at="2026-07-21",
        )
    )
    await asyncio.wait_for(
        asyncio.gather(*(event.wait() for event in started.values())),
        timeout=1,
    )
    assert report_task.done() is False

    release_collection.set()
    result = await report_task

    assert result["source_coverage"] == {
        "github": "ok",
        "email": "ok",
        "calendar": "ok",
    }


@pytest.mark.asyncio
async def test_generate_report_finishes_later_auth_after_one_source_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []

    async def authorize_github() -> str:
        trace.append("auth:github")
        return "github-token"

    async def authorize_email() -> str:
        trace.append("auth:email")
        raise RuntimeError("authorization unavailable")

    async def authorize_calendar() -> str:
        trace.append("auth:calendar")
        return "calendar-token"

    def collector(source: str):
        async def run(window, *, access_token: str, progress=None):
            del window
            assert progress is not None
            assert access_token == f"{source}-token"
            trace.append(f"collect:{source}")
            return report_tools._SourceResult()

        return run

    monkeypatch.setattr(
        report_tools,
        "authorize_github_report_access",
        authorize_github,
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_email_report_access",
        authorize_email,
    )
    monkeypatch.setattr(
        report_tools,
        "authorize_calendar_report_access",
        authorize_calendar,
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_github_evidence",
        collector("github"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_email_evidence",
        collector("email"),
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_calendar_evidence",
        collector("calendar"),
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
    )

    assert trace == [
        "auth:github",
        "auth:email",
        "auth:calendar",
        "collect:github",
        "collect:calendar",
    ]
    assert result["source_coverage"] == {
        "github": "ok",
        "email": "unavailable",
        "calendar": "ok",
    }
    assert result["warnings"] == [
        {
            "source": "email",
            "warning_type": "email_oauth_unavailable",
            "message": "邮件 OAuth 授权暂不可用。",
            "retryable": True,
        }
    ]


@pytest.mark.asyncio
async def test_generate_report_closes_auth_card_after_authorization_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[dict[str, object]] = []
    secret_sentinel = "authorization-secret-must-not-leak"

    async def authorize_github() -> str:
        report_tools.get_stream_writer()(
            {
                "type": "system_message",
                "system_message": "GitHub authorization required",
                "auth_url": "https://auth.example.com/github",
                "auth_required": True,
                "provider": "github-provider",
            }
        )
        raise RuntimeError(secret_sentinel)

    async def fail_collection(*args, **kwargs):
        del args, kwargs
        pytest.fail("Authorization failure must prevent GitHub collection")

    monkeypatch.setattr(
        report_tools,
        "authorize_github_report_access",
        authorize_github,
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_github_evidence",
        fail_collection,
    )
    monkeypatch.setattr(
        report_tools,
        "get_github_provider_name",
        lambda: "github-provider",
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )
    monkeypatch.setattr(report_tools, "get_stream_writer", lambda: events.append)

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
        sources=["github"],
    )

    lifecycle_events = [
        event
        for event in events
        if event.get("auth_required")
        or event.get("auth_failed")
        or event.get("report_ready")
    ]
    assert [
        "auth_required"
        if event.get("auth_required")
        else "auth_failed"
        if event.get("auth_failed")
        else "report_ready"
        for event in lifecycle_events
    ] == ["auth_required", "auth_failed", "report_ready"]
    assert lifecycle_events[1] == {
        "type": "system_message",
        "system_message": "GitHub 授权未完成，请重试。",
        "auth_failed": True,
        "provider": "github-provider",
    }
    assert result["source_coverage"]["github"] == "unavailable"
    assert secret_sentinel not in json.dumps(events, ensure_ascii=False)
    assert secret_sentinel not in json.dumps(result, ensure_ascii=False)
    assert secret_sentinel not in caplog.text


@pytest.mark.asyncio
async def test_empty_calendar_token_emits_auth_failed_with_oauth_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []

    async def authorize_calendar() -> str:
        return ""

    monkeypatch.setattr(
        report_tools,
        "authorize_calendar_report_access",
        authorize_calendar,
    )
    monkeypatch.setattr(report_tools, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(
        report_tools.AgentArtsRuntimeContext,
        "get_oauth2_custom_state",
        lambda: "signed-calendar-state",
    )

    authorization = await report_tools._authorize_report_sources(("calendar",))

    assert authorization.access_tokens == {}
    assert authorization.failures["calendar"].coverage == "unavailable"
    assert events == [
        {
            "type": "system_message",
            "system_message": "日历授权未完成，请重试。",
            "auth_failed": True,
            "provider": report_tools.CALENDAR_PROVIDER,
            "oauth2_state": "signed-calendar-state",
        }
    ]


@pytest.mark.asyncio
async def test_generate_report_sanitizes_unexpected_collector_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_sentinel = "collector-secret-must-not-leak"

    async def fail_github(window, *, access_token: str, progress=None):
        del window, access_token, progress
        raise RuntimeError(secret_sentinel)

    async def collect_calendar(window, *, access_token: str, progress=None):
        del window, access_token, progress
        return report_tools._SourceResult()

    monkeypatch.setattr(
        report_tools,
        "_collect_github_evidence",
        fail_github,
    )
    monkeypatch.setattr(
        report_tools,
        "_collect_calendar_evidence",
        collect_calendar,
    )
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
        sources=["github", "calendar"],
    )

    assert result["source_coverage"] == {
        "github": "unavailable",
        "email": "skipped",
        "calendar": "ok",
    }
    assert result["warnings"] == [
        {
            "source": "github",
            "warning_type": "github_source_unavailable",
            "message": "GitHub 工程活动数据源暂不可用。",
            "retryable": True,
        }
    ]
    assert secret_sentinel not in json.dumps(result, ensure_ascii=False)
    assert secret_sentinel not in caplog.text


def test_report_authorization_repr_hides_access_tokens() -> None:
    secret_sentinel = "report-preflight-secret"
    authorization = report_tools._ReportAuthorization(
        access_tokens={"github": secret_sentinel}
    )

    assert secret_sentinel not in repr(authorization)
    assert "access_tokens" not in repr(authorization)


def test_generate_report_public_schema_is_secret_free() -> None:
    credential_names = {
        "access_token",
        "api_key",
        "authorization",
        "secret",
        "pat",
        "ak",
        "sk",
        "sts",
        "token",
        "credential",
    }

    params = set(inspect.signature(generate_report).parameters)

    assert params.isdisjoint(credential_names)
    assert "reference_date" in params


def test_report_progress_emitter_uses_safe_monotonic_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(report_tools, "get_stream_writer", lambda: events.append)
    emitter = report_tools._ReportProgressEmitter()

    emitter.emit(stage="preparing", status="running", force=True)
    emitter.emit(
        source="github",
        stage="activity_detail",
        status="running",
        current=18,
        total=37,
        discovered=37,
        force=True,
    )

    assert [event["sequence"] for event in events] == [1, 2]
    assert events[1] == {
        "type": "report_progress",
        "report_progress": True,
        "sequence": 2,
        "source": "github",
        "stage": "activity_detail",
        "status": "running",
        "current": 18,
        "total": 37,
        "discovered": 37,
    }
    assert all("system_message" not in event for event in events)


def test_report_progress_emitter_ignores_writer_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def broken_writer(event: dict[str, object]) -> None:
        nonlocal calls
        del event
        calls += 1
        raise ValueError("writer unavailable")

    monkeypatch.setattr(report_tools, "get_stream_writer", lambda: broken_writer)
    emitter = report_tools._ReportProgressEmitter()

    emitter.emit(stage="preparing", status="running", force=True)

    assert calls == 1


@pytest.mark.asyncio
async def test_generate_report_passes_explicit_reference_date_to_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def capture_calendar(**kwargs) -> dict[str, object]:
        captured["start_time"] = kwargs["start_time"]
        captured["end_time"] = kwargs["end_time"]
        return {"events": [], "count": 0, "has_more": False}

    monkeypatch.setattr(report_tools, "list_calendar_events", capture_calendar)

    result = await generate_report(
        report_type="weekly",
        reference_date="2024-02-14",
        sources=["calendar"],
    )

    assert captured == {
        "start_time": "2024-02-12T00:00:00+08:00",
        "end_time": "2024-02-18T23:59:59+08:00",
    }
    assert result["window"] == {
        "start_at": captured["start_time"],
        "end_at": captured["end_time"],
        "timezone": "Asia/Shanghai",
    }


@pytest.mark.asyncio
async def test_generate_report_streams_original_markdown_download_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []

    async def empty_calendar(**kwargs) -> dict[str, object]:
        del kwargs
        return {"events": [], "count": 0, "has_more": False}

    monkeypatch.setattr(report_tools, "list_calendar_events", empty_calendar)
    monkeypatch.setattr(report_tools, "get_stream_writer", lambda: events.append)

    result = await generate_report(
        report_type="daily",
        reference_date="2024-02-14",
        sources=["calendar"],
    )

    progress_events = [
        event for event in events if event.get("type") == "report_progress"
    ]
    ready_events = [event for event in events if event.get("type") == "report_ready"]
    assert progress_events
    assert [event["sequence"] for event in progress_events] == list(
        range(1, len(progress_events) + 1)
    )
    assert all("system_message" not in event for event in progress_events)
    assert len(ready_events) == 1
    assert ready_events[0] == {
        "type": "report_ready",
        "report_ready": True,
        "report_format": "markdown",
        "report_filename": "日报-2024-02-14.md",
        "report_content": result["content"],
        "report_type": "daily",
        "report_window": result["window"],
    }


@pytest.mark.asyncio
async def test_generate_report_redacts_credentials_inside_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_sentinel = "feature18-secret-sentinel"
    github_token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"

    async def credential_email(
        folder: str,
        limit: int,
        *,
        access_token: str,
    ) -> dict[str, object]:
        assert access_token == "email-report-token"
        del limit
        if folder == "sentitems":
            return {"emails": [], "count": 0}
        return {
            "emails": [
                {
                    "id": "credential-mail",
                    "subject": f"Bearer {secret_sentinel}",
                    "from": "Security bot",
                    "receivedDateTime": "2026-07-21T09:00:00+08:00",
                    "bodyPreview": (
                        f"Authorization: Bearer {secret_sentinel} "
                        f"AK={secret_sentinel} SK={secret_sentinel} {github_token}"
                    ),
                }
            ],
            "count": 1,
        }

    async def credential_github(**kwargs) -> GitHubActivityResult:
        return GitHubActivityResult(
            events=[
                GitHubActivityEvent(
                    provider="github",
                    event_type="commit",
                    repository="owner/repo",
                    external_id="credential-event",
                    title="Sanitize evidence",
                    actor="oauth-user",
                    created_at="2026-07-21T10:00:00+08:00",
                    summary=f"Bearer {secret_sentinel}",
                    metrics={
                        "access_token": secret_sentinel,
                        "note": f"SK={secret_sentinel}",
                    },
                )
            ]
        )

    async def fake_github_context(access_token: str) -> GitHubReportContext:
        assert access_token == "github-report-token"
        return GitHubReportContext(
            login="oauth-user",
            user_id=1001,
            repositories=("owner/repo",),
        )

    async def credential_details(events) -> list[GitHubActivityEvent]:
        detail = (await credential_github()).events[0]
        return [detail for _ in events]

    monkeypatch.setattr(report_tools, "list_emails", credential_email)
    monkeypatch.setattr(
        report_tools,
        "github_mcp_search_activity",
        credential_github,
    )
    monkeypatch.setattr(report_tools, "get_github_report_context", fake_github_context)
    monkeypatch.setattr(report_tools, "github_mcp_get_details", credential_details)
    monkeypatch.setattr(
        report_tools,
        "get_settings",
        lambda: SimpleNamespace(github_mcp_enabled=True),
    )

    result = await generate_report(
        report_type="custom",
        start_at="2026-07-21",
        end_at="2026-07-21",
        sources=["email", "github"],
    )

    serialized = json.dumps(result, ensure_ascii=False)
    assert secret_sentinel not in serialized
    assert github_token not in serialized
    assert "access_token" not in serialized
    assert "[REDACTED]" in serialized
