"""Shared helpers for Agent Identity maintenance scripts."""

from __future__ import annotations

import os
from typing import Any

from huaweicloudsdkagentidentity.v1 import AgentIdentityClient
from huaweicloudsdkagentidentity.v1.region.agentidentity_region import (
    AgentIdentityRegion,
)
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions.exceptions import SdkException
from huaweicloudsdkcore.utils.http_utils import sanitize_for_serialization

DEFAULT_REGION = "cn-southwest-2"

AK_ENV_NAMES = ("HUAWEICLOUD_SDK_AK", "HUAWEICLOUD_AK", "HW_ACCESS_KEY")
SK_ENV_NAMES = ("HUAWEICLOUD_SDK_SK", "HUAWEICLOUD_SK", "HW_SECRET_KEY")
SECURITY_TOKEN_ENV_NAMES = (
    "HUAWEICLOUD_SDK_SECURITY_TOKEN",
    "HUAWEICLOUD_SECURITY_TOKEN",
    "HW_SECURITY_TOKEN",
)


def first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def required_env(names: tuple[str, ...], label: str) -> str:
    value = first_env(names)
    if value:
        return value
    names_text = ", ".join(names)
    raise RuntimeError(f"Missing {label}. Set one of: {names_text}")


def build_credentials() -> BasicCredentials:
    credentials = BasicCredentials(
        required_env(AK_ENV_NAMES, "Huawei Cloud AK"),
        required_env(SK_ENV_NAMES, "Huawei Cloud SK"),
    )
    security_token = first_env(SECURITY_TOKEN_ENV_NAMES)
    if security_token:
        credentials.with_security_token(security_token)
    return credentials


def build_client(region: str, endpoint: str | None) -> AgentIdentityClient:
    builder = AgentIdentityClient.new_builder().with_credentials(build_credentials())
    builder.with_region(AgentIdentityRegion.value_of(region))
    if endpoint:
        builder.with_endpoint(endpoint)
    return builder.build()


def as_dict(value: Any) -> dict[str, Any]:
    serialized = sanitize_for_serialization(value)
    return serialized if isinstance(serialized, dict) else {}


def dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def sdk_exception_text(exc: SdkException) -> str:
    fields = []
    for attr in ("status_code", "request_id", "error_code", "error_msg"):
        value = getattr(exc, attr, None)
        if value:
            fields.append(f"{attr}={value}")
    details = ", ".join(fields)
    if details:
        return f"{exc.__class__.__name__}: {details}"
    return f"{exc.__class__.__name__}: {exc}"
