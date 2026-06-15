"""Thin AgentArts SDK adapters for runtime context and credential decorators."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from agentarts.sdk.service.identity.polling.token_poller import TokenPoller

DEFAULT_GITHUB_SCOPES = ("repo", "read:user")
GITHUB_PROVIDER_NAME = "github-provider"
GITHUB_OAUTH2_CALLBACK_URL_ENV = "AGENTARTS_GITHUB_OAUTH2_CALLBACK_URL"
OAUTH2_CUSTOM_STATE_HEADER = "X-HW-AgentArts-OAuth2-Custom-State"
REQUEST_ID_HEADER = "X-Request-Id"

_GITHUB_AUTHORIZATION_URL: ContextVar[str | None] = ContextVar(
    "github_authorization_url",
    default=None,
)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"
_service_config: dict[str, Any] | None = None


@dataclass(slots=True)
class AuthorizationRequired(Exception):  # noqa: N818
    """Signal that end-user consent is required before an access token exists."""

    provider_name: str
    authorization_url: str | None = None
    message: str = "GitHub authorization is required"

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclass(frozen=True, slots=True)
class RuntimeIdentityContext:
    """Snapshot of the AgentArts runtime context for this request."""

    user_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    workload_access_token: str | None = None
    oauth2_custom_state: str | None = None
    user_token: str | None = None


class MissingAgentIdentityTokenError(RuntimeError):
    """Raised when AgentArts Identity returns an empty credential."""


def _clean(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _load_service_config() -> dict[str, Any]:
    global _service_config
    if _service_config is None:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                _service_config = yaml.safe_load(f) or {}
        else:
            _service_config = {}
    return _service_config


def get_runtime_user_id() -> str | None:
    return AgentArtsRuntimeContext.get_user_id()


def get_runtime_session_id() -> str | None:
    return AgentArtsRuntimeContext.get_session_id()


def get_github_oauth2_callback_url() -> str | None:
    env_callback_url = _clean(os.environ.get(GITHUB_OAUTH2_CALLBACK_URL_ENV))
    if env_callback_url:
        return env_callback_url

    identity_cfg = _load_service_config().get("identity", {})
    github_cfg = identity_cfg.get("github", {})
    callback_url = github_cfg.get("oauth2_callback_url")
    return _clean(callback_url)


def capture_runtime_context() -> RuntimeIdentityContext:
    """Capture the SDK runtime context so streaming responses can restore it."""

    return RuntimeIdentityContext(
        user_id=AgentArtsRuntimeContext.get_user_id(),
        session_id=AgentArtsRuntimeContext.get_session_id(),
        request_id=AgentArtsRuntimeContext.get_request_id(),
        workload_access_token=AgentArtsRuntimeContext.get_workload_access_token(),
        oauth2_custom_state=AgentArtsRuntimeContext.get_oauth2_custom_state(),
        user_token=AgentArtsRuntimeContext.get_user_token(),
    )


def _apply_runtime_context(context: RuntimeIdentityContext) -> None:
    AgentArtsRuntimeContext.set_user_id(context.user_id)
    AgentArtsRuntimeContext.set_session_id(context.session_id)
    AgentArtsRuntimeContext.set_request_id(context.request_id)
    AgentArtsRuntimeContext.set_workload_access_token(context.workload_access_token)
    AgentArtsRuntimeContext.set_oauth2_custom_state(context.oauth2_custom_state)
    AgentArtsRuntimeContext.set_user_token(context.user_token)


@contextmanager
def runtime_context_scope(
    context: RuntimeIdentityContext | None = None,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    workload_access_token: str | None = None,
    oauth2_custom_state: str | None = None,
    user_token: str | None = None,
) -> Iterator[None]:
    """Temporarily seed AgentArtsRuntimeContext using public SDK setters."""

    previous = capture_runtime_context()
    next_context = context or RuntimeIdentityContext(
        user_id=user_id if user_id is not None else previous.user_id,
        session_id=session_id if session_id is not None else previous.session_id,
        request_id=request_id if request_id is not None else previous.request_id,
        workload_access_token=(
            workload_access_token
            if workload_access_token is not None
            else previous.workload_access_token
        ),
        oauth2_custom_state=(
            oauth2_custom_state
            if oauth2_custom_state is not None
            else previous.oauth2_custom_state
        ),
        user_token=user_token if user_token is not None else previous.user_token,
    )
    _apply_runtime_context(next_context)
    try:
        yield
    finally:
        _apply_runtime_context(previous)


@contextmanager
def request_runtime_context(headers: Any) -> Iterator[RuntimeIdentityContext]:
    """Load AgentArts Gateway headers into the SDK runtime context."""

    request_id = _clean(headers.get(REQUEST_ID_HEADER)) or str(uuid.uuid4())
    context = RuntimeIdentityContext(
        user_id=_clean(headers.get(USER_ID_HEADER)),
        session_id=_clean(headers.get(SESSION_HEADER)),
        request_id=request_id,
        workload_access_token=_clean(headers.get(ACCESS_TOKEN_HEADER)),
        oauth2_custom_state=_clean(headers.get(OAUTH2_CUSTOM_STATE_HEADER)),
    )
    with runtime_context_scope(context):
        yield context


def capture_github_authorization_url(url: str) -> None:
    _GITHUB_AUTHORIZATION_URL.set(url)


@dataclass(slots=True)
class GitHubAuthorizationRequiredPoller(TokenPoller):
    provider_name: str = GITHUB_PROVIDER_NAME

    async def poll_for_token(self) -> str:
        raise AuthorizationRequired(
            provider_name=self.provider_name,
            authorization_url=_GITHUB_AUTHORIZATION_URL.get(),
        )
