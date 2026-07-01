"""Structured logging formatters, filters, and request correlation middleware."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from agentarts.sdk.runtime.model import SESSION_HEADER

from app.settings import get_settings

SERVICE_NAME = "personal-assistant"
SERVICE_VERSION = "0.1.0"
REQUEST_ID_HEADER = b"x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_request_id: ContextVar[str | None] = ContextVar("log_request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("log_session_id", default=None)

try:
    from opentelemetry import trace
except ImportError:  # pragma: no cover - optional runtime integration
    trace = None


def _utc_timestamp(created: float) -> str:
    return datetime.fromtimestamp(created, tz=UTC).isoformat(timespec="milliseconds")


def _trace_context() -> tuple[str | None, str | None]:
    if trace is None:
        return None, None

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}"


class RuntimeLevelFilter(logging.Filter):
    """Apply the configured LOG_LEVEL uniformly to every shared handler."""

    def __init__(self) -> None:
        super().__init__()
        self.minimum_level = logging.getLevelNamesMapping()[get_settings().log_level]

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.minimum_level


class ContextFilter(logging.Filter):
    """Attach request, session, and OpenTelemetry correlation fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.session_id = _session_id.get()
        record.trace_id, record.span_id = _trace_context()
        return True


class ConsoleFormatter(logging.Formatter):
    """Human-readable UTC formatter for local development."""

    def formatTime(  # noqa: N802 - logging.Formatter public override
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        del datefmt
        return _utc_timestamp(record.created)


class JsonFormatter(logging.Formatter):
    """Single-line JSON formatter using an OpenTelemetry-aligned field schema."""

    _OPTIONAL_FIELDS = {
        "event.name": "event_name",
        "request.id": "request_id",
        "session.id": "session_id",
        "trace_id": "trace_id",
        "span_id": "span_id",
        "http.request.method": "http_method",
        "url.path": "url_path",
        "url.raw_path": "url_raw_path",
        "url.root_path": "url_root_path",
        "http.route": "http_route",
        "http.response.status_code": "http_status_code",
        "duration_ms": "duration_ms",
        "status": "status",
        "invocation.mode": "invocation_mode",
    }

    def __init__(
        self,
        *,
        environment: str,
        service_name: str = SERVICE_NAME,
        service_version: str = SERVICE_VERSION,
    ) -> None:
        super().__init__()
        self.environment = environment
        self.service_name = service_name
        self.service_version = service_version

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _utc_timestamp(record.created),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service.name": self.service_name,
            "service.version": self.service_version,
            "deployment.environment": self.environment,
        }
        for output_name, record_name in self._OPTIONAL_FIELDS.items():
            value = getattr(record, record_name, None)
            if value is not None:
                payload[output_name] = value

        if record.exc_info:
            payload["exception.type"] = record.exc_info[0].__name__
            payload["exception.message"] = str(record.exc_info[1])
            payload["exception.stacktrace"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _header_value(scope: dict[str, Any], name: bytes) -> str | None:
    for header_name, value in scope.get("headers", []):
        if header_name.lower() == name:
            return value.decode("latin-1").strip() or None
    return None


def _request_identifier(scope: dict[str, Any]) -> str:
    supplied = _header_value(scope, REQUEST_ID_HEADER)
    if supplied and _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


class RequestLoggingMiddleware:
    """Record one structured completion event for each non-health HTTP request."""

    def __init__(self, app) -> None:
        self.app = app
        self.logger = logging.getLogger("app.http")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_identifier(scope)
        session_id = _header_value(scope, SESSION_HEADER.lower().encode("latin-1"))
        request_token: Token[str | None] = _request_id.set(request_id)
        session_token: Token[str | None] = _session_id.set(session_id)
        started_at = time.perf_counter()
        status_code = 500
        completed = False

        async def send_with_context(message) -> None:
            nonlocal completed, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                completed = True

            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            self._log_completion(scope, 500, started_at, "error", exc_info=True)
            raise
        else:
            if completed and scope.get("path") != "/ping":
                status = "success" if status_code < 400 else "error"
                self._log_completion(scope, status_code, started_at, status)
        finally:
            _session_id.reset(session_token)
            _request_id.reset(request_token)

    def _log_completion(
        self,
        scope: dict[str, Any],
        status_code: int,
        started_at: float,
        status: str,
        *,
        exc_info: bool = False,
    ) -> None:
        route = scope.get("route")
        route_path = getattr(route, "path", None)
        level = logging.ERROR if status_code >= 500 else logging.INFO
        raw_path = scope.get("raw_path")
        if isinstance(raw_path, bytes):
            raw_path = raw_path.decode("latin-1", errors="replace")
        if status_code == 404:
            self.logger.info(
                "HTTP request returned 404",
                extra={
                    "event_name": "http.request.not_found",
                    "http_method": scope.get("method"),
                    "url_path": scope.get("path"),
                    "url_raw_path": raw_path,
                    "url_root_path": scope.get("root_path"),
                    "http_route": route_path,
                    "http_status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "status": status,
                },
            )
        self.logger.log(
            level,
            "HTTP request completed",
            exc_info=exc_info,
            extra={
                "event_name": "http.request.completed",
                "http_method": scope.get("method"),
                "url_path": scope.get("path"),
                "url_raw_path": raw_path,
                "url_root_path": scope.get("root_path"),
                "http_route": route_path,
                "http_status_code": status_code,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "status": status,
            },
        )
