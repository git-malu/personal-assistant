"""Tests for structured logging formatters and configuration contracts."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.logging_config import (
    ContextFilter,
    JsonFormatter,
    RequestLoggingMiddleware,
    RuntimeLevelFilter,
)
from app.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_dev_and_prod_configs_cover_the_same_loggers():
    dev = yaml.safe_load((PROJECT_ROOT / "config/logging.dev.yaml").read_text())
    prod = yaml.safe_load((PROJECT_ROOT / "config/logging.prod.yaml").read_text())

    expected = {"app", "agentarts", "uvicorn", "uvicorn.error", "uvicorn.access"}
    assert set(dev["loggers"]) == expected
    assert set(prod["loggers"]) == expected
    assert dev["loggers"]["agentarts"]["handlers"] == []
    assert prod["loggers"]["agentarts"]["handlers"] == []
    assert dev["loggers"]["agentarts"]["propagate"] is True
    assert prod["loggers"]["agentarts"]["propagate"] is True
    assert dev["loggers"]["uvicorn.access"]["handlers"] == []
    assert prod["loggers"]["uvicorn.access"]["handlers"] == []


def test_prod_logging_config_uses_console_formatter():
    prod = yaml.safe_load((PROJECT_ROOT / "config/logging.prod.yaml").read_text())

    assert prod["formatters"] == {
        "console": {
            "()": "app.logging_config.ConsoleFormatter",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        }
    }
    assert prod["handlers"]["console"]["formatter"] == "console"


def test_json_formatter_emits_standard_fields():
    record = logging.LogRecord(
        name="app.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP request completed",
        args=(),
        exc_info=None,
    )
    record.event_name = "http.request.completed"
    record.request_id = "req-123"
    record.session_id = "session-456"
    record.http_method = "POST"
    record.http_route = "/invocations"
    record.http_status_code = 200
    record.duration_ms = 12.34
    record.status = "success"

    payload = json.loads(JsonFormatter(environment="test").format(record))

    assert payload["timestamp"].endswith("+00:00")
    assert payload["severity"] == "INFO"
    assert payload["service.name"] == "personal-assistant"
    assert payload["deployment.environment"] == "test"
    assert payload["event.name"] == "http.request.completed"
    assert payload["request.id"] == "req-123"
    assert payload["session.id"] == "session-456"
    assert payload["http.response.status_code"] == 200
    assert payload["duration_ms"] == 12.34


def test_context_filter_always_defines_optional_correlation_fields():
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Started server",
        args=(),
        exc_info=None,
    )

    assert ContextFilter().filter(record) is True
    assert hasattr(record, "request_id")
    assert hasattr(record, "session_id")
    assert hasattr(record, "trace_id")
    assert hasattr(record, "span_id")


def test_runtime_level_filter_uses_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    level_filter = RuntimeLevelFilter()
    info = logging.LogRecord("app", logging.INFO, __file__, 1, "info", (), None)
    warning = logging.LogRecord(
        "app",
        logging.WARNING,
        __file__,
        1,
        "warning",
        (),
        None,
    )

    assert level_filter.filter(info) is False
    assert level_filter.filter(warning) is True
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_request_middleware_correlates_http_completion_event():
    records: list[logging.LogRecord] = []
    sent_messages = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    async def application(scope, receive, send):
        del receive
        scope["route"] = SimpleNamespace(path="/invocations")
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"bad request"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    logger = logging.getLogger("app.http")
    old_handlers = logger.handlers
    old_level = logger.level
    old_propagate = logger.propagate
    handler = CaptureHandler()
    handler.addFilter(ContextFilter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        middleware = RequestLoggingMiddleware(application)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/invocations",
                "headers": [
                    (b"x-request-id", b"request-123"),
                    (b"x-hw-agentarts-session-id", b"session-456"),
                ],
            },
            receive,
            send,
        )
    finally:
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    response_start = sent_messages[0]
    assert (b"x-request-id", b"request-123") in response_start["headers"]
    assert len(records) == 1
    assert records[0].event_name == "http.request.completed"
    assert records[0].request_id == "request-123"
    assert records[0].session_id == "session-456"
    assert records[0].http_route == "/invocations"
    assert records[0].http_status_code == 400
