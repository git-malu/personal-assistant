"""High-level Report tool that orchestrates existing read-only data sources."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from langgraph.config import get_stream_writer

from app.identity import get_github_provider_name
from app.mcp.github_activity_source import (
    GitHubActivityEvent,
    GitHubActivityResult,
    GitHubMCPWarning,
    github_mcp_get_detail,
    github_mcp_get_details,
    github_mcp_search_activity,
)
from app.settings import get_settings
from app.tools.calendar_tools import (
    CALENDAR_PROVIDER,
    authorize_calendar_report_access,
)
from app.tools.calendar_tools import (
    _list_calendar_events_for_report as list_calendar_events,
)
from app.tools.email_tools import (
    EMAIL_PROVIDER,
    authorize_email_report_access,
)
from app.tools.email_tools import (
    _list_emails_authorized as list_emails,
)
from app.tools.github_tools import (
    GitHubReportContext,
    authorize_github_report_access,
)
from app.tools.github_tools import (
    _get_github_report_context_authorized as get_github_report_context,
)

logger = logging.getLogger(__name__)

type ReportType = Literal["daily", "weekly", "monthly", "custom"]
type ReportSource = Literal["email", "calendar", "github"]
type ReportAudience = Literal["self", "team"]
type ReportFormat = Literal["markdown"]
type SourceCoverage = Literal["ok", "partial", "unavailable", "skipped"]
type ReportProgressStage = Literal[
    "preparing",
    "github_context",
    "activity_search",
    "activity_detail",
    "email_collection",
    "calendar_collection",
    "rendering",
]
type ReportProgressStatus = Literal["running", "complete", "failed", "skipped"]

_DEFAULT_SOURCES: tuple[ReportSource, ...] = ("github", "email", "calendar")
_SOURCE_LABELS: dict[ReportSource, str] = {
    "email": "邮件",
    "calendar": "日历",
    "github": "GitHub 工程活动",
}
_REPORT_TITLES: dict[ReportType, str] = {
    "daily": "日报",
    "weekly": "周报",
    "monthly": "月报",
    "custom": "工作总结",
}
_EMAIL_FOLDERS = ("inbox", "sentitems")
_EMAIL_LIMIT_PER_FOLDER = 50
_CALENDAR_LIMIT = 50
_GITHUB_LIMIT = 100
_MAX_ITEMS_PER_SECTION = 12
_PROGRESS_MIN_INTERVAL_SECONDS = 0.35
_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GITHUB_CREDENTIAL_PATTERN = re.compile(
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    re.IGNORECASE,
)
_AUTHORIZATION_CREDENTIAL_PATTERN = re.compile(
    r"\bauthorization\b\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?[^\s,;]+",
    re.IGNORECASE,
)
_BEARER_CREDENTIAL_PATTERN = re.compile(
    r"\bbearer\b\s+[^\s,;]+",
    re.IGNORECASE,
)
_ASSIGNED_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:access[_ -]?token|api[_ -]?key|x[_ -]?api[_ -]?key|token|"
    r"client[_ -]?secret|secret|security[_ -]?token|x[_ -]?security[_ -]?token|"
    r"credential|sts|pat|ak/?sk|ak|sk)\b"
    r"\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_WARNING_TYPE_SENSITIVE_PARTS = (
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "token",
    "credential",
    "secret",
    "security_token",
    "sts",
    "signature",
    "pat",
    "ak_sk",
)


@dataclass(frozen=True, slots=True)
class ReportWindow:
    start_at: str
    end_at: str
    timezone: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class ReportEvidence:
    source: ReportSource
    source_id: str
    title: str
    occurred_at: str
    summary: str
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        serialized = asdict(self)
        serialized["metadata"] = _safe_metadata(serialized["metadata"])
        return serialized


@dataclass(frozen=True, slots=True)
class ReportWarning:
    source: ReportSource
    warning_type: str
    message: str
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReportResult:
    report_type: ReportType
    window: ReportWindow
    content: str
    evidence: list[ReportEvidence]
    warnings: list[ReportWarning]
    source_coverage: dict[ReportSource, SourceCoverage]
    source_context: dict[ReportSource, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_type": self.report_type,
            "window": self.window.to_dict(),
            "content": self.content,
            "evidence": [item.to_dict() for item in self.evidence],
            "warnings": [item.to_dict() for item in self.warnings],
            "source_coverage": dict(self.source_coverage),
            "source_context": _safe_metadata(self.source_context),
        }


def _report_filename(report_type: ReportType, window: ReportWindow) -> str:
    start_date = window.start_at[:10]
    end_date = window.end_at[:10]
    date_label = start_date if start_date == end_date else f"{start_date}_{end_date}"
    return f"{_REPORT_TITLES[report_type]}-{date_label}.md"


def _push_report_ready(
    *,
    content: str,
    filename: str,
    report_type: ReportType,
    window: ReportWindow,
) -> None:
    """Stream the generated Markdown to the matching Web Chat message."""
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "report_ready",
                "report_ready": True,
                "report_format": "markdown",
                "report_filename": filename,
                "report_content": content,
                "report_type": report_type,
                "report_window": window.to_dict(),
            }
        )
    except RuntimeError:
        logger.warning(
            "get_stream_writer unavailable - report download event not streamed"
        )


@dataclass(slots=True)
class _ReportProgressEmitter:
    """Emit ordered, throttled report progress without exposing source data."""

    sequence: int = 0
    _last_emitted_at: float = field(default=0.0, repr=False)
    _writer_unavailable_logged: bool = field(default=False, repr=False)

    def emit(
        self,
        *,
        stage: ReportProgressStage,
        status: ReportProgressStatus,
        source: ReportSource | None = None,
        current: int | None = None,
        total: int | None = None,
        discovered: int | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if (
            not force
            and self._last_emitted_at
            and now - self._last_emitted_at < _PROGRESS_MIN_INTERVAL_SECONDS
        ):
            return

        self.sequence += 1
        event: dict[str, Any] = {
            "type": "report_progress",
            "report_progress": True,
            "sequence": self.sequence,
            "stage": stage,
            "status": status,
        }
        if source is not None:
            event["source"] = source
        if current is not None:
            event["current"] = max(current, 0)
        if total is not None:
            event["total"] = max(total, 0)
        if discovered is not None:
            event["discovered"] = max(discovered, 0)

        try:
            writer = get_stream_writer()
            writer(event)
            self._last_emitted_at = now
        except Exception:
            if not self._writer_unavailable_logged:
                logger.warning(
                    "get_stream_writer unavailable - report progress not streamed"
                )
                self._writer_unavailable_logged = True


@dataclass(slots=True)
class _SourceResult:
    evidence: list[ReportEvidence] = field(default_factory=list)
    warnings: list[ReportWarning] = field(default_factory=list)
    coverage: SourceCoverage = "ok"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _ReportAuthorization:
    """Results of the pre-collection authorization phase."""

    access_tokens: dict[ReportSource, str] = field(
        default_factory=dict,
        repr=False,
    )
    failures: dict[ReportSource, _SourceResult] = field(default_factory=dict)


def _authorization_failure(source: ReportSource) -> _SourceResult:
    warning_types: dict[ReportSource, str] = {
        "github": "github_oauth_unavailable",
        "email": "email_oauth_unavailable",
        "calendar": "calendar_oauth_unavailable",
    }
    messages: dict[ReportSource, str] = {
        "github": "GitHub OAuth 授权或账号上下文暂不可用。",
        "email": "邮件 OAuth 授权暂不可用。",
        "calendar": "日历 OAuth 授权暂不可用。",
    }
    return _SourceResult(
        warnings=[
            _warning(
                source,
                warning_types[source],
                messages[source],
                retryable=True,
            )
        ],
        coverage="unavailable",
    )


def _push_report_auth_failed(source: ReportSource) -> None:
    """Close a pending Report AuthCard without exposing failure details."""
    messages: dict[ReportSource, str] = {
        "github": "GitHub 授权未完成，请重试。",
        "email": "邮件授权未完成，请重试。",
        "calendar": "日历授权未完成，请重试。",
    }
    try:
        if source == "github":
            provider = get_github_provider_name()
        elif source == "email":
            provider = EMAIL_PROVIDER
        else:
            provider = CALENDAR_PROVIDER
        event: dict[str, Any] = {
            "type": "system_message",
            "system_message": messages[source],
            "auth_failed": True,
            "provider": provider,
        }
    except Exception:
        logger.warning(
            "Report auth_failed event could not be prepared source=%s",
            source,
        )
        return

    if source == "calendar":
        try:
            oauth2_state = AgentArtsRuntimeContext.get_oauth2_custom_state()
        except Exception:
            oauth2_state = None
            logger.warning("Calendar OAuth state unavailable for report auth_failed")
        if oauth2_state:
            event["oauth2_state"] = oauth2_state

    try:
        get_stream_writer()(event)
    except Exception:
        logger.warning("Report auth_failed event not streamed source=%s", source)


def _github_disabled_result() -> _SourceResult:
    return _SourceResult(
        warnings=[
            _warning(
                "github",
                "github_source_disabled",
                "GitHub MCP 工程活动数据源未启用。",
            )
        ],
        coverage="unavailable",
    )


def _source_progress_stage(source: ReportSource) -> ReportProgressStage:
    if source == "github":
        return "github_context"
    if source == "email":
        return "email_collection"
    return "calendar_collection"


def _collection_failure(source: ReportSource) -> _SourceResult:
    messages: dict[ReportSource, str] = {
        "github": "GitHub 工程活动数据源暂不可用。",
        "email": "邮件数据源暂不可用。",
        "calendar": "日历数据源暂不可用。",
    }
    return _SourceResult(
        warnings=[
            _warning(
                source,
                f"{source}_source_unavailable",
                messages[source],
                retryable=True,
            )
        ],
        coverage="unavailable",
    )


async def _authorize_report_sources(
    selected: tuple[ReportSource, ...],
) -> _ReportAuthorization:
    """Authorize selected sources in canonical order before any collection."""
    result = _ReportAuthorization()
    selected_set = set(selected)

    for source in _DEFAULT_SOURCES:
        if source not in selected_set:
            continue
        if source == "github" and not get_settings().github_mcp_enabled:
            result.failures[source] = _github_disabled_result()
            continue

        try:
            if source == "github":
                access_token = await authorize_github_report_access()
            elif source == "email":
                access_token = await authorize_email_report_access()
            else:
                access_token = await authorize_calendar_report_access()
        except Exception:
            logger.warning(
                "Report source authorization unavailable source=%s",
                source,
            )
            _push_report_auth_failed(source)
            result.failures[source] = _authorization_failure(source)
            continue

        if not isinstance(access_token, str) or not access_token:
            logger.warning(
                "Report source authorization returned no token source=%s",
                source,
            )
            _push_report_auth_failed(source)
            result.failures[source] = _authorization_failure(source)
            continue
        result.access_tokens[source] = access_token

    return result


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc


def _parse_datetime(
    value: str | datetime,
    timezone: ZoneInfo,
    *,
    end_of_day_for_date: bool = False,
) -> datetime:
    if isinstance(value, datetime):
        parsed = value
        is_date_only = False
    else:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Datetime value cannot be empty")
        is_date_only = bool(_DATE_ONLY_PATTERN.fullmatch(normalized))
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid ISO 8601 datetime: {value}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    else:
        parsed = parsed.astimezone(timezone)
    if is_date_only and end_of_day_for_date:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed.replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def resolve_report_window(
    report_type: ReportType,
    *,
    reference_date: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    timezone: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> ReportWindow:
    """Resolve a report type without replacing an explicit user date."""
    if report_type not in _REPORT_TITLES:
        raise ValueError(f"Unsupported report_type: {report_type}")

    tz = _timezone(timezone)
    if (start_at is None) != (end_at is None):
        if reference_date is not None:
            raise ValueError(
                "reference_date cannot be combined with an incomplete explicit window"
            )
        reference_date = start_at or end_at
        start_at = None
        end_at = None

    if start_at is not None and end_at is not None:
        if reference_date is not None:
            raise ValueError(
                "reference_date cannot be combined with start_at and end_at"
            )
        start = _parse_datetime(start_at, tz)
        end = _parse_datetime(end_at, tz, end_of_day_for_date=True)
        if start > end:
            raise ValueError("start_at must not be later than end_at")
        return ReportWindow(
            start_at=_iso(start),
            end_at=_iso(end),
            timezone=timezone,
        )

    if report_type == "custom":
        raise ValueError("custom reports require both start_at and end_at")

    reference = (
        _parse_datetime(reference_date, tz)
        if reference_date is not None
        else now or datetime.now(tz)
    )
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=tz)
    else:
        reference = reference.astimezone(tz)
    reference = reference.replace(microsecond=0)

    if report_type == "daily":
        start = reference.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
    elif report_type == "weekly":
        start = (reference - timedelta(days=reference.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
        )
        end = start + timedelta(days=7) - timedelta(seconds=1)
    else:
        start = reference.replace(day=1, hour=0, minute=0, second=0)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(seconds=1)

    if start > end:
        raise ValueError("start_at must not be later than end_at")
    return ReportWindow(
        start_at=_iso(start),
        end_at=_iso(end),
        timezone=timezone,
    )


def select_report_sources(
    sources: Sequence[str] | None,
) -> tuple[ReportSource, ...]:
    """Validate and deduplicate sources; an empty selection means all defaults."""
    selected = list(sources) if sources else list(_DEFAULT_SOURCES)
    invalid = [source for source in selected if source not in _SOURCE_LABELS]
    if invalid:
        raise ValueError(f"Unsupported report source: {invalid[0]}")
    return tuple(dict.fromkeys(selected))  # type: ignore[return-value]


def _safe_text(value: Any, *, limit: int = 300) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    text = _AUTHORIZATION_CREDENTIAL_PATTERN.sub("[REDACTED]", text)
    text = _BEARER_CREDENTIAL_PATTERN.sub("[REDACTED]", text)
    text = _GITHUB_CREDENTIAL_PATTERN.sub("[REDACTED]", text)
    text = _ASSIGNED_CREDENTIAL_PATTERN.sub("[REDACTED]", text)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _safe_text(raw_key, limit=120)
            normalized_key = re.sub(r"[^a-z0-9_]+", "_", key.lower()).strip("_")
            if not key or normalized_key in {"ak", "sk"}:
                continue
            if any(part in normalized_key for part in _WARNING_TYPE_SENSITIVE_PARTS):
                continue
            cleaned[key] = _safe_metadata(raw_value)
        return cleaned
    if isinstance(value, set):
        return [_safe_metadata(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, limit=500)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value, limit=500)


def _safe_warning_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    has_sensitive_part = any(
        part in normalized for part in _WARNING_TYPE_SENSITIVE_PARTS
    )
    if not normalized or has_sensitive_part:
        return "source_unavailable"
    return normalized


def _warning(
    source: ReportSource,
    warning_type: str,
    message: str,
    *,
    retryable: bool = False,
) -> ReportWarning:
    return ReportWarning(
        source=source,
        warning_type=_safe_warning_type(warning_type),
        message=_safe_text(message),
        retryable=retryable,
    )


def _window_datetimes(window: ReportWindow) -> tuple[datetime, datetime]:
    tz = _timezone(window.timezone)
    return (
        _parse_datetime(window.start_at, tz),
        _parse_datetime(window.end_at, tz),
    )


def _event_datetime(
    value: Any,
    window: ReportWindow,
    *,
    fallback_timezone: str | None = None,
) -> datetime | None:
    report_timezone = _timezone(window.timezone)
    if isinstance(value, dict):
        raw_value = value.get("dateTime")
        source_timezone = value.get("timeZone")
        if not isinstance(raw_value, (str, datetime)) or not raw_value:
            return None
        parsed_timezone = report_timezone
        for candidate in (source_timezone, fallback_timezone):
            if not isinstance(candidate, str) or not candidate:
                continue
            try:
                parsed_timezone = _timezone(candidate)
                break
            except ValueError:
                continue
        try:
            parsed = _parse_datetime(raw_value, parsed_timezone)
        except ValueError:
            return None
        return parsed.astimezone(report_timezone)
    if not isinstance(value, (str, datetime)) or not value:
        return None
    try:
        return _parse_datetime(value, report_timezone)
    except ValueError:
        return None


def _is_in_window(value: datetime, window: ReportWindow) -> bool:
    start, end = _window_datetimes(window)
    return start <= value <= end


def _overlaps_window(
    start_at: datetime,
    end_at: datetime | None,
    window: ReportWindow,
) -> bool:
    if end_at is None or end_at == start_at:
        return _is_in_window(start_at, window)
    if end_at < start_at:
        return False
    window_start, window_end = _window_datetimes(window)
    return start_at <= window_end and end_at > window_start


def _source_id(*parts: Any) -> str:
    return ":".join(_safe_text(part, limit=160) for part in parts if part is not None)


async def _collect_email_evidence(
    window: ReportWindow,
    *,
    access_token: str,
    progress: _ReportProgressEmitter | None = None,
) -> _SourceResult:
    result = _SourceResult()
    successful_folders = 0
    if progress is not None:
        progress.emit(
            source="email",
            stage="email_collection",
            status="running",
            current=0,
            total=len(_EMAIL_FOLDERS),
            discovered=0,
            force=True,
        )

    for folder_index, folder in enumerate(_EMAIL_FOLDERS, start=1):
        try:
            response = await list_emails(
                folder=folder,
                limit=_EMAIL_LIMIT_PER_FOLDER,
                access_token=access_token,
            )
        except Exception:
            response = {"error": "unavailable"}

        if not isinstance(response, dict) or response.get("error"):
            result.warnings.append(
                _warning(
                    "email",
                    "email_folder_unavailable",
                    f"邮件文件夹 {folder} 暂不可用。",
                    retryable=True,
                )
            )
            if progress is not None:
                progress.emit(
                    source="email",
                    stage="email_collection",
                    status="running",
                    current=folder_index,
                    total=len(_EMAIL_FOLDERS),
                    discovered=len(result.evidence),
                    force=True,
                )
            continue

        successful_folders += 1
        emails = response.get("emails")
        if not isinstance(emails, list):
            emails = []
        for item in emails:
            if not isinstance(item, dict):
                continue
            occurred = _event_datetime(item.get("receivedDateTime"), window)
            if occurred is None or not _is_in_window(occurred, window):
                continue
            title = _safe_text(item.get("subject") or "(无主题)", limit=180)
            sender = _safe_text(item.get("from") or "", limit=120)
            preview = _safe_text(item.get("bodyPreview") or "", limit=240)
            summary_parts = [f"文件夹：{folder}"]
            if sender:
                summary_parts.append(f"发件人：{sender}")
            if preview:
                summary_parts.append(preview)
            message_id = item.get("id") or f"{folder}:{_iso(occurred)}:{title}"
            result.evidence.append(
                ReportEvidence(
                    source="email",
                    source_id=_source_id(message_id),
                    title=title,
                    occurred_at=_iso(occurred),
                    summary="；".join(summary_parts),
                    metadata={
                        "folder": folder,
                        "sender": sender,
                        "importance": _safe_text(item.get("importance") or "normal"),
                        "is_read": item.get("isRead"),
                    },
                )
            )

        count = response.get("count")
        if isinstance(count, int) and count >= _EMAIL_LIMIT_PER_FOLDER:
            result.warnings.append(
                _warning(
                    "email",
                    "email_result_limited",
                    f"邮件文件夹 {folder} 已达到单次采集上限，结果可能不完整。",
                )
            )

        if progress is not None:
            progress.emit(
                source="email",
                stage="email_collection",
                status="running",
                current=folder_index,
                total=len(_EMAIL_FOLDERS),
                discovered=len(result.evidence),
                force=True,
            )

    if successful_folders == 0:
        result.coverage = "unavailable"
    elif result.warnings:
        result.coverage = "partial"
    if progress is not None:
        progress.emit(
            source="email",
            stage="email_collection",
            status=("failed" if result.coverage == "unavailable" else "complete"),
            current=len(_EMAIL_FOLDERS),
            total=len(_EMAIL_FOLDERS),
            discovered=len(result.evidence),
            force=True,
        )
    return result


async def _collect_calendar_evidence(
    window: ReportWindow,
    *,
    access_token: str,
    progress: _ReportProgressEmitter | None = None,
) -> _SourceResult:
    if progress is not None:
        progress.emit(
            source="calendar",
            stage="calendar_collection",
            status="running",
            current=0,
            total=1,
            discovered=0,
            force=True,
        )
    try:
        response = await list_calendar_events(
            start_time=window.start_at,
            end_time=window.end_at,
            calendar_id="primary",
            limit=_CALENDAR_LIMIT,
            access_token=access_token,
        )
    except Exception:
        response = {"error": "unavailable"}

    if not isinstance(response, dict) or response.get("error"):
        if progress is not None:
            progress.emit(
                source="calendar",
                stage="calendar_collection",
                status="failed",
                current=0,
                total=1,
                discovered=0,
                force=True,
            )
        return _SourceResult(
            warnings=[
                _warning(
                    "calendar",
                    "calendar_unavailable",
                    "日历数据源暂不可用。",
                    retryable=True,
                )
            ],
            coverage="unavailable",
        )

    result = _SourceResult()
    events = response.get("events")
    if not isinstance(events, list):
        events = []
    response_timezone = response.get("timezone")
    fallback_timezone = (
        response_timezone if isinstance(response_timezone, str) else None
    )
    for item in events:
        if not isinstance(item, dict):
            continue
        occurred = _event_datetime(
            item.get("start"),
            window,
            fallback_timezone=fallback_timezone,
        )
        ended = _event_datetime(
            item.get("end"),
            window,
            fallback_timezone=fallback_timezone,
        )
        if occurred is None or not _overlaps_window(occurred, ended, window):
            continue
        title = _safe_text(item.get("subject") or "(无标题)", limit=180)
        organizer_value = item.get("organizer")
        organizer = ""
        if isinstance(organizer_value, dict):
            organizer = _safe_text(
                organizer_value.get("name") or organizer_value.get("address") or "",
                limit=120,
            )
        location = _safe_text(item.get("location") or "", limit=120)
        preview = _safe_text(item.get("bodyPreview") or "", limit=240)
        summary_parts: list[str] = []
        if organizer:
            summary_parts.append(f"组织者：{organizer}")
        if location:
            summary_parts.append(f"地点：{location}")
        if preview:
            summary_parts.append(preview)
        event_id = item.get("id") or f"{_iso(occurred)}:{title}"
        attendees = item.get("attendees")
        result.evidence.append(
            ReportEvidence(
                source="calendar",
                source_id=_source_id(event_id),
                title=title,
                occurred_at=_iso(occurred),
                summary="；".join(summary_parts) or "日历事件",
                url=_safe_text(item.get("webLink") or "", limit=500) or None,
                metadata={
                    "location": location,
                    "organizer": organizer,
                    "attendee_count": (
                        len(attendees) if isinstance(attendees, list) else 0
                    ),
                    "is_online_meeting": bool(item.get("isOnlineMeeting")),
                    "end_at": _iso(ended) if ended is not None else None,
                },
            )
        )

    if response.get("has_more"):
        result.warnings.append(
            _warning(
                "calendar",
                "calendar_result_limited",
                "日历事件存在后续页，当前报表仅包含本次采集结果。",
            )
        )
        result.coverage = "partial"
    if progress is not None:
        progress.emit(
            source="calendar",
            stage="calendar_collection",
            status="complete",
            current=1,
            total=1,
            discovered=len(result.evidence),
            force=True,
        )
    return result


def _github_evidence(
    event: GitHubActivityEvent,
    window: ReportWindow,
    *,
    subject_login: str,
) -> ReportEvidence | None:
    occurred = _event_datetime(event.updated_at or event.created_at, window)
    if occurred is None or not _is_in_window(occurred, window):
        return None
    title = _safe_text(event.title or "(无标题)", limit=180)
    summary_parts = [
        _safe_text(event.summary or event.title or "GitHub 工程活动", limit=600)
    ]
    if event.state:
        summary_parts.append(f"状态：{_safe_text(event.state, limit=80)}")
    if event.metrics:
        metrics = ", ".join(
            f"{_safe_text(key, limit=80)}={_safe_text(value, limit=120)}"
            for key, value in sorted(event.metrics.items())
        )
        if metrics:
            summary_parts.append(f"指标：{metrics}")
    summary = _safe_text("；".join(summary_parts), limit=900)
    return ReportEvidence(
        source="github",
        source_id=_source_id(event.external_id),
        title=title,
        occurred_at=_iso(occurred),
        summary=summary,
        url=_safe_text(event.url or "", limit=500) or None,
        metadata={
            "repository": _safe_text(event.repository, limit=180),
            "event_type": event.event_type,
            "actor": _safe_text(event.actor or "", limit=120) or None,
            "state": _safe_text(event.state or "", limit=80) or None,
            "parent_external_id": _safe_text(
                event.parent_external_id or "",
                limit=120,
            )
            or None,
            "metrics": dict(event.metrics),
            "detail_available": bool(event.details),
            "subject_login": subject_login,
            "repository_scope": "oauth_accessible",
            "data_access_identity": "platform_mcp",
        },
    )


def _github_event_key(event: GitHubActivityEvent) -> tuple[str, str, str, str]:
    return (
        event.repository.casefold(),
        event.event_type,
        event.external_id,
        event.parent_external_id or "",
    )


def _github_event_time(event: GitHubActivityEvent, window: ReportWindow) -> float:
    occurred = _event_datetime(event.updated_at or event.created_at, window)
    return occurred.timestamp() if occurred is not None else float("-inf")


def _merge_github_detail(
    event: GitHubActivityEvent,
    detail: GitHubActivityEvent,
) -> GitHubActivityEvent | None:
    same_identity = (
        detail.event_type == event.event_type
        and detail.repository.casefold() == event.repository.casefold()
        and detail.external_id == event.external_id
    )
    if not same_identity:
        return None
    if (
        detail.actor
        and event.actor
        and detail.actor.casefold() != event.actor.casefold()
    ):
        return None
    return GitHubActivityEvent(
        provider=detail.provider or event.provider,
        event_type=event.event_type,
        repository=event.repository,
        external_id=event.external_id,
        title=detail.title or event.title,
        parent_external_id=event.parent_external_id,
        url=detail.url or event.url,
        actor=event.actor,
        state=detail.state or event.state,
        created_at=event.created_at or detail.created_at,
        updated_at=event.updated_at or detail.updated_at,
        summary=detail.summary or event.summary,
        metrics={**event.metrics, **detail.metrics},
        details={**event.details, **detail.details},
    )


def _github_detail_result(
    event: GitHubActivityEvent,
    detail: GitHubActivityEvent | GitHubMCPWarning | None,
) -> tuple[GitHubActivityEvent, GitHubMCPWarning | None]:
    if isinstance(detail, GitHubActivityEvent):
        merged = _merge_github_detail(event, detail)
        if merged is not None:
            return merged, None
        return (
            event,
            GitHubMCPWarning(
                ok=False,
                warning_type="detail_identity_mismatch",
                message="GitHub activity detail identity does not match search.",
            ),
        )
    if isinstance(detail, GitHubMCPWarning):
        return event, detail
    return (
        event,
        GitHubMCPWarning(
            ok=False,
            warning_type="detail_unavailable",
            message="GitHub activity detail is unavailable.",
            retryable=True,
        ),
    )


async def _github_event_detail(
    event: GitHubActivityEvent,
) -> tuple[GitHubActivityEvent, GitHubMCPWarning | None]:
    try:
        detail = await github_mcp_get_detail(
            event_type=event.event_type,
            repository=event.repository,
            external_id=event.external_id,
            parent_external_id=event.parent_external_id,
        )
    except Exception:
        detail = None
    return _github_detail_result(event, detail)


async def _collect_github_evidence(
    window: ReportWindow,
    *,
    access_token: str,
    progress: _ReportProgressEmitter | None = None,
) -> _SourceResult:
    if not get_settings().github_mcp_enabled:
        if progress is not None:
            progress.emit(
                source="github",
                stage="github_context",
                status="skipped",
                force=True,
            )
        return _github_disabled_result()

    if progress is not None:
        progress.emit(
            source="github",
            stage="github_context",
            status="running",
            force=True,
        )
    try:
        oauth_context = await get_github_report_context(access_token)
    except Exception:
        if progress is not None:
            progress.emit(
                source="github",
                stage="github_context",
                status="failed",
                force=True,
            )
        return _SourceResult(
            warnings=[
                _warning(
                    "github",
                    "github_oauth_unavailable",
                    "GitHub OAuth 授权或账号上下文暂不可用。",
                    retryable=True,
                )
            ],
            coverage="unavailable",
        )

    if not isinstance(oauth_context, GitHubReportContext):
        if progress is not None:
            progress.emit(
                source="github",
                stage="github_context",
                status="failed",
                force=True,
            )
        return _SourceResult(
            warnings=[
                _warning(
                    "github",
                    "github_oauth_unavailable",
                    "GitHub OAuth 账号上下文格式无效。",
                    retryable=True,
                )
            ],
            coverage="unavailable",
        )

    result = _SourceResult(
        context={
            "subject_login": oauth_context.login,
            "subject_user_id": oauth_context.user_id,
            "repository_scope": "oauth_accessible",
            "repository_count": len(oauth_context.repositories),
            "data_access_identity": "platform_mcp",
        }
    )
    if progress is not None:
        progress.emit(
            source="github",
            stage="github_context",
            status="complete",
            current=len(oauth_context.repositories),
            total=len(oauth_context.repositories),
            discovered=len(oauth_context.repositories),
            force=True,
        )
    if not oauth_context.repositories:
        if progress is not None:
            progress.emit(
                source="github",
                stage="activity_search",
                status="complete",
                current=0,
                total=0,
                discovered=0,
                force=True,
            )
        return result

    events_by_key: dict[tuple[str, str, str, str], GitHubActivityEvent] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    page_count = 0
    search_failed = False
    if progress is not None:
        progress.emit(
            source="github",
            stage="activity_search",
            status="running",
            current=0,
            discovered=0,
            force=True,
        )
    while True:
        try:
            response = await github_mcp_search_activity(
                start_at=window.start_at,
                end_at=window.end_at,
                timezone=window.timezone,
                repositories=list(oauth_context.repositories),
                actor=oauth_context.login,
                limit=_GITHUB_LIMIT,
                cursor=cursor,
            )
        except Exception:
            response = None
        if not isinstance(response, GitHubActivityResult):
            search_failed = True
            result.warnings.append(
                _warning(
                    "github",
                    "github_source_unavailable",
                    "GitHub MCP 工程活动数据源暂不可用。",
                    retryable=True,
                )
            )
            break
        page_count += 1
        for event in response.events:
            if (
                event.actor is not None
                and event.actor.casefold() == oauth_context.login.casefold()
            ):
                events_by_key[_github_event_key(event)] = event
        for warning in response.warnings:
            if (
                warning.warning_type == "pagination_budget_exhausted"
                and response.next_cursor
            ):
                continue
            result.warnings.append(
                _warning(
                    "github",
                    warning.warning_type,
                    "GitHub MCP 工程活动数据不完整。",
                    retryable=warning.retryable,
                )
            )
        if progress is not None:
            progress.emit(
                source="github",
                stage="activity_search",
                status="running",
                current=page_count,
                discovered=len(events_by_key),
            )
        next_cursor = response.next_cursor
        if not next_cursor:
            break
        if next_cursor in seen_cursors:
            result.warnings.append(
                _warning(
                    "github",
                    "github_cursor_repeated",
                    "GitHub MCP 分页游标重复，采集已提前停止。",
                    retryable=True,
                )
            )
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    if progress is not None:
        progress.emit(
            source="github",
            stage="activity_search",
            status="failed" if search_failed else "complete",
            current=page_count,
            total=None if search_failed else page_count,
            discovered=len(events_by_key),
            force=True,
        )

    ordered_events = sorted(
        events_by_key.values(),
        key=lambda event: (
            _github_event_time(event, window),
            _github_event_key(event),
        ),
        reverse=True,
    )
    if len(ordered_events) > _GITHUB_LIMIT:
        result.warnings.append(
            _warning(
                "github",
                "github_activity_truncated",
                f"GitHub 工程活动超过全局 {_GITHUB_LIMIT} 条上限，报告已截断。",
            )
        )
        ordered_events = ordered_events[:_GITHUB_LIMIT]

    if progress is not None:
        progress.emit(
            source="github",
            stage="activity_detail",
            status="running",
            current=0,
            total=len(ordered_events),
            discovered=len(ordered_events),
            force=True,
        )

    def _detail_progress(current: int, total: int) -> None:
        if progress is not None:
            progress.emit(
                source="github",
                stage="activity_detail",
                status="running",
                current=current,
                total=total,
                discovered=len(ordered_events),
            )

    try:
        detail_results = await github_mcp_get_details(
            ordered_events,
            on_progress=_detail_progress,
        )
    except Exception:
        detail_results = []
    for index, event in enumerate(ordered_events):
        detail = detail_results[index] if index < len(detail_results) else None
        detailed, detail_warning = _github_detail_result(event, detail)
        evidence = _github_evidence(
            detailed,
            window,
            subject_login=oauth_context.login,
        )
        if evidence is not None:
            result.evidence.append(evidence)
        if detail_warning is not None:
            result.warnings.append(
                _warning(
                    "github",
                    detail_warning.warning_type,
                    "一条 GitHub 工程活动的详细信息不可用，已保留搜索摘要。",
                    retryable=detail_warning.retryable,
                )
            )

    if result.warnings:
        result.coverage = "partial" if result.evidence else "unavailable"
    if progress is not None:
        progress.emit(
            source="github",
            stage="activity_detail",
            status=("failed" if result.coverage == "unavailable" else "complete"),
            current=len(ordered_events),
            total=len(ordered_events),
            discovered=len(result.evidence),
            force=True,
        )
    return result


def _deduplicate_evidence(items: list[ReportEvidence]) -> list[ReportEvidence]:
    unique: dict[tuple[str, str, str, str], ReportEvidence] = {}
    for item in items:
        unique[
            (
                item.source,
                item.source_id,
                str(item.metadata.get("repository") or ""),
                str(item.metadata.get("event_type") or ""),
            )
        ] = item
    return sorted(
        unique.values(),
        key=lambda item: (item.occurred_at, item.source, item.source_id),
        reverse=True,
    )


def _deduplicate_warnings(items: list[ReportWarning]) -> list[ReportWarning]:
    unique: dict[tuple[str, str, str, bool], ReportWarning] = {}
    for item in items:
        unique[(item.source, item.warning_type, item.message, item.retryable)] = item
    return list(unique.values())


def _build_markdown(
    report_type: ReportType,
    window: ReportWindow,
    audience: ReportAudience,
    evidence: list[ReportEvidence],
    warnings: list[ReportWarning],
    coverage: dict[ReportSource, SourceCoverage],
    source_context: dict[ReportSource, dict[str, Any]],
) -> str:
    audience_label = "个人" if audience == "self" else "团队"
    lines = [
        f"# {_REPORT_TITLES[report_type]}",
        "",
        f"- 时间范围：{window.start_at} 至 {window.end_at}",
        f"- 时区：{window.timezone}",
        f"- 面向对象：{audience_label}",
        "",
        "## 摘要",
        "",
        f"共整理 {len(evidence)} 条可引用证据。",
    ]
    for source in _DEFAULT_SOURCES:
        count = sum(item.source == source for item in evidence)
        lines.append(
            f"- {_SOURCE_LABELS[source]}：{count} 条，覆盖状态 {coverage[source]}"
        )

    for source in _DEFAULT_SOURCES:
        source_items = [item for item in evidence if item.source == source]
        if coverage[source] == "skipped":
            continue
        lines.extend(["", f"## {_SOURCE_LABELS[source]}", ""])
        if source == "github":
            github_context = source_context.get("github", {})
            subject_login = _safe_text(
                github_context.get("subject_login"),
                limit=120,
            )
            repository_count = github_context.get("repository_count")
            if subject_login:
                lines.append(f"- OAuth 账号：{subject_login}")
            if isinstance(repository_count, int):
                lines.append(
                    f"- 仓库范围：OAuth 账号可访问的全部 {repository_count} 个仓库"
                )
            if subject_login or isinstance(repository_count, int):
                lines.append(
                    "- 活动读取：Feature-17 GitHub MCP；仅保留该 OAuth 账号的活动"
                )
        if not source_items:
            lines.append("本时间范围内没有可用证据。")
            continue
        for item in source_items[:_MAX_ITEMS_PER_SECTION]:
            lines.append(f"- {item.occurred_at} | {item.title}：{item.summary}")
        remaining = len(source_items) - _MAX_ITEMS_PER_SECTION
        if remaining > 0:
            lines.append(f"- 另有 {remaining} 条证据可在结构化 evidence 中查看。")

    lines.extend(["", "## 数据覆盖与提醒", ""])
    if not warnings:
        lines.append("所有已选择数据源均完成本次采集。")
    else:
        for warning in warnings:
            lines.append(
                f"- {_SOURCE_LABELS[warning.source]} / "
                f"{warning.warning_type}：{warning.message}"
            )
    return "\n".join(lines)


async def _collect_authorized_source(
    source: ReportSource,
    window: ReportWindow,
    access_token: str,
    progress: _ReportProgressEmitter,
) -> _SourceResult:
    try:
        if source == "email":
            return await _collect_email_evidence(
                window,
                access_token=access_token,
                progress=progress,
            )
        if source == "calendar":
            return await _collect_calendar_evidence(
                window,
                access_token=access_token,
                progress=progress,
            )
        return await _collect_github_evidence(
            window,
            access_token=access_token,
            progress=progress,
        )
    except Exception:
        logger.warning("Report source collection failed source=%s", source)
        progress.emit(
            source=source,
            stage=_source_progress_stage(source),
            status="failed",
            force=True,
        )
        return _collection_failure(source)


async def generate_report(
    report_type: ReportType = "daily",
    reference_date: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    timezone: str = "Asia/Shanghai",
    sources: list[ReportSource] | None = None,
    audience: ReportAudience = "self",
    format: ReportFormat = "markdown",
) -> dict[str, Any]:
    """Generate a daily, weekly, monthly, or custom report.

    Use this high-level tool for reports, work summaries, and engineering progress
    summaries. By default it deterministically combines Email, Calendar, and
    GitHub activity authored by the current GitHub OAuth account across every
    repository that account can access. GitHub activity is read through the
    Feature 17 MCP source using the OAuth account as the fixed actor and the OAuth
    repository list as an allowlist. Selected sources complete authorization in
    GitHub, Email, Calendar order before any source starts collecting data.
    Individual source failures are returned as warnings while the remaining
    sources continue. When the user provides one date, pass it as reference_date;
    when they provide a date range, pass start_at and end_at. Explicit dates always
    override the current date.
    """
    if audience not in {"self", "team"}:
        raise ValueError(f"Unsupported audience: {audience}")
    if format != "markdown":
        raise ValueError("Only markdown report format is supported")

    window = resolve_report_window(
        report_type,
        reference_date=reference_date,
        start_at=start_at,
        end_at=end_at,
        timezone=timezone,
    )
    selected = select_report_sources(sources)
    coverage: dict[ReportSource, SourceCoverage] = dict.fromkeys(
        _DEFAULT_SOURCES,
        "skipped",
    )
    evidence: list[ReportEvidence] = []
    warnings: list[ReportWarning] = []
    source_context: dict[ReportSource, dict[str, Any]] = {}
    progress = _ReportProgressEmitter()
    progress.emit(stage="preparing", status="running", force=True)
    authorization = await _authorize_report_sources(selected)
    progress.emit(stage="preparing", status="complete", force=True)

    source_results = dict(authorization.failures)
    collection_sources: list[ReportSource] = []
    collection_coroutines = []
    for source in selected:
        if source in source_results:
            disabled = any(
                warning.warning_type == "github_source_disabled"
                for warning in source_results[source].warnings
            )
            progress.emit(
                source=source,
                stage=_source_progress_stage(source),
                status="skipped" if disabled else "failed",
                force=True,
            )
            continue
        access_token = authorization.access_tokens.get(source)
        if access_token is None:
            source_results[source] = _authorization_failure(source)
            progress.emit(
                source=source,
                stage=_source_progress_stage(source),
                status="failed",
                force=True,
            )
            continue
        collection_sources.append(source)
        collection_coroutines.append(
            _collect_authorized_source(source, window, access_token, progress)
        )

    collected_results = await asyncio.gather(*collection_coroutines)
    source_results.update(zip(collection_sources, collected_results, strict=True))

    for source in selected:
        source_result = source_results[source]
        evidence.extend(source_result.evidence)
        warnings.extend(source_result.warnings)
        coverage[source] = source_result.coverage
        if source_result.context:
            source_context[source] = source_result.context

    progress.emit(stage="rendering", status="running", force=True)
    normalized_evidence = _deduplicate_evidence(evidence)
    normalized_warnings = _deduplicate_warnings(warnings)
    content = _build_markdown(
        report_type,
        window,
        audience,
        normalized_evidence,
        normalized_warnings,
        coverage,
        source_context,
    )
    result = ReportResult(
        report_type=report_type,
        window=window,
        content=content,
        evidence=normalized_evidence,
        warnings=normalized_warnings,
        source_coverage=coverage,
        source_context=source_context,
    ).to_dict()
    progress.emit(stage="rendering", status="complete", force=True)
    _push_report_ready(
        content=content,
        filename=_report_filename(report_type, window),
        report_type=report_type,
        window=window,
    )
    return result


REPORT_TOOLS = [generate_report]
